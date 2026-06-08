#!/usr/bin/env python3
"""
monitor.py – Watch pg_stat_user_tables in real time to observe dead tuple
             accumulation and autovacuum activity.

Usage:
    python3 monitor.py [--table TABLE] [--interval SECONDS]

Tuning autovacuum per-table (run in psql while this script is active):

    -- Make autovacuum very aggressive (triggers at ~1 % dead):
    ALTER TABLE test_table
        SET (autovacuum_vacuum_scale_factor = 0.01,
             autovacuum_vacuum_threshold    = 10);

    -- Restore global defaults:
    ALTER TABLE test_table
        RESET (autovacuum_vacuum_scale_factor,
               autovacuum_vacuum_threshold);
"""
import argparse
import os
import time
from datetime import datetime, timezone

import psycopg2

DSN = "host=localhost port=5432 dbname=autovacuum_demo user=demo password=demo123"

SEPARATOR = "─" * 62


def connect() -> psycopg2.extensions.connection:
    for attempt in range(12):
        try:
            conn = psycopg2.connect(DSN)
            conn.autocommit = True
            return conn
        except psycopg2.OperationalError as e:
            print(f"  Waiting for Postgres… (attempt {attempt + 1}/12) — {e}")
            time.sleep(3)
    raise RuntimeError("Could not connect")


# ── Data fetching ──────────────────────────────────────────────────────────────

def fetch_global_settings(cur) -> dict:
    cur.execute("""
        SELECT name, setting, unit
          FROM pg_settings
         WHERE name IN (
             'autovacuum_vacuum_scale_factor',
             'autovacuum_vacuum_threshold',
             'autovacuum_naptime',
             'autovacuum_analyze_scale_factor',
             'autovacuum_analyze_threshold'
         )
         ORDER BY name
    """)
    return {row[0]: {"value": row[1], "unit": row[2] or ""} for row in cur.fetchall()}


def fetch_table_relopts(cur, table: str) -> dict:
    """Return per-table storage parameters set via ALTER TABLE … SET (…)."""
    cur.execute(
        "SELECT reloptions FROM pg_class WHERE relname = %s AND relkind = 'r'",
        (table,),
    )
    row = cur.fetchone()
    if not row or not row[0]:
        return {}
    opts = {}
    for item in row[0]:
        k, _, v = item.partition("=")
        opts[k] = v
    return opts


def fetch_table_stats(cur, table: str) -> tuple | None:
    cur.execute("""
        SELECT n_live_tup,
               n_dead_tup,
               last_vacuum,
               last_autovacuum,
               last_analyze,
               last_autoanalyze,
               vacuum_count,
               autovacuum_count,
               n_mod_since_analyze
          FROM pg_stat_user_tables
         WHERE relname = %s
    """, (table,))
    return cur.fetchone()


def fetch_active_autovacuum(cur, table: str) -> list[str]:
    """Return phase strings for any autovacuum worker currently on this table."""
    cur.execute("""
        SELECT phase
          FROM pg_stat_progress_vacuum
         WHERE relid = (SELECT oid FROM pg_class WHERE relname = %s)
    """, (table,))
    return [row[0] for row in cur.fetchall()]


# ── Helpers ────────────────────────────────────────────────────────────────────

def fmt_ago(ts) -> str:
    if ts is None:
        return "never"
    now = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    secs = int((now - ts).total_seconds())
    if secs < 0:
        return "just now"
    if secs < 60:
        return f"{secs}s ago"
    if secs < 3600:
        return f"{secs // 60}m {secs % 60}s ago"
    return f"{secs // 3600}h {(secs % 3600) // 60}m ago"


def vacuum_trigger_threshold(settings: dict, relopts: dict, n_live: int) -> tuple[float, float, int]:
    """Return (threshold_value, effective_scale_factor, effective_base_threshold)."""
    scale = float(
        relopts.get("autovacuum_vacuum_scale_factor",
                    settings["autovacuum_vacuum_scale_factor"]["value"])
    )
    base = int(
        relopts.get("autovacuum_vacuum_threshold",
                    settings["autovacuum_vacuum_threshold"]["value"])
    )
    return base + scale * n_live, scale, base


def progress_bar(pct: float, width: int = 44) -> str:
    filled = min(int(pct / 100 * width), width)
    empty = width - filled
    if pct >= 100:
        return "█" * width + "  ← VACUUM DUE"
    if pct >= 75:
        return "▓" * filled + "░" * empty
    return "▒" * filled + "░" * empty


# ── Rendering ──────────────────────────────────────────────────────────────────

def render(stats, settings: dict, relopts: dict, table: str, active_vac: list[str]) -> None:
    os.system("clear")
    now = datetime.now().strftime("%H:%M:%S")

    print(f"╔══ Postgres Autovacuum Monitor {'═' * 29}╗")
    print(f"  Table: {table:<20}  Refreshed: {now}")
    print(f"╚{'═' * 60}╝")

    # ── Global settings ────────────────────────────────────────────────────────
    print("\n  Global autovacuum settings (docker-compose / postgresql.conf):\n")
    for name, meta in sorted(settings.items()):
        label = name.replace("autovacuum_", "")
        override_key = name  # relopts uses full name
        override = ""
        if override_key in relopts:
            override = f"  ← overridden: {relopts[override_key]}"
        print(f"    {name:<42} {meta['value']:>8} {meta['unit']}{override}")

    # ── Per-table overrides ────────────────────────────────────────────────────
    print(f"\n  Per-table overrides (ALTER TABLE … SET):")
    if relopts:
        for k, v in relopts.items():
            print(f"    {k} = {v}")
    else:
        print("    (none — inheriting global defaults)")

    if stats is None:
        print(f"\n  '{table}' not found yet — run hammer.py first.")
        return

    (n_live, n_dead, last_vac, last_autovac,
     last_analyze, last_autoanalyze, vac_count, autovac_count,
     n_mod_since_analyze) = stats

    trigger_at, eff_scale, eff_base = vacuum_trigger_threshold(settings, relopts, n_live)
    pct = (n_dead / trigger_at * 100) if trigger_at > 0 else 0.0

    # ── Live / dead stats ──────────────────────────────────────────────────────
    print(f"\n  {SEPARATOR}")
    print(f"  {'Metric':<35} {'Value':>20}")
    print(f"  {SEPARATOR}")
    print(f"  {'n_live_tup':<35} {n_live:>20,}")
    print(f"  {'n_dead_tup':<35} {n_dead:>20,}  ← watch this")
    print(f"  {'n_mod_since_analyze':<35} {n_mod_since_analyze:>20,}")
    print(f"  {SEPARATOR}")

    # ── Vacuum trigger ─────────────────────────────────────────────────────────
    formula = f"= {eff_base} + {eff_scale} × {n_live:,}"
    print(f"  {'Vacuum trigger threshold':<35} {int(trigger_at):>20,}  {formula}")
    print(f"  {'Dead-tuple pressure':<35} {pct:>19.1f}%")
    print()
    print(f"  [{progress_bar(pct)}] {pct:.0f}%")
    print()

    # ── Autovacuum timing ──────────────────────────────────────────────────────
    print(f"  {SEPARATOR}")
    print(f"  {'last_autovacuum':<35} {fmt_ago(last_autovac):>20}")
    print(f"  {'last_vacuum (manual)':<35} {fmt_ago(last_vac):>20}")
    print(f"  {'last_autoanalyze':<35} {fmt_ago(last_autoanalyze):>20}")
    print(f"  {'autovacuum_count (total)':<35} {autovac_count:>20,}")
    print(f"  {SEPARATOR}")

    # ── In-progress worker ─────────────────────────────────────────────────────
    if active_vac:
        print(f"\n  *** AUTOVACUUM WORKER ACTIVE: {', '.join(active_vac)} ***")
    elif pct >= 100:
        print(f"\n  *** Dead-tuple threshold reached — autovacuum should start soon ***")

    # ── Tuning cheat-sheet ─────────────────────────────────────────────────────
    print(f"\n  {SEPARATOR}")
    print("  Tuning (run in psql to experiment live):\n")
    print(f"    -- Aggressive: trigger at ~1% dead tuples")
    print(f"    ALTER TABLE {table}")
    print(f"        SET (autovacuum_vacuum_scale_factor = 0.01,")
    print(f"             autovacuum_vacuum_threshold    = 10);")
    print()
    print(f"    -- Lazy: trigger only after 50% dead tuples")
    print(f"    ALTER TABLE {table}")
    print(f"        SET (autovacuum_vacuum_scale_factor = 0.5,")
    print(f"             autovacuum_vacuum_threshold    = 500);")
    print()
    print(f"    -- Reset to global defaults")
    print(f"    ALTER TABLE {table}")
    print(f"        RESET (autovacuum_vacuum_scale_factor,")
    print(f"               autovacuum_vacuum_threshold);")
    print(f"  {SEPARATOR}")


# ── Main ───────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Monitor autovacuum activity on a Postgres table",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--table", default="test_table", help="Table to watch (default: test_table)")
    parser.add_argument("--interval", type=int, default=3, help="Refresh interval in seconds (default: 3)")
    args = parser.parse_args()

    print("Connecting to Postgres …")
    conn = connect()
    cur = conn.cursor()
    print(f"Connected. Monitoring '{args.table}' every {args.interval}s — Ctrl+C to stop.")
    time.sleep(1)

    try:
        while True:
            settings = fetch_global_settings(cur)
            relopts = fetch_table_relopts(cur, args.table)
            stats = fetch_table_stats(cur, args.table)
            active_vac = fetch_active_autovacuum(cur, args.table)
            render(stats, settings, relopts, args.table, active_vac)
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped.")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
