# Flight Seat Booking — Concurrent Locking Benchmark

120 passengers check in simultaneously for one flight.  
Three approaches, two languages. Same problem, different database locking strategies.

---

## The Problem

```
READ  → is seat free?   ← two threads both see "yes"
WRITE → claim seat      ← both write; one overwrites the other
```

This is a **TOCTOU** (time-of-check / time-of-use) race. The fix lives in the database query, not in application code.

---

## Approaches

### Approach 1 — No Lock (race condition)

```sql
SELECT id FROM seats WHERE booked_by IS NULL ORDER BY id LIMIT 1;
-- gap: another thread reads the same row here
UPDATE seats SET booked_by = $1 WHERE id = $2;
```

- No transaction, no lock
- Two threads see the same seat as free simultaneously
- Last writer wins silently → **double-bookings**

### Approach 2 — `FOR UPDATE` (blocking)

```sql
BEGIN;
SELECT id FROM seats WHERE booked_by IS NULL ORDER BY id LIMIT 1 FOR UPDATE;
UPDATE seats SET booked_by = $1 WHERE id = $2;
COMMIT;
```

- `FOR UPDATE` locks the row at the database level until `COMMIT`
- A second transaction targeting the same row **blocks and waits**
- After the first commits, it re-evaluates: seat is taken → moves to next seat
- Correct, but transactions queue up under high contention → slower

### Approach 3 — `FOR UPDATE SKIP LOCKED` (non-blocking)

```sql
BEGIN;
SELECT id FROM seats WHERE booked_by IS NULL ORDER BY id LIMIT 1 FOR UPDATE SKIP LOCKED;
UPDATE seats SET booked_by = $1 WHERE id = $2;
COMMIT;
```

- `SKIP LOCKED` skips rows already locked by another transaction instead of waiting
- Each thread/goroutine immediately gets a **different unlocked row** — no queuing
- Highest throughput
- If all rows happen to be locked at once, the worker finds nothing and gives up (would retry in production)

---

## Setup

```bash
# Create the seats table (run once)
psql -U parashuram -d postgres -f setup.sql
```

---

## Run Individually

```bash
# Approach 1
cd approach1/python && .venv/bin/python3 main.py
cd approach1/go    && go run .

# Approach 2
cd approach2/python && .venv/bin/python3 main.py
cd approach2/go    && go run .

# Approach 3
cd approach3/python && .venv/bin/python3 main.py
cd approach3/go    && go run .
```

---

## Benchmark (all 6 at once)

```bash
bash benchmark.sh
```

Example output:

```
┌────────────────────────────┬──────────┬────────────┬─────────┬────────┐
│ Approach                   │ Duration │ Booked/120 │ Doubles │ Failed │
├────────────────────────────┼──────────┼────────────┼─────────┼────────┤
│ No Lock       (Python)     │   210ms  │  120/120   │   31    │      0 │
│ No Lock       (Go)         │    80ms  │  120/120   │   28    │      0 │
│ FOR UPDATE    (Python)     │   340ms  │  120/120   │    0    │      0 │
│ FOR UPDATE    (Go)         │   120ms  │  120/120   │    0    │      0 │
│ SKIP LOCKED   (Python)     │   180ms  │  118/120   │    0    │      2 │
│ SKIP LOCKED   (Go)         │    60ms  │  119/120   │    0    │      1 │
└────────────────────────────┴──────────┴────────────┴─────────┴────────┘
```

---

## Key Observations

| | No Lock | FOR UPDATE | SKIP LOCKED |
|---|---|---|---|
| Double-bookings | Yes | No | No |
| Blocking | No | Yes | No |
| Throughput | High* | Low (queued) | High |
| All seats filled | No** | Yes | Near-yes |

\* Fast but wrong — seats get double-booked  
\*\* Many seats never touched because threads pile on the same few rows

**Go is consistently faster than Python** because goroutines are scheduled by the Go runtime (M:N model, ~2KB stack) while Python uses OS threads (~8MB stack). Both are correct — goroutines just scale more efficiently.
