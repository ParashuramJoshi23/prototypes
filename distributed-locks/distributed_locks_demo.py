"""
Distributed Locks Demo — Pessimistic / Optimistic / Mutex / Semaphore / Combined
=================================================================================
Run against a local PostgreSQL instance (pessimistic + optimistic only).
Mutex, semaphore, and combined demos are pure in-memory — no DB required.

Setup:
    pip install psycopg2-binary
    createdb locks_demo

Usage:
    python distributed_locks_demo.py

Knobs to turn:
    NUM_WORKERS   — threads per demo (raise to see more contention)
    LOT_CAPACITY  — spots per parking lot (lower = more queuing, fewer lost updates)
    INITIAL_STOCK — starting inventory for DB demos
"""

import threading
import time
import psycopg2

# ──────────────────────────────────────────────
# Config
# ──────────────────────────────────────────────
DB_CONFIG = {
    "dbname": "locks_demo",
    "user": "parashuram",
    "password": "",
    "host": "localhost",
    "port": 5432,
}

NUM_WORKERS   = 5      # workers per demo  ← raise to see more contention
PRODUCT_ID    = 1
INITIAL_STOCK = 100

LOTS         = ["A", "B", "C"]   # parking lots
LOT_CAPACITY = 2                 # spots per lot  ← lower to serialize; raise to expose races


# ──────────────────────────────────────────────
# DB helpers
# ──────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(**DB_CONFIG)


def setup_tables():
    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS inventory;")
    cur.execute("""
        CREATE TABLE inventory (
            product_id  INT PRIMARY KEY,
            name        TEXT NOT NULL,
            quantity    INT NOT NULL,
            version     INT NOT NULL DEFAULT 1
        );
    """)
    cur.execute(
        "INSERT INTO inventory (product_id, name, quantity, version) VALUES (%s, %s, %s, 1);",
        (PRODUCT_ID, "Widget", INITIAL_STOCK),
    )
    conn.close()
    print("✓ Table created, stock reset to", INITIAL_STOCK)


def reset_stock():
    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()
    cur.execute(
        "UPDATE inventory SET quantity = %s, version = 1 WHERE product_id = %s;",
        (INITIAL_STOCK, PRODUCT_ID),
    )
    conn.close()


def read_stock():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT quantity, version FROM inventory WHERE product_id = %s;",
        (PRODUCT_ID,),
    )
    row = cur.fetchone()
    conn.close()
    return row  # (quantity, version)


# ──────────────────────────────────────────────
# 1. PESSIMISTIC LOCKING — SELECT … FOR UPDATE
# ──────────────────────────────────────────────
# Mental model: single bathroom key.
# Every other thread blocks on FOR UPDATE until the holder commits.
# Correct always; throughput is serial (one writer at a time).
#
# Effect of NUM_WORKERS:
#   More workers → longer queue, higher total wait time, same final stock.

def pessimistic_worker(worker_id, amount, results):
    conn = get_conn()
    try:
        conn.autocommit = False
        cur = conn.cursor()
        print(f"  [Pessimistic] W{worker_id}: requesting lock...")
        t0 = time.time()

        cur.execute(
            "SELECT quantity FROM inventory WHERE product_id = %s FOR UPDATE;",
            (PRODUCT_ID,),
        )
        qty = cur.fetchone()[0]
        wait = time.time() - t0
        print(f"  [Pessimistic] W{worker_id}: lock acquired (waited {wait:.3f}s), qty={qty}")

        time.sleep(0.1)  # simulate work
        new_qty = qty - amount
        cur.execute(
            "UPDATE inventory SET quantity = %s WHERE product_id = %s;",
            (new_qty, PRODUCT_ID),
        )
        conn.commit()
        print(f"  [Pessimistic] W{worker_id}: committed qty={new_qty}, lock released")
        results.append(("success", worker_id, new_qty))
    except Exception as e:
        conn.rollback()
        print(f"  [Pessimistic] W{worker_id}: ERROR — {e}")
        results.append(("error", worker_id, str(e)))
    finally:
        conn.close()


def demo_pessimistic():
    print("\n" + "=" * 60)
    print("PESSIMISTIC LOCKING (SELECT ... FOR UPDATE)")
    print("Each worker blocks until the previous one commits.")
    print("=" * 60)
    reset_stock()

    results = []
    threads = [
        threading.Thread(target=pessimistic_worker, args=(i + 1, 10, results))
        for i in range(NUM_WORKERS)
    ]
    for t in threads: t.start()
    for t in threads: t.join()

    qty, _ = read_stock()
    expected = INITIAL_STOCK - NUM_WORKERS * 10
    print(f"\n  Final stock: {qty} (expected {expected})")
    print(f"  Correct: {'✓' if qty == expected else '✗ DATA INCONSISTENCY'}")


# ──────────────────────────────────────────────
# 2. OPTIMISTIC LOCKING — version column + CAS
# ──────────────────────────────────────────────
# Mental model: wiki edit conflict.
# Everyone reads freely; only the first writer wins each round.
# Losers retry. Correct always; cost is wasted retries under contention.
#
# Effect of NUM_WORKERS:
#   More workers → more retries per round. Retry count ≈ (N*(N-1))/2.

def optimistic_worker(worker_id, amount, results, max_retries=20):
    conn = get_conn()
    conn.autocommit = True
    cur = conn.cursor()

    for attempt in range(1, max_retries + 1):
        cur.execute(
            "SELECT quantity, version FROM inventory WHERE product_id = %s;",
            (PRODUCT_ID,),
        )
        qty, version = cur.fetchone()
        print(f"  [Optimistic]  W{worker_id}: read qty={qty}, ver={version} (attempt {attempt})")

        time.sleep(0.05)

        new_qty     = qty - amount
        new_version = version + 1
        cur.execute(
            """UPDATE inventory
               SET quantity = %s, version = %s
               WHERE product_id = %s AND version = %s;""",
            (new_qty, new_version, PRODUCT_ID, version),
        )

        if cur.rowcount == 1:
            print(f"  [Optimistic]  W{worker_id}: ✓ wrote ver={new_version}, qty={new_qty}")
            results.append(("success", worker_id, new_qty, attempt))
            conn.close()
            return
        else:
            print(f"  [Optimistic]  W{worker_id}: ✗ version conflict! Retrying...")

    print(f"  [Optimistic]  W{worker_id}: GAVE UP after {max_retries} retries")
    results.append(("gave_up", worker_id, None, max_retries))
    conn.close()


def demo_optimistic():
    print("\n" + "=" * 60)
    print("OPTIMISTIC LOCKING (version column + CAS)")
    print("All workers read freely. Only first writer wins per round.")
    print("=" * 60)
    reset_stock()

    results = []
    threads = [
        threading.Thread(target=optimistic_worker, args=(i + 1, 10, results))
        for i in range(NUM_WORKERS)
    ]
    for t in threads: t.start()
    for t in threads: t.join()

    qty, ver = read_stock()
    expected      = INITIAL_STOCK - NUM_WORKERS * 10
    total_retries = sum(r[3] - 1 for r in results if r[0] == "success")
    print(f"\n  Final stock: {qty} (expected {expected})")
    print(f"  Final version: {ver}")
    print(f"  Total retries across all workers: {total_retries}")
    print(f"  Correct: {'✓' if qty == expected else '✗ DATA INCONSISTENCY'}")


# ──────────────────────────────────────────────
# 3. MUTEX — shared in-memory counter
# ──────────────────────────────────────────────
# Mental model: bathroom key for a single shared variable.
# Without lock: threads read a stale value, overwrite each other → lost increments.
# With lock:    one thread at a time → always correct.
#
# We deliberately insert a sleep between read and write to make the race visible.
# (In real Python, the GIL can hide races on simple int +=1; the sleep exposes them.)
#
# Effect of NUM_WORKERS:
#   More workers without a lock → more lost increments.
#   With a lock it stays correct regardless.

_counter = 0


def mutex_worker_unsafe(worker_id):
    global _counter
    val = _counter          # read
    time.sleep(0.01)        # gap that lets other threads read the same stale value
    _counter = val + 1      # write (may overwrite a concurrent write)
    print(f"  [No lock]  W{worker_id}: wrote counter={_counter}")


def mutex_worker_safe(worker_id, lock):
    global _counter
    with lock:
        val = _counter
        time.sleep(0.01)    # same gap, but now serialized by the lock
        _counter = val + 1
        print(f"  [Mutex]    W{worker_id}: wrote counter={_counter}")


def demo_mutex():
    global _counter
    print("\n" + "=" * 60)
    print("MUTEX — increment a shared counter")
    print(f"Without lock: race condition.  With lock: always {NUM_WORKERS}.")
    print("=" * 60)

    # ── Without lock ──
    _counter = 0
    print(f"\n  [Without lock] {NUM_WORKERS} threads each increment counter by 1")
    threads = [
        threading.Thread(target=mutex_worker_unsafe, args=(i + 1,))
        for i in range(NUM_WORKERS)
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    lost = NUM_WORKERS - _counter
    print(f"  Final: {_counter} (expected {NUM_WORKERS})")
    print(f"  Correct: {'✓' if lost == 0 else f'✗  Lost {lost} increment(s) to race condition'}")

    # ── With lock ──
    _counter = 0
    lock = threading.Lock()
    print(f"\n  [With mutex]   {NUM_WORKERS} threads each increment counter by 1")
    threads = [
        threading.Thread(target=mutex_worker_safe, args=(i + 1, lock))
        for i in range(NUM_WORKERS)
    ]
    for t in threads: t.start()
    for t in threads: t.join()
    print(f"  Final: {_counter} (expected {NUM_WORKERS})")
    print(f"  Correct: {'✓' if _counter == NUM_WORKERS else '✗ DATA LOSS'}")


# ──────────────────────────────────────────────
# 4. SEMAPHORE — Parking Lot
# ──────────────────────────────────────────────
# Mental model: parking lot with LOT_CAPACITY spots.
# Semaphore controls how many cars fit — once full, newcomers wait outside.
# This is about capacity, NOT about protecting shared data.
#
# Effect of LOT_CAPACITY:
#   1         → serial; one car at a time, no races.
#   NUM_WORKERS → all cars enter at once; race condition on revenue counter!
#   2 (default) → middle ground; observe queuing + partial parallelism.
#
# Effect of NUM_WORKERS:
#   More workers → longer queues at each lot.

def parking_worker(worker_id, lot, semaphore, occupancy, occ_lock):
    print(f"  [Parking]  W{worker_id}: driving to Lot {lot}...")
    t0 = time.time()
    with semaphore:
        wait = time.time() - t0
        with occ_lock:
            occupancy[lot] += 1
            spot = occupancy[lot]
        print(f"  [Parking]  W{worker_id}: parked in Lot {lot} "
              f"(spot {spot}/{LOT_CAPACITY}, waited {wait:.2f}s)")
        time.sleep(0.2)  # time spent parked
        with occ_lock:
            occupancy[lot] -= 1
        print(f"  [Parking]  W{worker_id}: left Lot {lot}")


def demo_parking_lot():
    total = NUM_WORKERS * len(LOTS)
    print("\n" + "=" * 60)
    print(f"SEMAPHORE — Parking Lot  ({len(LOTS)} lots × {LOT_CAPACITY} spots, {total} cars total)")
    print("Semaphore controls occupancy per lot. No data correctness guarantee.")
    print("=" * 60)

    lot_sems  = {lot: threading.Semaphore(LOT_CAPACITY) for lot in LOTS}
    lot_locks = {lot: threading.Lock() for lot in LOTS}
    occupancy = {lot: 0 for lot in LOTS}

    # round-robin: car 1→Lot A, car 2→Lot B, car 3→Lot C, car 4→Lot A, …
    threads = []
    for i in range(total):
        lot = LOTS[i % len(LOTS)]
        threads.append(threading.Thread(
            target=parking_worker,
            args=(i + 1, lot, lot_sems[lot], occupancy, lot_locks[lot])
        ))

    for t in threads: t.start()
    for t in threads: t.join()

    print(f"\n  All {total} cars parked and left.")
    print(f"  Max concurrent per lot: {LOT_CAPACITY}  (enforced by semaphore)")
    print(f"  Raise LOT_CAPACITY → more parallelism; lower → more queuing.")


# ──────────────────────────────────────────────
# 5. COMBINED — Semaphore per lot + Mutex per lot
# ──────────────────────────────────────────────
# Semaphore: controls how many cars can be IN a lot simultaneously.
# Mutex:     protects each lot's revenue counter (read-modify-write).
#
# The semaphore limits blast radius; the mutex ensures correctness.
# Without the mutex the revenue counter races even inside the semaphore,
# because LOT_CAPACITY > 1 allows concurrent writes.
#
# Effect of LOT_CAPACITY:
#   1 → semaphore serializes everything; mutex is redundant but harmless.
#   > 1 → multiple cars update revenue concurrently; mutex is essential.

PARKING_FEE = 10


def combined_worker(worker_id, lot, semaphore, mutex, revenue):
    print(f"  [Combined] W{worker_id}: heading to Lot {lot}...")
    with semaphore:                      # wait for a parking spot
        print(f"  [Combined] W{worker_id}: entered Lot {lot}, paying ${PARKING_FEE}")
        time.sleep(0.1)                  # time spent parking/paying
        with mutex:                      # only one car updates revenue at a time
            old = revenue[lot]
            time.sleep(0.01)             # simulate read-modify-write gap
            revenue[lot] = old + PARKING_FEE
            print(f"  [Combined] W{worker_id}: Lot {lot} revenue → ${revenue[lot]}")


def demo_combined_parking():
    total            = NUM_WORKERS * len(LOTS)
    expected_per_lot = NUM_WORKERS * PARKING_FEE

    print("\n" + "=" * 60)
    print(f"COMBINED — Semaphore({LOT_CAPACITY} spots/lot) + Mutex per lot")
    print(f"Semaphore limits occupancy. Mutex guards each lot's revenue counter.")
    print("=" * 60)

    lot_sems    = {lot: threading.Semaphore(LOT_CAPACITY) for lot in LOTS}
    lot_mutexes = {lot: threading.Lock() for lot in LOTS}
    revenue     = {lot: 0 for lot in LOTS}

    threads = []
    for i in range(total):
        lot = LOTS[i % len(LOTS)]
        threads.append(threading.Thread(
            target=combined_worker,
            args=(i + 1, lot, lot_sems[lot], lot_mutexes[lot], revenue)
        ))

    for t in threads: t.start()
    for t in threads: t.join()

    print(f"\n  Revenue per lot (expected ${expected_per_lot} each):")
    all_correct = True
    for lot in LOTS:
        ok = revenue[lot] == expected_per_lot
        if not ok: all_correct = False
        print(f"    Lot {lot}: ${revenue[lot]}  {'✓' if ok else '✗'}")
    print(f"  All correct: {'✓' if all_correct else '✗ Lost revenue to race condition'}")


# ──────────────────────────────────────────────
# Run all demos
# ──────────────────────────────────────────────
if __name__ == "__main__":
    print("Setting up database...")
    setup_tables()

    demo_pessimistic()
    demo_optimistic()
    demo_mutex()
    demo_parking_lot()
    demo_combined_parking()

    print("\n" + "=" * 60)
    print("KEY TAKEAWAYS")
    print("=" * 60)
    print(f"""
  Pessimistic:  DB row lock (FOR UPDATE). Always correct; fully serial.
                ↑ NUM_WORKERS → longer queues, same stock.

  Optimistic:   Version column + CAS. Always correct; losers retry.
                ↑ NUM_WORKERS → exponentially more retries.

  Mutex:        Single lock around a shared variable.
                Without it: lost increments from concurrent read-modify-write.
                With it: correct regardless of NUM_WORKERS.

  Semaphore:    Parking lot — controls HOW MANY enter, not data safety.
                LOT_CAPACITY=1  → serial (safe but slow).
                LOT_CAPACITY>1  → parallel (fast but needs mutex for shared state).
                ↑ NUM_WORKERS   → longer queues at the gate.

  Combined:     Semaphore (capacity gate) + Mutex (data guard) per lot.
                Real pattern: semaphore limits blast radius,
                mutex ensures correctness inside the lot.

  Experiment:
    NUM_WORKERS=10, LOT_CAPACITY=5  → heavy contention; watch retries & queues.
    NUM_WORKERS=2,  LOT_CAPACITY=1  → near-serial; almost no contention.
    """)
