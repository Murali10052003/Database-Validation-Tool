"""Command-line interface for the migration validation platform.

Commands:
    test-connection CONFIG      Check source and target connectivity.
    discover CONFIG             Discover and summarise a database's structure.
    validate CONFIG             Run a full validation and write a JSON report.
    report --migration-id ID    Print the summary of a previously written report.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, TextColumn, TimeElapsedColumn
from rich.table import Table

from app.core.config import MigrationConfig, get_settings
from app.core.enums import ValidationProfile, ValidationStatus
from app.core.exceptions import MigrationValidatorError
from app.core.logging import configure_logging
from app.reporting.report_builder import ValidationReport
from app.services.discovery_service import DiscoveryService
from app.services.migration_service import MigrationService
from app.services.report_service import ReportService

app = typer.Typer(
    add_completion=False,
    help="Validate database migrations from a source database into an Azure target.",
)
console = Console()

_STATUS_STYLE = {
    ValidationStatus.PASS: "green",
    ValidationStatus.FAIL: "red",
    ValidationStatus.WARNING: "yellow",
    ValidationStatus.SKIPPED: "dim",
    ValidationStatus.NOT_SUPPORTED: "dim",
    ValidationStatus.ERROR: "bright_red",
}


def _load_config(config: Path) -> MigrationConfig:
    try:
        return MigrationConfig.from_yaml(config)
    except MigrationValidatorError as exc:
        console.print(f"[red]Configuration error:[/red] {exc}")
        raise typer.Exit(code=2) from exc


@app.callback()
def _main(log_level: str = typer.Option(None, "--log-level", help="Override log level.")) -> None:
    settings = get_settings()
    configure_logging(log_level or settings.log_level)


@app.command("test-connection")
def test_connection(config: Path = typer.Argument(..., help="Migration config YAML.")) -> None:
    """Check that both the source and target databases are reachable."""
    cfg = _load_config(config)
    service = MigrationService()
    source, target = asyncio.run(service.test_connections(cfg))

    for side, result in (("SOURCE", source), ("TARGET", target)):
        if result.success:
            version = result.version or "unknown version"
            console.print(f"[green]OK[/green]   {side}: connected ({version})")
        else:
            console.print(f"[red]FAIL[/red] {side}: {result.error or 'connection failed'}")

    if not (source.success and target.success):
        raise typer.Exit(code=1)


@app.command("discover")
def discover(
    config: Path = typer.Argument(..., help="Migration config YAML."),
    side: str = typer.Option("source", "--side", help="'source' or 'target'."),
) -> None:
    """Discover and summarise the structure of the source or target database."""
    cfg = _load_config(config)
    conn = cfg.source if side.lower() == "source" else cfg.target
    schema_filter = (
        list(cfg.mapping.schemas.keys())
        if side.lower() == "source"
        else list(cfg.mapping.schemas.values())
    ) or None

    model = asyncio.run(DiscoveryService().discover(conn, schema_filter, include_columns=True))

    console.print(
        f"[bold]{side.upper()}[/bold]: {model.database_type.value} ({model.version or 'n/a'})"
    )
    table = Table("Schema", "Tables", "Columns", box=None)
    for schema in model.schemas:
        columns = sum(len(t.columns) for t in schema.tables)
        table.add_row(schema.name, str(len(schema.tables)), str(columns))
    console.print(table)


@app.command("validate")
def validate(
    config: Path = typer.Argument(..., help="Migration config YAML."),
    profile: str = typer.Option(None, "--profile", help="quick | standard | full."),
) -> None:
    """Run validation and write a JSON report."""
    cfg = _load_config(config)
    selected_profile = _parse_profile(profile) if profile else None
    service = MigrationService()

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("validating", total=1)

        def on_progress(stage: str, step: int, total: int) -> None:
            progress.update(task, total=total, completed=step, description=stage)

        run = asyncio.run(
            service.run_validation(cfg, profile=selected_profile, progress=on_progress)
        )

    assert run.report is not None
    _print_report_summary(run.report)
    console.print(f"\nReport written to: [cyan]{run.report_path}[/cyan]")
    if run.report.overall_status in (ValidationStatus.FAIL, ValidationStatus.ERROR):
        raise typer.Exit(code=1)


@app.command("migrate-storage")
def migrate_storage_command(
    destination: Path = typer.Option(
        ..., "--destination", help="Host data folder (reports/ and logs/)."),
    source_reports: Path = typer.Option(Path("reports"), "--source-reports"),
    legacy_db: Path | None = typer.Option(
        None, "--legacy-db", help="Optional old SQLite log database."),
    source_logs: Path | None = typer.Option(
        None, "--source-logs", help="Optional existing file-backed log directory."),
) -> None:
    """Copy existing history without deleting originals; stop old writers first."""
    from app.services.storage_migration import migrate_storage

    try:
        counts = migrate_storage(legacy_db=legacy_db, source_reports=source_reports,
                                 destination=destination, source_logs=source_logs)
    except (OSError, ValueError) as exc:
        console.print(str(exc), markup=False)
        raise typer.Exit(code=2) from exc
    console.print(counts)


@app.command("report")
def report(migration_id: str = typer.Option(..., "--migration-id", help="Run id.")) -> None:
    """Print the summary of a previously written report."""
    service = ReportService()
    path = service.report_path(migration_id)
    if not path.is_file():
        console.print(f"[red]No report found for migration id '{migration_id}'[/red] ({path})")
        raise typer.Exit(code=2)
    _print_report_summary(service.load(migration_id))
    console.print(f"\nReport path: [cyan]{path}[/cyan]")


def _parse_profile(value: str) -> ValidationProfile:
    try:
        return ValidationProfile(value.lower())
    except ValueError as exc:
        raise typer.BadParameter(f"Unknown profile '{value}'.") from exc


def _print_report_summary(report: ValidationReport) -> None:
    s = report.summary
    console.print(f"\n[bold]{report.migration_name}[/bold]  (profile: {report.profile.value})")
    grid = Table(box=None)
    grid.add_column(justify="right")
    grid.add_column()
    grid.add_row("[green]PASS[/green]", str(s.passed))
    grid.add_row("[red]FAIL[/red]", str(s.failed))
    grid.add_row("[yellow]WARNING[/yellow]", str(s.warning))
    grid.add_row("[dim]SKIPPED[/dim]", str(s.skipped))
    grid.add_row("[dim]NOT SUPPORTED[/dim]", str(s.not_supported))
    grid.add_row("[bright_red]ERROR[/bright_red]", str(s.error))
    console.print(grid)

    style = _STATUS_STYLE.get(report.overall_status, "white")
    console.print(f"Overall result: [{style}]{report.overall_status.value.upper()}[/{style}]")

    failures = [
        r
        for r in report.results
        if r.status in (ValidationStatus.FAIL, ValidationStatus.ERROR)
    ]
    if failures:
        console.print("\n[bold]Issues:[/bold]")
        for r in failures[:50]:
            target = r.source_object or r.check_id
            detail = r.message or r.error or ""
            style = _STATUS_STYLE.get(r.status, "white")
            console.print(f"  [{style}]{r.status.value.upper()}[/{style}] {target}: {detail}")
        if len(failures) > 50:
            console.print(f"  ... and {len(failures) - 50} more (see JSON report)")


if __name__ == "__main__":  # pragma: no cover
    app()
