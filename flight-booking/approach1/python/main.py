"""
Approach 1 — No Lock (race condition)

SELECT then UPDATE with no transaction or lock.
A 5ms sleep widens the window between read and write so multiple
threads see the same seat as free and overwrite each other.
"""

import threading
import time
import psycopg2

DSN        = "dbname=postgres user=parashuram"
PASSENGERS = 120


def book(passenger: str, claims: dict, lock: threading.Lock):
    conn = psycopg2.connect(DSN)
    try:
        cur = conn.cursor()

        cur.execute("""
            SELECT id FROM seats
            WHERE booked_by IS NULL
            ORDER BY id
            LIMIT 1
        """)
        row = cur.fetchone()
        if row is None:
            return

        seat_id = row[0]
        time.sleep(0.005)  # widen race window

        cur.execute("UPDATE seats SET booked_by = %s WHERE id = %s", (passenger, seat_id))
        conn.commit()

        # track in memory — DB only keeps last writer, so we record all claimants
        with lock:
            claims.setdefault(seat_id, []).append(passenger)
    finally:
        conn.close()


def run():
    conn = psycopg2.connect(DSN)
    conn.autocommit = True
    conn.cursor().execute("UPDATE seats SET booked_by = NULL")
    conn.close()

    claims, lock = {}, threading.Lock()
    threads = [
        threading.Thread(target=book, args=(f"P{i:03d}", claims, lock))
        for i in range(1, PASSENGERS + 1)
    ]

    print(f"Approach : 1 — No Lock")
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
    conn.close()

    # double-booked = seats where multiple threads both "claimed" it before any committed
    double_booked = sum(1 for claimants in claims.values() if len(claimants) > 1)

    print(f"\nDuration:      {duration_ms}ms")
    print(f"Booked:        {booked} / {PASSENGERS}")
    print(f"Double-booked: {double_booked}")


if __name__ == "__main__":
    run()
