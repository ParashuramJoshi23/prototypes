# Temporal E-commerce Order Workflow

A minimal [Temporal](https://temporal.io) prototype in Python that fulfills a
single e-commerce order through three steps and **automatically recovers from a
simulated transient payment failure**. The goal is to see workflow
orchestration, activities, retries, durable state persistence, and recovery
behavior in action — no external input, just a hardcoded sample order.

## What's inside

| File | Purpose |
|---|---|
| `app/workflows.py` | `OrderWorkflow` — deterministic orchestration of the three steps |
| `app/activities.py` | The three activities; `process_payment` fails once on purpose |
| `app/worker.py` | Worker that polls the task queue and runs the code |
| `app/starter.py` | Submits the hardcoded sample order, prints structured result |
| `app/shared.py` | `Order` / `OrderResult` dataclasses + task-queue name |
| `tests/test_workflow.py` | Time-skipping test asserting recovery on retry |
| `docker-compose.yml` | Temporal dev server (+ Web UI) + worker + starter |

## The order flow

```
reserve_inventory ──▶ process_payment ──▶ send_order_confirmation
                          │
              attempt 1: fail (simulated gateway timeout)
              attempt 2: succeed   ◀── Temporal retries automatically
```

### Activities

| Activity | Signature | Result |
|---|---|---|
| `reserve_inventory` | `(order_id: str)` | `{status: "reserved"}` |
| `process_payment` | `(order_id: str, amount: float)` | `{status: "paid", attempts: int}` |
| `send_order_confirmation` | `(email: str)` | `{status: "sent"}` |

### How the failure / recovery is simulated

`process_payment` reads `activity.info().attempt` (1-based, tracked durably by
Temporal across retries). On attempt 1 it raises a retryable `ApplicationError`;
the workflow's `RetryPolicy` then reschedules it, and attempt 2 succeeds. The
workflow code itself doesn't know or care that a retry happened — that's the
point of Temporal's durable execution.

## Run it

### With Docker (recommended)

```bash
cd temporal-ecommerce-workflow
docker compose up --build -d temporal worker   # start server + worker
docker compose run --rm starter                # submit the sample order
```

Then open the Temporal Web UI at <http://localhost:8233> to watch the workflow
history, including the failed first payment attempt and the successful retry.

### Locally (without Docker)

You need the [Temporal CLI](https://docs.temporal.io/cli) for the dev server:

```bash
cd temporal-ecommerce-workflow
pip install -r requirements.txt

temporal server start-dev          # terminal 1 — server + UI on :8233
python -m app.worker               # terminal 2 — worker
python -m app.starter              # terminal 3 — submit order
```

## Expected output

```json
{
  "order_id": "ORD-1001",
  "inventory_status": "reserved",
  "payment_status": "paid",
  "payment_attempts": 2,
  "confirmation_status": "sent",
  "workflow_status": "COMPLETED",
  "summary": "Order ORD-1001 fulfilled: inventory reserved, payment paid in 2 attempt(s) (payment recovered after a transient failure), confirmation sent."
}
```

`payment_attempts == 2` is the proof that Temporal retried and recovered.

## Tests

```bash
cd temporal-ecommerce-workflow
pip install -r requirements.txt
pytest
```

The test uses Temporal's **time-skipping** test environment, so the retry
backoff is fast-forwarded — it runs in milliseconds while still exercising the
real retry machinery and asserting `payment_attempts == 2`.

## Concepts this demonstrates

- **Orchestration** — the workflow sequences activities without doing I/O itself.
- **Activities** — isolated, retryable units of side-effecting work.
- **Retries** — declarative `RetryPolicy` drives automatic recovery from the
  transient payment failure; no manual retry loop in the code.
- **State persistence** — Temporal records every step in an event history
  (persisted to sqlite by the dev server here), so a crashed worker can replay
  and resume exactly where it left off.
- **Recovery** — a failed activity attempt doesn't fail the workflow; Temporal
  reschedules it transparently.
