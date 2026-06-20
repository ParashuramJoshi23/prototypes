# AI Interviewer (LiveKit + Claude)

A realtime **voice** AI that conducts surveys. A participant joins from the browser,
talks to an AI interviewer over a live audio call, and the agent asks the survey
questions one at a time, asks brief follow-ups, and records structured answers.

The interviewer's "brain" is **Claude** (`claude-opus-4-8` by default), wired into
the **LiveKit Agents** voice pipeline:

```
 Browser mic ──▶ Deepgram (STT) ──▶ Claude (LLM) ──▶ Cartesia (TTS) ──▶ Browser speaker
                         ▲                  │
                   Silero VAD +        record_answer / complete_interview
                 turn detector            (function tools → results store)
```

## What's inside

| Path | Purpose |
|---|---|
| `app/agent.py` | The LiveKit voice agent worker — runs the interview, calls Claude, persists answers via tools |
| `app/token_server.py` | FastAPI: lists surveys, mints LiveKit join tokens, serves results + the web client |
| `app/survey.py` | Loads YAML survey definitions into typed objects |
| `app/prompts.py` | Turns a survey into the Claude system prompt (interview rules + questions) |
| `app/results.py` | Results store (Postgres via asyncpg) |
| `app/db.py` | Shared asyncpg connection pool + schema bootstrap |
| `app/config.py` | Env-driven settings (DB URL, pool sizes, model) |
| `migrations/init.sql` | `interviews` + `answers` schema |
| `docker-compose.yml` | Local Postgres for the results store |
| `surveys/*.yaml` | The surveys themselves — edit these to add your own |
| `web/index.html` | Minimal browser client (LiveKit JS SDK): pick a survey, talk, see the transcript |

## How a survey gets routed

There's one agent worker but many possible surveys. Selection happens per call:

1. The browser asks `POST /api/token` for the chosen `survey_id`.
2. The token server mints a LiveKit token with `{"survey_id": ...}` baked into the
   participant **metadata**, and returns a fresh room name.
3. The browser joins that room; LiveKit dispatches the agent worker to it.
4. The agent reads `survey_id` from the participant metadata, loads that survey,
   builds the Claude prompt, and starts interviewing.

Answers are written to Postgres (the `answers` table) as the agent calls its
`record_answer` tool, and the interview is marked complete (`interviews.completed_at`)
when it calls `complete_interview`.

## Prerequisites

- Python 3.10–3.14
- Docker (for the local Postgres results store), or any reachable Postgres
- A **LiveKit** project — free at [cloud.livekit.io](https://cloud.livekit.io) (or self-hosted)
- API keys for **Anthropic** (Claude), **Deepgram** (STT), and **Cartesia** (TTS)

## Setup

```bash
cd ai-interviewer-livekit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in the keys/URL
```

Start Postgres (the results store). The schema is applied automatically:

```bash
docker compose up -d
```

One-time: download the local model files used by Silero VAD and the turn detector:

```bash
python -m app.agent download-files
```

## Run

Two processes. In one terminal, the agent worker:

```bash
python -m app.agent dev
```

In another, the token server + web client:

```bash
uvicorn app.token_server:app --reload --port 8000
```

Then open **http://localhost:8000**, pick a survey, click **Start interview**,
allow the mic, and start talking. When you end the call (or the agent says
goodbye), your recorded responses appear in the page.

## Adding a survey

Drop a new YAML file in `surveys/`:

```yaml
id: onboarding_feedback
title: Onboarding Feedback
description: A quick voice survey about your first week.
persona: a friendly onboarding specialist named Sam
closing: Thanks — this really helps us improve onboarding.
questions:
  - id: first_impression
    text: What was your first impression when you started using the product?
    intent: Capture initial reaction.
  - id: stuck
    text: Was there any moment where you felt stuck or confused?
    intent: Find onboarding friction.
```

It shows up in the dropdown automatically (no restart of the token server needed
for the list; the agent picks it up per call).

## Inspecting results

- API: `GET /api/results` (all) or `GET /api/results/<room>` (one interview)
- SQL: `docker compose exec postgres psql -U interviewer -d interviewer -c \
  "SELECT survey_id, question_id, answer, sentiment FROM answers ORDER BY recorded_at DESC LIMIT 20;"`

The API shape (interview + nested answers) looks like:

```json
{
  "room": "interview-customer_satisfaction-1a2b3c4d",
  "survey_id": "customer_satisfaction",
  "participant": "Guest-9f8e7d",
  "started_at": "2026-06-20T04:20:00+00:00",
  "completed_at": "2026-06-20T04:24:11+00:00",
  "answers": [
    {"question_id": "overall_rating", "answer": "An 8 — fast support but checkout was clunky", "sentiment": "positive", "recorded_at": "..."}
  ]
}
```

## Notes & knobs

- **Model.** Defaults to `claude-opus-4-8`. Voice is latency-sensitive, so for
  snappier turns or lower cost you can set `INTERVIEWER_MODEL=claude-sonnet-4-6`
  (or `claude-haiku-4-5`) in `.env`.
- **Swapping providers.** STT/TTS are just plugins. Change `deepgram.STT(...)` /
  `cartesia.TTS(...)` in `app/agent.py` to any other LiveKit-supported vendor.
- **Telephony.** This prototype is browser↔agent. To take real phone calls, add a
  LiveKit SIP trunk and route inbound calls to the same agent — the interview
  logic is unchanged.
- **Database.** Results live in Postgres (`interviews` + `answers`). Point
  `DATABASE_URL` at any Postgres instance; the app applies the schema on startup,
  so a managed/hosted Postgres works without running the bundled compose file.
