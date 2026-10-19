"""Local metadata and validation-result catalog with credential-free connection metadata."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

from filelock import FileLock

from app.core.config import get_settings
from app.models.database import DatabaseModel

VERSION = 2
CONNECTION_FIELDS = (
    "type", "platform", "host", "port", "database", "service", "username", "auth_method", "ssl",
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def connection_metadata(connection) -> dict:
    values = connection.model_dump(mode="json") if hasattr(connection, "model_dump") else connection
    return {key: values.get(key) for key in CONNECTION_FIELDS}


def identity(connection) -> str:
    encoded = json.dumps(connection_metadata(connection), sort_keys=True).encode()
    return hashlib.sha256(encoded).hexdigest()


class Catalog:
    def __init__(self, path: Path | None = None):
        self.path = Path(path or get_settings().catalog_path)
        self.initialize()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.create_function("casefold", 1, lambda value: value.casefold())
        connection.execute("PRAGMA foreign_keys=ON")
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def initialize(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.path) + ".lock", timeout=30), self.connect() as connection:
            version = connection.execute("PRAGMA user_version").fetchone()[0]
            if version == VERSION:
                return
            if version == 1:
                destination = (
                    self.path.parent / "backups" / f"catalog-v1-{uuid.uuid4().hex}.sqlite3"
                )
                destination.parent.mkdir(exist_ok=True)
                with sqlite3.connect(destination) as backup:
                    connection.backup(backup)
                self._upgrade_results(connection)
                return
            if version != 0:
                raise ValueError(f"Unsupported catalog version {version}; data was not changed")
            tables = connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
            if tables:
                raise ValueError("Unversioned catalog contains tables; refusing to overwrite it")
            connection.executescript("""
                BEGIN IMMEDIATE;
                CREATE TABLE connections (
                    id TEXT PRIMARY KEY, label TEXT NOT NULL, identity TEXT NOT NULL,
                    metadata TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    deleted INTEGER NOT NULL DEFAULT 0
                );
                CREATE INDEX connection_identity ON connections(identity);
                CREATE TABLE inventories (
                    id TEXT PRIMARY KEY, identity TEXT NOT NULL, created_at TEXT NOT NULL,
                    metadata TEXT NOT NULL, complete INTEGER NOT NULL,
                    format_version INTEGER NOT NULL DEFAULT 1
                );
                CREATE INDEX inventory_identity ON inventories(identity, created_at);
                CREATE TABLE inventory_objects (
                    id INTEGER PRIMARY KEY, inventory_id TEXT NOT NULL REFERENCES inventories(id),
                    schema_name TEXT NOT NULL, name TEXT NOT NULL, kind TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
                CREATE INDEX object_lookup ON inventory_objects
                    (inventory_id, schema_name, kind, name);
                CREATE TABLE mappings (
                    id TEXT PRIMARY KEY, source_identity TEXT NOT NULL,
                    target_identity TEXT NOT NULL,
                    source_inventory TEXT NOT NULL REFERENCES inventories(id),
                    target_inventory TEXT NOT NULL REFERENCES inventories(id),
                    created_at TEXT NOT NULL, payload TEXT NOT NULL
                );
                CREATE INDEX mapping_pair ON mappings(source_identity, target_identity, created_at);
                CREATE TABLE runs (
                    id TEXT PRIMARY KEY, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    status TEXT NOT NULL, configuration TEXT NOT NULL, report TEXT, error TEXT
                );
                CREATE TABLE schema_migrations (
                    version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
                INSERT INTO schema_migrations VALUES (1, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
                PRAGMA user_version=1;
                COMMIT;
            """)
            self._upgrade_results(connection)

    @staticmethod
    def _upgrade_results(connection):
        connection.executescript("""
            BEGIN IMMEDIATE;
            CREATE TABLE run_results (
                run_id TEXT NOT NULL REFERENCES runs(id), result_key TEXT NOT NULL,
                stage TEXT NOT NULL, recorded_at TEXT NOT NULL, payload TEXT NOT NULL,
                PRIMARY KEY (run_id, result_key)
            );
            CREATE TABLE run_stages (
                run_id TEXT NOT NULL REFERENCES runs(id), stage TEXT NOT NULL,
                position INTEGER NOT NULL, status TEXT NOT NULL,
                updated_at TEXT NOT NULL, PRIMARY KEY (run_id, stage)
            );
            INSERT INTO schema_migrations VALUES (2, strftime('%Y-%m-%dT%H:%M:%fZ','now'));
            PRAGMA user_version=2;
            COMMIT;
        """)

    def plan_stages(self, run_id, stages):
        with self.connect() as connection:
            connection.executemany(
                "INSERT INTO run_stages VALUES (?,?,?,?,?)",
                [(run_id, stage, position, "pending", now())
                 for position, stage in enumerate(stages)],
            )

    def record_stage(self, run_id, stage, status):
        with self.connect() as connection:
            connection.execute(
                "UPDATE run_stages SET status=?,updated_at=? WHERE run_id=? AND stage=?",
                (status, now(), run_id, stage),
            )

    def record_result(self, run_id, stage, result):
        key = json.dumps([result.check_id, result.category.value,
                          result.source_object, result.target_object])
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO run_results VALUES (?,?,?,?,?) "
                "ON CONFLICT(run_id,result_key) DO UPDATE SET "
                "stage=excluded.stage,recorded_at=excluded.recorded_at,payload=excluded.payload",
                (run_id, key, stage, now(), result.model_dump_json()),
            )

    def run_state(self, run_id):
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id,status,error FROM runs WHERE id=?", (run_id,),
            ).fetchone()
        return dict(row) if row is not None else None

    def partial_report(self, run_id, limit=100, offset=0):
        with self.connect() as connection:
            connection.execute("BEGIN")
            run = connection.execute(
                "SELECT id,status,error FROM runs WHERE id=?", (run_id,),
            ).fetchone()
            if run is None:
                return None
            stages = [dict(row) for row in connection.execute(
                "SELECT stage,status,updated_at FROM run_stages WHERE run_id=? ORDER BY position",
                (run_id,),
            )]
            counts = {row[0]: row[1] for row in connection.execute(
                "SELECT json_extract(payload,'$.status'),count(*) FROM run_results "
                "WHERE run_id=? GROUP BY json_extract(payload,'$.status')", (run_id,),
            )}
            rows = connection.execute(
                "SELECT payload FROM run_results WHERE run_id=? "
                "ORDER BY result_key LIMIT ? OFFSET ?",
                (run_id, limit, offset),
            ).fetchall()
        complete = bool(stages) and run["status"] == "completed" and all(
            stage["status"] == "completed" for stage in stages
        )
        return {"run_id": run_id, "state": run["status"], "error": run["error"],
                "coverage_complete": complete, "stages": stages, "counts": counts,
                "total": sum(counts.values()), "offset": offset, "limit": limit,
                "results": [json.loads(row["payload"]) for row in rows]}

    def backup(self) -> Path:
        destination = self.path.parent / "backups" / f"catalog-{uuid.uuid4().hex}.sqlite3"
        destination.parent.mkdir(exist_ok=True)
        with self.connect() as source:
            target = sqlite3.connect(destination)
            try:
                source.backup(target)
            finally:
                target.close()
        return destination

    def connections(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM connections WHERE deleted=0 ORDER BY updated_at DESC"
            ).fetchall()
        return [{**json.loads(row["metadata"]), "id": row["id"], "label": row["label"]}
                for row in rows]

    def save_connection(self, values: dict) -> dict:
        metadata = connection_metadata(values)
        timestamp = now()
        identifier = values.get("id") or uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO connections VALUES (?,?,?,?,?,?,0) ON CONFLICT(id) DO UPDATE SET "
                "label=excluded.label, identity=excluded.identity, metadata=excluded.metadata, "
                "updated_at=excluded.updated_at, deleted=0",
                (identifier, values["label"], identity(metadata), json.dumps(metadata),
                 timestamp, timestamp),
            )
        return {**metadata, "id": identifier, "label": values["label"]}

    def delete_connection(self, identifier: str):
        with self.connect() as connection:
            connection.execute("UPDATE connections SET deleted=1 WHERE id=?", (identifier,))

    def save_inventory(self, connection_config, model: DatabaseModel, *, collected=None) -> str:
        identifier = uuid.uuid4().hex
        metadata = model.model_dump(mode="json", exclude={"schemas"})
        metadata["connection"] = connection_metadata(connection_config)
        metadata["collected"] = collected if collected is not None else ["columns", "structural"]
        objects = []
        for schema in model.schemas:
            objects.append((identifier, schema.name, schema.name, "schema", json.dumps(
                schema.model_dump(mode="json", exclude={"tables", "views", "routines", "sequences"})
            )))
            for kind, collection in (("table", schema.tables), ("view", schema.views),
                                     ("routine", schema.routines), ("sequence", schema.sequences)):
                objects.extend((identifier, schema.name, item.name, kind, item.model_dump_json())
                               for item in collection)
        with self.connect() as connection:
            connection.execute(
                "INSERT INTO inventories VALUES (?,?,?,?,1,1)",
                (identifier, identity(connection_config), now(), json.dumps(metadata)),
            )
            connection.executemany(
                "INSERT INTO inventory_objects(inventory_id,schema_name,name,kind,payload) "
                "VALUES (?,?,?,?,?)", objects,
            )
        return identifier

    def inventories(self, connection_config) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT id,created_at,complete,metadata FROM inventories WHERE identity=? "
                "ORDER BY created_at DESC", (identity(connection_config),),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            collected = json.loads(item.pop("metadata")).get("collected", [])
            item["collected"] = collected
            item["metadata_complete"] = {"columns", "structural"}.issubset(collected)
            result.append(item)
        return result

    def inventory_collected(self, identifier: str, connection_config) -> list[str]:
        """Metadata categories saved in an inventory (``[]`` = schema/table names only)."""
        with self.connect() as connection:
            row = connection.execute(
                "SELECT metadata FROM inventories WHERE id=? AND identity=? AND complete=1",
                (identifier, identity(connection_config)),
            ).fetchone()
        if row is None:
            raise ValueError("Inventory missing, incomplete, incompatible, or connection changed")
        return json.loads(row["metadata"]).get("collected", [])

    def load_inventory(
        self, identifier: str, connection_config, schemas=None, included=None, excluded=None,
        require_complete: bool = False,
    ) -> DatabaseModel:
        with self.connect() as connection:
            snapshot = connection.execute(
                "SELECT * FROM inventories WHERE id=? AND identity=? AND complete=1",
                (identifier, identity(connection_config)),
            ).fetchone()
            if snapshot is None or snapshot["format_version"] != 1:
                raise ValueError(
                    "Inventory missing, incomplete, incompatible, or connection changed")
            query = "SELECT * FROM inventory_objects WHERE inventory_id=?"
            parameters = [identifier]
            if schemas is not None:
                query += " AND schema_name IN (" + ",".join("?" for _ in schemas) + ")"
                parameters.extend(schemas)
            if included:
                conditions = []
                for name in included:
                    conditions.append("(casefold(schema_name)=? OR "
                                      "casefold(schema_name || '.' || name)=?)")
                    parameters.extend([name.strip().casefold()] * 2)
                query += " AND (" + " OR ".join(conditions) + ")"
            for name in excluded or []:
                query += " AND casefold(schema_name)<>? AND " \
                         "casefold(schema_name || '.' || name)<>?"
                parameters.extend([name.strip().casefold()] * 2)
            rows = connection.execute(query, parameters).fetchall()
        metadata = json.loads(snapshot["metadata"])
        if require_complete and not {"columns", "structural"}.issubset(
            metadata.get("collected", [])
        ):
            raise ValueError(
                "Inventory holds schema/table names only; run validation in full mode "
                "or Discover & match again to collect the required metadata"
            )
        metadata.pop("connection", None)
        metadata.pop("collected", None)
        grouped = {}
        for row in rows:
            schema = grouped.setdefault(row["schema_name"], {"name": row["schema_name"]})
            payload = json.loads(row["payload"])
            if row["kind"] == "schema":
                schema.update(payload)
            else:
                schema.setdefault(row["kind"] + "s", []).append(payload)
        return DatabaseModel.model_validate({**metadata, "schemas": list(grouped.values())})

    def save_mapping(self, source, target, source_inventory, target_inventory, payload) -> str:
        self.load_inventory(source_inventory, source, [])
        self.load_inventory(target_inventory, target, [])
        identifier = uuid.uuid4().hex
        with self.connect() as connection:
            connection.execute("INSERT INTO mappings VALUES (?,?,?,?,?,?,?)", (
                identifier, identity(source), identity(target), source_inventory,
                target_inventory, now(), json.dumps(payload),
            ))
        return identifier

    def mappings(self, source, target) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM mappings WHERE source_identity=? AND target_identity=? "
                "ORDER BY created_at DESC", (identity(source), identity(target)),
            ).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]

    def start_run(self, identifier, config, status="running"):
        payload = config.model_dump(mode="json")
        payload["source"] = connection_metadata(config.source)
        payload["target"] = connection_metadata(config.target)
        with self.connect() as connection:
            connection.execute("INSERT INTO runs VALUES (?,?,?,?,?,NULL,NULL)",
                               (identifier, now(), now(), status, json.dumps(payload)))

    def activate_run(self, identifier):
        with self.connect() as connection:
            cursor = connection.execute(
                "UPDATE runs SET status='running',updated_at=? WHERE id=? AND status='queued'",
                (now(), identifier),
            )
            if cursor.rowcount != 1:
                raise ValueError("Run is no longer queued")

    def finish_run(self, identifier, report=None, error=None):
        with self.connect() as connection:
            if report is None:
                connection.execute(
                    "UPDATE run_stages SET status='error',updated_at=? WHERE run_id=? "
                    "AND status='running' AND EXISTS "
                    "(SELECT 1 FROM runs WHERE id=? AND status='running')",
                    (now(), identifier, identifier),
                )
            connection.execute(
                "UPDATE runs SET updated_at=?,status=?,report=COALESCE(?,report),error=? "
                "WHERE id=? AND status!='completed'",
                (now(), "completed" if report else "failed",
                 report.model_dump_json() if report else None, error, identifier),
            )

    def update_run_config(self, identifier, config):
        payload = config.model_dump(mode="json")
        payload["source"] = connection_metadata(config.source)
        payload["target"] = connection_metadata(config.target)
        with self.connect() as connection:
            connection.execute("UPDATE runs SET configuration=?,updated_at=? WHERE id=?",
                               (json.dumps(payload), now(), identifier))

    def interrupt_run(self, identifier):
        with self.connect() as connection:
            connection.execute(
                "UPDATE run_stages SET status='interrupted',updated_at=? "
                "WHERE run_id=? AND status='running'", (now(), identifier),
            )
            connection.execute(
                "UPDATE runs SET status='interrupted',updated_at=?,error='application_stopped' "
                "WHERE id=? AND status IN ('queued','running')", (now(), identifier),
            )

    def recover_runs(self):
        with self.connect() as connection:
            connection.execute(
                "UPDATE run_stages SET status='interrupted',updated_at=? "
                "WHERE status='running' AND run_id IN (SELECT id FROM runs WHERE status='running')",
                (now(),),
            )
            connection.execute(
                "UPDATE runs SET status='interrupted',updated_at=?,"
                "error='application_restarted' WHERE status IN ('running','queued')", (now(),),
            )

    def runs(self) -> list[dict]:
        with self.connect() as connection:
            rows = connection.execute("SELECT * FROM runs ORDER BY created_at DESC").fetchall()
        return [{**dict(row), "configuration": json.loads(row["configuration"]),
                 "report": json.loads(row["report"]) if row["report"] else None} for row in rows]

    def runs_for(self, source, target) -> list[dict]:
        return [run for run in self.runs()
                if identity(run["configuration"].get("source", {})) == identity(source)
                and identity(run["configuration"].get("target", {})) == identity(target)]

    def import_report(self, report):
        payload = report.model_dump_json()
        with self.connect() as connection:
            existing = connection.execute("SELECT report FROM runs WHERE id=?",
                                          (report.migration_id,)).fetchone()
            if existing:
                if existing["report"] != payload:
                    raise FileExistsError(f"Conflicting catalog run: {report.migration_id}")
                return
            connection.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,NULL)", (
                report.migration_id, report.generated_at.isoformat(), now(), "imported",
                json.dumps({"legacy": True}), payload,
            ))