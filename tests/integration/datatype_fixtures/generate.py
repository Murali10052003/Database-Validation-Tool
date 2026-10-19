"""Generate standalone setup SQL, without opening any database connection."""

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from tests.integration.datatype_fixtures.cases import CASES


def postgres_schema(schema: str, path: str, scenario: str) -> str:
    statements = [f"CREATE SCHEMA {schema};", f"SET LOCAL search_path TO {schema};",
                  "CREATE TYPE dt_state AS ENUM ('new', 'done');",
                  "CREATE DOMAIN dt_positive AS NUMERIC(8,2) CHECK (VALUE >= 0);"]
    for case in CASES:
        if path not in case.paths:
            continue
        statements.append(f"CREATE TABLE {case.table} (row_id INTEGER PRIMARY KEY, "
                          f"value {case.postgres_type});")
        values = [*case.values, "NULL"]
        if scenario == "bad":
            if case.aggregate_preserved:
                values[0], values[2] = values[2], values[0]
            else:
                values[2] = case.changed
        if scenario == "good" and case.table in {"dt_json", "dt_jsonb"}:
            values[0] = "'{\"b\":[true,null" + (
                ",\"text\"" if case.table == "dt_json" else "") + "],\"a\":1}'"
        statements.append(f"INSERT INTO {case.table} (row_id,value) VALUES " + ",".join(
            f"({index},{value})" for index, value in enumerate(values, 1)) + ";")
        if scenario == "shape" and case.support != "unsupported":
            statements.append(f"ALTER TABLE {case.table} ALTER COLUMN value TYPE VARCHAR(20000) "
                              "USING value::text;")
    return "\n".join(statements)


def oracle_source() -> str:
    statements = [
        "WHENEVER SQLERROR EXIT SQL.SQLCODE ROLLBACK",
        "SET DEFINE OFF",
        "BEGIN",
        "  IF SYS_CONTEXT('USERENV', 'SESSION_USER') <> 'MV_DT_SOURCE' THEN",
        "    RAISE_APPLICATION_ERROR(-20001, 'Connect as the dedicated MV_DT_SOURCE user');",
        "  END IF;",
        "END;",
        "/",
        "ALTER SESSION SET TIME_ZONE = '+00:00';",
    ]
    for case in CASES:
        if case.oracle_type is None:
            continue
        statements.append(f"CREATE TABLE {case.table} (row_id NUMBER(9,0) PRIMARY KEY, "
                          f"value {case.oracle_type});")
        for index, value in enumerate([*(case.oracle_values or case.values), "NULL"], 1):
            statements.append(f"INSERT INTO {case.table} (row_id,value) VALUES ({index},{value});")
    return "\n".join([*statements, "COMMIT;", ""])


def artifacts() -> dict[str, str]:
    files = {"oracle-source.sql": oracle_source()}
    files["postgres-source.sql"] = "BEGIN;\n" + postgres_schema(
        "mv_dt_source", "postgres_postgres", "source") + "\nCOMMIT;\n"
    for path in ("oracle_postgres", "postgres_postgres"):
        files[f"{path}-targets.sql"] = "BEGIN;\n" + "\n".join(
            postgres_schema(f"mv_dt_{scenario}", path, scenario)
            for scenario in ("good", "bad", "shape")) + "\nCOMMIT;\n"
    files["cases.json"] = json.dumps([
        asdict(case) | {"paths": case.paths} for case in CASES], indent=2) + "\n"
    return files


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    files = artifacts()
    if any((args.output / name).exists() for name in files):
        parser.error("Output files already exist; choose a fresh directory (no files overwritten)")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, content in files.items():
        (args.output / name).write_text(content, encoding="utf-8")
    print(f"Generated {len(files)} files in {args.output}; no database connections made")


if __name__ == "__main__":
    main()