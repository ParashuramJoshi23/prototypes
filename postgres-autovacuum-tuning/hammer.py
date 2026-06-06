#!/usr/bin/env python3
"""
hammer.py – Hammer Postgres with high-volume UPDATE and DELETE operations
to deliberately accumulate dead tuples and observe autovacuum behavior.

Usage:
    python3 hammer.py [--batch-size N] [--sleep-ms N] [--initial-rows N]
"""
import argparse
import random
import time

import psycopg2

DSN = "host=localhost port=5432 dbname=autovacuum_demo user=demo password=demo123"
TABLE = "test_table"


def connect() -> psycopg2.extensions.connection:
    for attempt in range(12):
        try:
            return psycopg2.connect(DSN)
        except psycopg2.OperationalError as e:
            print(f"  Waiting for Postgres... (attempt {attempt + 1}/12) — {e}")
            time.sleep(3)
    raise RuntimeError("Could not connect to Postgres after 12 attempts")


def setup(conn, initial_rows: int) -> None:
    with conn.cursor() as cur:
        cur.execute(f"""
            CREATE TABLE IF NOT EXISTS {TABLE} (
                id         SERIAL PRIMARY KEY,
                payload    TEXT        NOT NULL,
                counter    INT         NOT NULL DEFAULT 0,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
        """)
        cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
        existing = cur.fetchone()[0]

        if existing == 0:
            print(f"Seeding {initial_rows:,} initial rows …")
            batch = [(f"payload-{i}", i % 100) for i in range(initial_rows)]
            cur.executemany(
                f"INSERT INTO {TABLE} (payload, counter) VALUES (%s, %s)",
                batch,
            )
            print("Seed complete.")
        else:
            print(f"Table already has {existing:,} rows — skipping seed.")

    conn.commit()


def hammer(conn, batch_size: int, sleep_ms: int) -> None:
    """
    Each iteration:
      1. UPDATE a random batch of rows  → each update creates one dead tuple
      2. DELETE a small fraction        → more dead tuples, shrinks live count
      3. Re-INSERT the deleted count    → keeps the table size stable
    """
    iteration = 0
    max_id = _get_max_id(conn)

    while True:
        with conn.cursor() as cur:
            # --- UPDATEs ---
            ids = [random.randint(1, max_id) for _ in range(batch_size)]
            cur.execute(
                f"""UPDATE {TABLE}
                       SET counter    = counter + 1,
                           updated_at = now()
                     WHERE id = ANY(%s)""",
                (ids,),
            )
            updated = cur.rowcount

            # --- DELETEs (20 % of batch) ---
            delete_n = max(1, batch_size // 5)
            cur.execute(
                f"""DELETE FROM {TABLE}
                     WHERE id IN (
                         SELECT id FROM {TABLE}
                         ORDER BY random()
                         LIMIT %s
                     )""",
                (delete_n,),
            )
            deleted = cur.rowcount

            # --- Re-INSERT to keep the table populated ---
            if deleted > 0:
                replenish = [
                    (f"payload-{random.randint(0, 999_999)}", random.randint(0, 100))
                    for _ in range(deleted)
                ]
                cur.executemany(
                    f"INSERT INTO {TABLE} (payload, counter) VALUES (%s, %s)",
                    replenish,
                )
                # update ceiling so new rows can be targeted
                cur.execute(f"SELECT MAX(id) FROM {TABLE}")
                max_id = cur.fetchone()[0] or max_id

        conn.commit()
        iteration += 1

        if iteration % 20 == 0:
            with conn.cursor() as cur:
                cur.execute(f"SELECT COUNT(*) FROM {TABLE}")
                live = cur.fetchone()[0]
            print(
                f"[iter {iteration:>6}]  updated={updated:>4}  deleted={deleted:>3}"
                f"  live_rows≈{live:,}"
            )

        time.sleep(sleep_ms / 1_000.0)


def _get_max_id(conn) -> int:
    with conn.cursor() as cur:
        cur.execute(f"SELECT COALESCE(MAX(id), 1) FROM {TABLE}")
        return cur.fetchone()[0]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Hammer Postgres with UPDATE/DELETE to accumulate dead tuples"
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=300,
        help="Rows per UPDATE batch (default: 300)",
    )
    parser.add_argument(
        "--sleep-ms",
        type=int,
        default=50,
        help="Sleep between iterations in milliseconds (default: 50)",
    )
    parser.add_argument(
        "--initial-rows",
        type=int,
        default=10_000,
        help="Rows to seed if the table is empty (default: 10000)",
    )
    args = parser.parse_args()

    print("Connecting to Postgres …")
    conn = connect()
    print("Connected.")
    setup(conn, args.initial_rows)

    print(
        f"\nHammering '{TABLE}' — batch={args.batch_size} rows, "
        f"sleep={args.sleep_ms} ms per iteration."
    )
    print("Run monitor.py in a second terminal to watch dead tuple accumulation.")
    print("Press Ctrl+C to stop.\n")

    try:
        hammer(conn, batch_size=args.batch_size, sleep_ms=args.sleep_ms)
    except KeyboardInterrupt:
        print("\nStopped by user.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
