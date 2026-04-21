"""
Approach 2 — SELECT ... FOR UPDATE (blocking)

Each thread opens a transaction, locks the first available row with
FOR UPDATE, updates it, and commits. Concurrent transactions that
target the same row block until the lock is released, then re-evaluate.
No double-bookings. Slower under high contention due to queuing.
"""

import threading
import time
import psycopg2

DSN        = "dbname=postgres user=parashuram"
PASSENGERS = 120


def book(passenger: str, results: list, lock: threading.Lock):
    conn = psycopg2.connect(DSN)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM seats
            WHERE booked_by IS NULL
            ORDER BY id
            LIMIT 1
            FOR UPDATE
        """)
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            return

        seat_id = row[0]
        cur.execute("UPDATE seats SET booked_by = %s WHERE id = %s", (passenger, seat_id))
        conn.commit()

        with lock:
            results.append(seat_id)
    finally:
        conn.close()


def run():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    conn.cursor().execute("UPDATE seats SET booked_by = NULL")
    conn.close()

    results, lock = [], threading.Lock()
    threads = [
        threading.Thread(target=book, args=(f"P{i:03d}", results, lock))
        for i in range(1, PASSENGERS + 1)
    ]

    print(f"Approach : 2 — FOR UPDATE (blocking)")
    print(f"Language : Python")
    print(f"Passengers: {PASSENGERS}")

    start = time.time()
    print(f"\n[START] {time.strftime('%H:%M:%S')}.{int(start % 1 * 1000):03d}")

    for t in threads: t.start()
    for t in threads: t.join()

    end = time.time()
    print(f"[END]   {time.strftime('%H:%M:%S')}.{int(end % 1 * 1000):03d}")
    duration_ms = int((end - start) * 1000)

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM seats WHERE booked_by IS NOT NULL")
    booked = cur.fetchone()[0]
    cur.execute("""
        SELECT COUNT(*) FROM (
            SELECT booked_by FROM seats WHERE booked_by IS NOT NULL
            GROUP BY booked_by HAVING COUNT(*) > 1
        ) t
    """)
    double_booked = cur.fetchone()[0]
    conn.close()

    print(f"\nDuration:      {duration_ms}ms")
    print(f"Booked:        {booked} / {PASSENGERS}")
    print(f"Double-booked: {double_booked}")


if __name__ == "__main__":
    run()
