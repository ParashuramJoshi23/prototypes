"""Database access. Every function takes an open autocommit connection."""

import os

import click
import psycopg
from psycopg.rows import dict_row

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
  id           BIGSERIAL PRIMARY KEY,
  command      TEXT        NOT NULL,
  status       TEXT        NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued','running','succeeded','failed')),
  exit_code    INT,
  output       TEXT,
  worker_id    TEXT,
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at   TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs (status, created_at);
"""


def connect() -> psycopg.Connection:
    url = os.environ.get("JQ_DATABASE_URL")
    if not url:
        raise click.ClickException("JQ_DATABASE_URL is not set")
    return psycopg.connect(url, autocommit=True, row_factory=dict_row)


def init(conn: psycopg.Connection) -> None:
    conn.execute(SCHEMA)


def submit(conn: psycopg.Connection, command: str) -> int:
    row = conn.execute(
        "INSERT INTO jobs (command) VALUES (%s) RETURNING id", (command,)
    ).fetchone()
    return row["id"]


def claim_next(conn: psycopg.Connection, worker_id: str) -> dict | None:
    """Pick the oldest queued job and mark it running.

    Deliberately naive: the SELECT and the UPDATE are separate statements,
    so two workers can pick the same job. Step 2 is about finding and fixing that.
    """
    job = conn.execute(
        "SELECT id, command FROM jobs WHERE status = 'queued'"
        " ORDER BY created_at LIMIT 1"
    ).fetchone()
    if job is None:
        return None
    conn.execute(
        "UPDATE jobs SET status = 'running', worker_id = %s, started_at = now()"
        " WHERE id = %s",
        (worker_id, job["id"]),
    )
    return job


def finish(conn: psycopg.Connection, job_id: int, exit_code: int, output: str) -> None:
    conn.execute(
        "UPDATE jobs SET status = %s, exit_code = %s, output = %s, finished_at = now()"
        " WHERE id = %s",
        ("succeeded" if exit_code == 0 else "failed", exit_code, output, job_id),
    )


def list_jobs(conn: psycopg.Connection, status: str | None) -> list[dict]:
    return conn.execute(
        "SELECT id, status, worker_id, exit_code,"
        "  COALESCE(finished_at, now()) - started_at AS duration"
        " FROM jobs WHERE %(s)s::text IS NULL OR status = %(s)s"
        " ORDER BY id",
        {"s": status},
    ).fetchall()


def get_job(conn: psycopg.Connection, job_id: int) -> dict | None:
    return conn.execute("SELECT * FROM jobs WHERE id = %s", (job_id,)).fetchone()
