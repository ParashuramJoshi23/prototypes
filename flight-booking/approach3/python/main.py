"""
Approach 3 — SELECT ... FOR UPDATE SKIP LOCKED (non-blocking)

Like FOR UPDATE but SKIP LOCKED skips rows already held by another
transaction instead of waiting. Each thread immediately gets a
different unlocked row — no queuing, maximum throughput.
If all rows are locked at the moment of the SELECT, the thread finds
nothing and gives up (would retry in a real system).
"""

import threading
import time
import psycopg2

DSN        = "dbname=postgres user=parashuram"
PASSENGERS = 120


def book(passenger: str, results: list, failed: list, lock: threading.Lock):
    conn = psycopg2.connect(DSN)
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT id FROM seats
            WHERE booked_by IS NULL
            ORDER BY id
            LIMIT 1
            FOR UPDATE SKIP LOCKED
        """)
        row = cur.fetchone()
        if row is None:
            conn.rollback()
            with lock:
                failed.append(passenger)
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

    results, failed, lock = [], [], threading.Lock()
    threads = [
        threading.Thread(target=book, args=(f"P{i:03d}", results, failed, lock))
        for i in range(1, PASSENGERS + 1)
    ]

    print(f"Approach : 3 — FOR UPDATE SKIP LOCKED (non-blocking)")
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
    print(f"Failed:        {len(failed)}")


if __name__ == "__main__":
    run()
