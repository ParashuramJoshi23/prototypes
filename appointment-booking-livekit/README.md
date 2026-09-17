# Appointment Booking Agent (LiveKit + Claude + Google Calendar)

A realtime **voice** receptionist. A caller joins from the browser, says something
like *"can I get a slot next Tuesday afternoon?"*, and the agent checks a Google
Calendar for free times, offers a few, collects a name and email, confirms, and
creates the event. It can also look up and cancel existing bookings.

The receptionist's "brain" is **Claude** (`claude-opus-5` by default), wired into
the **LiveKit Agents** voice pipeline; the calendar is the **Google Calendar API v3**:

```
 Browser mic ──▶ Deepgram (STT) ──▶ Claude (LLM) ──▶ Cartesia (TTS) ──▶ Browser speaker
                         ▲                  │
                   Silero VAD +      get_available_slots / book_appointment /
                 turn detector       find_appointments / cancel_appointment
                                            │
                                            ▼
                                 Google Calendar (freebusy, events)
```

Analogy: Claude is the receptionist on the phone; the four function tools are the
locked appointment book. Claude decides *what* the caller wants, but it can only
read or write the calendar by asking the book, and the book double-checks every
request (valid date? still free? explicit name?) before it writes anything.

## What's inside

| Path | Purpose |
|---|---|
| `app/agent.py` | The LiveKit voice agent worker — Claude + the four calendar tools |
| `app/calendar_client.py` | Async wrapper over Google Calendar (freebusy, list, insert, delete); also a CLI smoke test |
| `app/slots.py` | Pure slot arithmetic: business hours + busy blocks → bookable start times (unit-tested) |
| `app/prompts.py` | Builds the per-call system prompt (knows today's date, hours, procedure) |
| `app/token_server.py` | FastAPI: mints LiveKit join tokens, lists upcoming bookings, serves the web client |
| `app/config.py` | Env-driven settings (auth mode, calendar id, hours, slot length, model) |
| `scripts/authorize_google.py` | One-time OAuth consent flow that writes a refreshable token |
| `tests/test_slots.py` | Tests for the slot logic |
| `web/index.html` | Minimal browser client (LiveKit JS SDK): talk, see the transcript, see what got booked |

## How a booking flows

1. Browser asks `POST /api/token`; the token server mints a LiveKit token and a fresh room name.
2. Browser joins the room; LiveKit dispatches the agent worker to it.
3. The agent builds a prompt with the current date/time and business rules and greets the caller.
4. Caller names a day → Claude resolves it to an ISO date and calls **`get_available_slots`**.
   The tool runs a Google **freebusy** query for business hours that day and grids the
   free time into `APPOINTMENT_MINUTES` slots (dropping anything sooner than `MIN_LEAD_MINUTES`).
5. Caller picks a time and gives a name (and optionally email) → Claude reads it back, waits
   for a yes, then calls **`book_appointment`**. The tool re-checks the slot (someone could
   have booked it mid-call), then `events.insert`s an event, inviting the caller if an email
   was given.
6. `find_appointments` searches upcoming events by name/email; `cancel_appointment`
   deletes by event id. Both require Claude to read the appointment back first.

Every tool returns plain text that Claude relays in speech, and every failure path
returns a sentence the prompt tells Claude to relay honestly ("the calendar is
unavailable right now") rather than improvise.

## Prerequisites

- Python 3.10+
- A **LiveKit** project — free at [cloud.livekit.io](https://cloud.livekit.io) (or self-hosted)
- API keys for **Anthropic** (Claude), **Deepgram** (STT), and **Cartesia** (TTS)
- A Google Cloud project with the **Google Calendar API** enabled

## Google Calendar setup

Pick one auth mode (`GOOGLE_AUTH_MODE` in `.env`):

**`oauth`** (default — best for a personal Gmail or your own Workspace calendar)

1. Google Cloud Console → *APIs & Services* → *Credentials* → *Create credentials* →
   *OAuth client ID* → application type **Desktop app**. Download the JSON.
2. Save it as `credentials/client_secret.json`.
3. If the OAuth consent screen is in *Testing*, add your Google account as a test user.
4. Run the consent flow once; it writes `credentials/token.json`, which refreshes itself:

   ```bash
   python scripts/authorize_google.py
   ```

**`service_account`** (headless / shared team calendar)

1. Create a service account, download its key to `credentials/service_account.json`.
2. In Google Calendar, share the target calendar with the service account's email
   with **Make changes to events**, and set `GOOGLE_CALENDAR_ID` to that calendar's id
   (*Settings → Integrate calendar*).
3. Set `CALENDAR_INVITE_ATTENDEES=false` — a service account can't add attendees
   without domain-wide delegation. The caller's details still go in the event description.

`credentials/` is git-ignored. Scopes requested are `calendar.events` + `calendar.readonly`.

## Setup

```bash
cd appointment-booking-livekit
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env      # then fill in the keys and calendar settings
```

Sanity-check the calendar connection before involving voice at all
(prints tomorrow's free slots, or a given date's):

```bash
python -m app.calendar_client
python -m app.calendar_client 2026-09-22
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

Open **http://localhost:8000**, click **Start call**, allow the mic, and ask for an
appointment. The panel under the transcript lists the calendar's next 7 days
(`GET /api/appointments`), so you can watch the event appear.

## Tests

The slot arithmetic is pure and covered by unit tests; nothing else needs a network:

```bash
pytest
```

## Tuning

All booking rules are env vars (see `.env.example`): business name, timezone, open/close
times, which weekdays, the slot grid, appointment length, minimum lead time, how far
ahead to book, and how many slots to offer at once. Voice is latency-sensitive, so
`BOOKING_MODEL=claude-sonnet-5` or `claude-haiku-4-5` are reasonable faster swaps.

## Things this prototype does *not* do

- No SIP/phone-number ingress — it's browser-to-agent. LiveKit SIP would slot in without code changes to the agent.
- No multi-calendar / multi-provider routing; one calendar per deployment.
- No persistence beyond the calendar itself. Bookings made during a call are kept in
  memory only so "actually, cancel that" works without a lookup.
