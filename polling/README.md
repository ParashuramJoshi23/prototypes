# Polling Demo — Short vs Long Polling

Demonstrates both polling patterns using a mock EC2 instance creation workflow.

## What's inside

| File | Purpose |
|---|---|
| `app.py` | Flask API with short-poll and long-poll endpoints |
| `demo.py` | Side-by-side comparison with timing output |
| `tests/test_polling.py` | pytest test suite |
| `requirements.txt` | Python dependencies |

## The mock EC2 workflow

When a job is created it transitions through four states on a background thread:

```
pending  ──(2s)──▶  initializing  ──(3s)──▶  running  ──(4s)──▶  complete
```

Total time to completion: ~9 seconds.

## API

### Create a job
```
POST /jobs
→ 201  { job_id, status, instance_id, created_at, updated_at }
```

### Short poll
```
GET /jobs/<job_id>/status
→ 200  { … current status … }   (always responds immediately)
```

### Long poll
```
GET /jobs/<job_id>/status/long?current_status=<s>&timeout=<t>
→ 200  { … updated status … }
```

The server **holds the connection open** until the status differs from
`current_status` (or `timeout` seconds elapse).  The client re-polls
immediately after each response.

## Short polling vs Long polling

| | Short polling | Long polling |
|---|---|---|
| How it works | Client sleeps N seconds, then asks again | Client sends its known status; server blocks until it changes |
| HTTP requests | One per poll interval (many wasted) | One per state transition (minimal) |
| Latency to detect change | Up to N seconds | Near-zero (woken by `notify_all`) |
| Server load | Higher (many idle requests) | Lower (connections sleep in the OS scheduler) |
| Implementation complexity | Trivial | Slightly more (Condition variable per job) |

## Setup

```bash
cd polling
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Run the demo

```bash
python demo.py
```

Sample output:

```
────────────────────────────────────────────────────────────
Creating EC2 job for SHORT POLLING demo …
  job_id=a1b2c3d4  instance=i-0f1e2d3c4b5a67890
  Polling every 1.0s …

  [short-poll] req #  1    0.0s  status → pending
  [short-poll] req #  3    2.1s  status → initializing
  [short-poll] req #  6    5.1s  status → running
  [short-poll] req # 10    9.1s  status → complete

────────────────────────────────────────────────────────────
Creating EC2 job for LONG POLLING demo …
  job_id=e5f6a7b8  instance=i-9876543210abcdef0
  Holding connection (server pushes on change) …

  [long-poll]  req #  1    2.0s  status → initializing
  [long-poll]  req #  2    5.0s  status → running
  [long-poll]  req #  3    9.0s  status → complete

────────────────────────────────────────────────────────────
                               SHORT       LONG
────────────────────────────────────────────────────────────
Total HTTP requests                10          3
Time to detect completion (s)    9.10       9.03
────────────────────────────────────────────────────────────
  Long polling saved 7 unnecessary HTTP requests.
────────────────────────────────────────────────────────────
```

Both strategies detect completion in roughly the same wall-clock time, but
long polling does it with a fraction of the HTTP requests.

## Run the tests

```bash
pytest tests/ -v
```
