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


def book(passenger: str, failed: list, lock: threading.Lock):
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
        cur.execute("UPDATE seats SET booked_by = %s WHERE id = %s", (passenger, row[0]))
        conn.commit()
    finally:
        conn.close()


def run():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    conn.cursor().execute("UPDATE seats SET booked_by = NULL")
    conn.close()

    failed, lock = [], threading.Lock()
    threads = [
        threading.Thread(target=book, args=(f"P{i:03d}", failed, lock))
        for i in range(1, PASSENGERS + 1)
    ]

    print("Approach : 3 — FOR UPDATE SKIP LOCKED (non-blocking)")
    print("Language : Python")
    print(f"Passengers: {PASSENGERS}")

    start = time.time()
    print(f"\n[START] {time.strftime('%H:%M:%S')}.{int(start % 1 * 1000):03d}")

    for t in threads: t.start()
    for t in threads: t.join()

    end = time.time()
    print(f"[END]   {time.strftime('%H:%M:%S')}.{int(end % 1 * 1000):03d}")

    conn = psycopg2.connect(DSN)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM seats WHERE booked_by IS NOT NULL")
    booked = cur.fetchone()[0]
    conn.close()

    print(f"\nDuration: {int((end - start) * 1000)}ms")
    print(f"Booked:   {booked} / {PASSENGERS}")
    print(f"Failed:   {len(failed)}")


if __name__ == "__main__":
    run()
