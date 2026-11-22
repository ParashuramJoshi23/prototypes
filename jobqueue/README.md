# jobqueue

A tiny Postgres-backed job queue. Currently at step 1 (see `step1.md`).

## Setup

```sh
export JQ_DATABASE_URL="postgresql://postgres:$(cat ~/.postgres16-password)@127.0.0.1:5432/jobqueue"
uv sync
uv run jq init
```

## Usage

```sh
uv run jq submit "echo hi"     # prints the job id
uv run jq worker               # runs jobs until Ctrl+C (finishes the current job first)
uv run jq ls [--status failed]
uv run jq show 1
```

Ctrl+C is a graceful stop: the running job finishes, then the worker exits.
Further Ctrl+C presses are ignored; use Ctrl+\ to force-quit (the job is then left `running`).

Note: inside an activated `.venv`, `jq` shadows the JSON tool of the same name.
