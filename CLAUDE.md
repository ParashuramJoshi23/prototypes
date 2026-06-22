# CLAUDE.md

Guidance for Claude Code when working in this repository.

## What this repo is

A personal **monorepo of independent prototypes** built to understand backend/distributed-systems concepts (caching, sharding, load balancing, leader election, polling, async pipelines, etc.). Each top-level directory is a **self-contained project** with its own dependencies, run setup, and (usually) `README.md`. There is no shared build, no cross-project imports, and no root-level package manifest — treat each directory as its own small repo.

When asked to work on something, first identify which project directory it belongs to and operate inside that directory.

## Layout

Each project dir is one of two stacks:

- **Python** (most projects) — FastAPI or Flask, with `requirements.txt` and usually a `docker-compose.yml` + `Dockerfile`. Code typically lives under `app/`, tests under `tests/`.
- **Go** — has a `go.mod` (module name is per-project, e.g. `module remote-locks`). Go versions vary per project (1.21–1.25); use the version pinned in that project's `go.mod`.

Notable projects: `auth-service` (JWT/SSO/OAuth, Alembic migrations), `g2-reviews` (FastAPI + Redis write-through cache + asyncpg, latency-focused), `hashtag-service` (FastAPI + Postgres + Kafka + presigned S3), `video-processing-kafka` (FastAPI + Celery + Kafka async pipeline), `gateway-vs-lb` (Go, gateway vs load-balancer comparison w/ Prometheus), `polling` (Flask short vs long polling), `sse-logs`/`shorthand-chat` (SSE/websocket demos), plus several Go load-balancer / locking experiments.

`Homelab.md` is a **standalone design doc** (k3s cluster planning), not tied to any code project. `README.md` at root is intentionally one line.

## Running / testing a project

There is no universal command — check the individual project first (its `README.md`, then `docker-compose.yml` / `Makefile`). Common patterns:

- **Python + compose:** `cd <project> && docker compose up --build`
- **Python standalone:** `cd <project> && pip install -r requirements.txt && python app.py` (or `uvicorn app.main:app --reload` for FastAPI under `app/`)
- **Python tests:** `cd <project> && pytest`
- **Go:** `cd <project> && go run .` / `go build ./...` / `go test ./...` (some have a `Makefile` — prefer it)

Backing stores in compose files are typically `postgres:16-alpine` and `redis:7-alpine`; Kafka and LocalStack appear in the event-driven projects.

## Conventions

- **Stay scoped to one project.** Don't refactor across project boundaries or introduce a shared library — keeping prototypes independent is the point.
- **Match the local project's style** — each was built at a different time and may differ in structure; follow the conventions of the file you're editing rather than imposing a repo-wide standard.
- Each project pins its own deps in `requirements.txt` / `go.mod`; add deps there, not globally.
- `.gitignore` already excludes `__pycache__/`, `*.pyc`, `.venv/`, `*.sqlite`, and built Go binaries — don't commit those.

## Git

- Default/main branch is `master`.
- Work merges in via PRs; feature branches follow `claude/<topic>` naming (see history). Branch before committing per the harness rules.
