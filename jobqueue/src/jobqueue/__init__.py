"""jq: a tiny Postgres-backed job queue (step 1)."""

import click

from jobqueue import db
from jobqueue.worker import run_worker

STATUSES = ["queued", "running", "succeeded", "failed"]


@click.group()
def main() -> None:
    """Job queue CLI. Reads the database URL from JQ_DATABASE_URL."""


@main.command()
def init() -> None:
    """Create the jobs table (safe to run repeatedly)."""
    with db.connect() as conn:
        db.init(conn)
    click.echo("ok")


@main.command()
@click.argument("command")
def submit(command: str) -> None:
    """Queue a shell command and print its job id."""
    with db.connect() as conn:
        click.echo(db.submit(conn, command))


@main.command()
def worker() -> None:
    """Run jobs until Ctrl+C."""
    run_worker()


def _fmt_duration(d) -> str:
    return "-" if d is None else f"{d.total_seconds():.2f}s"


@main.command(name="ls")
@click.option("--status", type=click.Choice(STATUSES))
def ls_(status: str | None) -> None:
    """List jobs."""
    with db.connect() as conn:
        rows = db.list_jobs(conn, status)
    click.echo(f"{'ID':>5}  {'STATUS':<10} {'WORKER':<28} {'EXIT':>4}  DURATION")
    for r in rows:
        exit_code = "-" if r["exit_code"] is None else r["exit_code"]
        click.echo(
            f"{r['id']:>5}  {r['status']:<10} {r['worker_id'] or '-':<28} "
            f"{exit_code:>4}  {_fmt_duration(r['duration'])}"
        )


@main.command()
@click.argument("job_id", type=int)
def show(job_id: int) -> None:
    """Show one job, including its output."""
    with db.connect() as conn:
        job = db.get_job(conn, job_id)
    if job is None:
        raise click.ClickException(f"no job {job_id}")
    output = job.pop("output")
    for key, value in job.items():
        click.echo(f"{key:<12} {'-' if value is None else value}")
    click.echo("output:")
    click.echo(output if output else "(none)")
