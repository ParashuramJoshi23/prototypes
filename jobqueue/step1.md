# Job Queue — Step 1: A queue on one machine

## Goal
Submit shell commands as jobs, have one worker run them, record the result.
Only one new idea in this step: the submit -> claim -> run -> mark-done loop.
No concurrency safety, no leases, no networking concerns yet (those are steps 2-5).

## Stack
- Python 3.12+, `psycopg` (v3), `click` or `typer` for CLI
- PostgreSQL 16+ running locally on the devbox (Docker is fine)
- Single repo, `uv` for env management

## Schema
```sql
CREATE TABLE jobs (
  id           BIGSERIAL PRIMARY KEY,
  command      TEXT        NOT NULL,
  status       TEXT        NOT NULL DEFAULT 'queued'
               CHECK (status IN ('queued','running','succeeded','failed')),
  exit_code    INT,
  output       TEXT,                    -- stdout+stderr, truncated to 64 KB
  worker_id    TEXT,                    -- hostname:pid of the worker that ran it
  created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at   TIMESTAMPTZ,
  finished_at  TIMESTAMPTZ
);
CREATE INDEX jobs_status_created ON jobs (status, created_at);
```

## CLI (`jq` = job queue)
- `jq init` — create the table (idempotent)
- `jq submit "<shell command>"` — insert a job, print its id
- `jq worker` — run the worker loop (below) until Ctrl+C
- `jq ls [--status S]` — list jobs: id, status, worker_id, exit_code, duration
- `jq show <id>` — full row including output

Config via env var `JQ_DATABASE_URL`.

## Worker loop
1. Find the oldest `queued` job (`ORDER BY created_at LIMIT 1`).
2. If none: sleep 1 s, repeat.
3. Set `status='running'`, `worker_id`, `started_at=now()`.
4. Run the command with `subprocess.run(shell=True, timeout=300)`, capturing output.
5. Set `status` to `succeeded`/`failed`, `exit_code`, `output`, `finished_at`.
6. Log one line per job to stdout: `job=<id> status=<s> exit=<code> took=<ms>`.
7. On Ctrl+C: finish the current job, then exit.

Deliberately naive: step 1 has a race when two workers run at once.
Do NOT add `FOR UPDATE SKIP LOCKED` yet — step 2 exists to discover that race.

## Done when
- [ ] `jq submit` x5 (mix of `sleep 2`, `echo hi`, `false`), one `jq worker`
      -> all 5 reach a terminal status; `false` is `failed` with exit 1.
- [ ] `jq ls` and `jq show` display correct data.
- [ ] Killing the worker with Ctrl+C mid-job lets that job finish first.

## Prediction to write down before building
What happens if you start TWO workers against 50 queued jobs with this code?
Write your guess here; step 2 begins by testing it.

> My prediction: This is a naive implementation; 2 workers can run the same
> process twice and override the 1st status.
