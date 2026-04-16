"""
ProxySQL-style Read/Write Splitting Demo
=========================================
Infrastructure:
    MySQL master  :3310  — handles writes
    MySQL replica :3311  — handles reads  (read-only=ON, replicates from master)
    MySQL Router  :6033  → master   (write endpoint)
                  :6034  → replica  (read  endpoint)

ProxyRouter (this file) implements the same logic ProxySQL runs internally:
    • Hostgroups     — HG 10 = writer, HG 20 = reader
    • Query rules    — regex match in rule_id order; first match wins
    • Least connections — within a hostgroup pick the backend with fewest
                          active connections (Weighted Least Connections)

Setup:
    ./setup.sh          # starts master, replica, MySQL Router
    python3 proxysql_demo.py
"""

import re
import time
import threading
import pymysql
import pymysql.cursors
from dataclasses import dataclass, field
from typing import Optional

# ─────────────────────────────────────────
# Hostgroup + Backend definitions
# ─────────────────────────────────────────

@dataclass
class Backend:
    host: str
    port: int
    label: str
    hostgroup: int
    weight: int = 1
    # live connection tracking
    active_connections: int = field(default=0, repr=False)
    total_queries: int      = field(default=0, repr=False)
    _lock: threading.Lock   = field(default_factory=threading.Lock, repr=False)

    def acquire(self):
        with self._lock:
            self.active_connections += 1
            self.total_queries      += 1

    def release(self):
        with self._lock:
            self.active_connections = max(0, self.active_connections - 1)

    def score(self) -> float:
        """Weighted Least Connections score — lower is better."""
        return self.active_connections / self.weight


@dataclass
class QueryRule:
    rule_id: int
    pattern: str
    destination_hostgroup: int
    comment: str
    _compiled: re.Pattern = field(init=False, repr=False)

    def __post_init__(self):
        self._compiled = re.compile(self.pattern, re.IGNORECASE)

    def matches(self, sql: str) -> bool:
        return bool(self._compiled.match(sql.strip()))


# ─────────────────────────────────────────
# ProxyRouter — the ProxySQL logic in Python
# ─────────────────────────────────────────

class ProxyRouter:
    """
    Mimics ProxySQL's core routing engine:
      1. Apply query rules (first match wins)  →  pick hostgroup
      2. Within hostgroup, pick backend by Weighted Least Connections
      3. Open a real MySQL connection to that backend
    """

    def __init__(self, backends: list[Backend], rules: list[QueryRule],
                 default_hostgroup: int, user: str, password: str, db: str):
        self.backends          = backends
        self.rules             = sorted(rules, key=lambda r: r.rule_id)
        self.default_hostgroup = default_hostgroup
        self._creds            = dict(user=user, password=password, database=db,
                                      cursorclass=pymysql.cursors.DictCursor)

    # ── Routing ────────────────────────────────────────────────

    def route(self, sql: str) -> tuple[int, str]:
        """Returns (hostgroup_id, matched_rule_comment)."""
        for rule in self.rules:
            if rule.matches(sql):
                return rule.destination_hostgroup, rule.comment
        return self.default_hostgroup, "default → HG10 master (write)"

    def _pick_backend(self, hostgroup: int) -> Backend:
        """Weighted Least Connections within a hostgroup."""
        candidates = [b for b in self.backends if b.hostgroup == hostgroup]
        if not candidates:
            raise RuntimeError(f"No backends in hostgroup {hostgroup}")
        return min(candidates, key=lambda b: b.score())

    # ── Connection context manager ─────────────────────────────

    class _Conn:
        """Wraps a pymysql connection; tracks active_connections on the backend."""
        def __init__(self, backend: Backend, conn):
            self._backend = backend
            self._conn    = conn

        def execute(self, sql, params=None):
            with self._conn.cursor() as cur:
                cur.execute(sql, params)
                try:
                    return cur.fetchall()
                except Exception:
                    return []

        def close(self):
            self._conn.close()
            self._backend.release()

        def __enter__(self):
            return self

        def __exit__(self, *_):
            self.close()

    def connect(self, sql: str) -> tuple["ProxyRouter._Conn", int, str]:
        """
        Route sql, pick the least-connected backend, return an open connection.
        Returns (conn, hostgroup_id, rule_comment).
        """
        hg, comment = self.route(sql)
        backend     = self._pick_backend(hg)
        backend.acquire()
        try:
            conn = pymysql.connect(
                host=backend.host, port=backend.port,
                autocommit=True,
                **self._creds,
            )
        except Exception:
            backend.release()
            raise
        return self._Conn(backend, conn), hg, comment

    # ── Stats ──────────────────────────────────────────────────

    def print_stats(self):
        print(f"\n  {'Hostgroup':<28} {'Backend':<22} {'Active':<8} {'Total queries'}")
        print(f"  {'-'*28} {'-'*22} {'-'*8} {'-'*14}")
        for b in self.backends:
            hg_label = f"HG {b.hostgroup} {b.label}"
            backend  = f"{b.host}:{b.port}"
            print(f"  {hg_label:<28} {backend:<22} {b.active_connections:<8} {b.total_queries}")


# ─────────────────────────────────────────
# Build the router (mirrors proxysql.cnf)
# ─────────────────────────────────────────

def build_router() -> ProxyRouter:
    backends = [
        Backend(host="127.0.0.1", port=6033, label="writer (master)",    hostgroup=10),
        Backend(host="127.0.0.1", port=6034, label="reader (replica-1)", hostgroup=20),
        Backend(host="127.0.0.1", port=6035, label="reader (replica-2)", hostgroup=20),
    ]
    rules = [
        QueryRule(1, r"^SELECT\b.+\bFOR\s+UPDATE\b", 10,
                  "rule 1: SELECT FOR UPDATE → HG 10 master (needs row lock)"),
        QueryRule(2, r"^SELECT\b",                    20,
                  "rule 2: SELECT → HG 20 replica"),
    ]
    return ProxyRouter(
        backends=backends, rules=rules, default_hostgroup=10,
        user="app_user", password="app_password", db="demo",
    )


# ─────────────────────────────────────────
# Demo sections
# ─────────────────────────────────────────

def section(title):
    print(f"\n{'=' * 60}\n{title}\n{'=' * 60}")


def demo_writes(router: ProxyRouter):
    section("WRITES — INSERT routed to master (HG 10)")
    users = [(1,"Ravi","Bangalore"),(2,"Priya","Delhi"),(3,"Amit","Mumbai"),
             (4,"Sara","Chennai"),(5,"Kiran","Hyderabad")]

    sql = "TRUNCATE TABLE users"
    with router.connect(sql)[0] as c:
        c.execute(sql)

    for uid, name, city in users:
        sql = "INSERT INTO users (id, name, city) VALUES (%s, %s, %s)"
        conn, hg, comment = router.connect(sql)
        with conn:
            conn.execute(sql, (uid, name, city))
        print(f"  INSERT user {uid} ({name:<6}) → {comment}")


def demo_reads(router: ProxyRouter):
    section("READS — SELECT routed to replica (HG 20)")
    time.sleep(1)  # let replication catch up

    sql = "SELECT * FROM users ORDER BY id"
    conn, hg, comment = router.connect(sql)
    with conn:
        rows = conn.execute(sql)

    for r in rows:
        print(f"  user_id={r['id']} {r['name']:<8} {r['city']:<12}  ← {comment}")


def demo_select_for_update(router: ProxyRouter):
    section("SELECT FOR UPDATE — stays on master (HG 10)")

    sql = "SELECT * FROM users WHERE id = 1 FOR UPDATE"
    conn, hg, comment = router.connect(sql)
    # Need autocommit=OFF for FOR UPDATE; open a raw connection for this one
    raw = pymysql.connect(host="127.0.0.1", port=6033, user="app_user",
                          password="app_password", database="demo",
                          cursorclass=pymysql.cursors.DictCursor, autocommit=False)
    try:
        with raw.cursor() as cur:
            cur.execute(sql)
            row = cur.fetchone()
        print(f"  Locked row: user_id={row['id']}, name={row['name']}")
        print(f"  {comment}")
    finally:
        raw.rollback()
        raw.close()


def demo_least_connections(router: ProxyRouter):
    section("LEAST CONNECTIONS — reads spread across replica-1 and replica-2")
    readers = [b for b in router.backends if b.hostgroup == 20]
    print(f"  HG 20 has {len(readers)} replicas. Opening 6 concurrent connections.")
    print("  ProxyRouter picks the backend with the lowest active_connections score.\n")

    sql = "SELECT COUNT(*) AS cnt FROM users"
    conns = []
    for i in range(6):
        conn, hg, comment = router.connect(sql)
        rows = conn.execute(sql)
        scores = "  ".join(
            f"{b.label}: active={b.active_connections}" for b in readers
        )
        print(f"  Connection {i+1}: COUNT={rows[0]['cnt']}  [{scores}]  → {comment}")
        conns.append(conn)
    for c in conns:
        c.close()


def demo_stats(router: ProxyRouter):
    section("ROUTING STATS — total queries per hostgroup")
    router.print_stats()


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────

if __name__ == "__main__":
    router = build_router()

    print("ProxyRouter connecting through MySQL Router")
    print("  Write endpoint → 127.0.0.1:6033 → master  :3310")
    print("  Read  endpoint → 127.0.0.1:6034 → replica :3311")

    demo_writes(router)
    demo_reads(router)
    demo_select_for_update(router)
    demo_least_connections(router)
    demo_stats(router)

    print("\n" + "=" * 60)
    print("KEY TAKEAWAYS")
    print("=" * 60)
    print("""
  MySQL Router — transparent TCP proxy, two endpoints:
    :6033 → master  (all writes land here)
    :6034 → replica (all reads land here)

  ProxyRouter — the routing brain (mirrors ProxySQL internals):
    Query rules  evaluated in rule_id order; first match wins.
      rule 1  SELECT … FOR UPDATE → HG 10 master   (needs row lock)
      rule 2  SELECT              → HG 20 replica  (read-only)
      default everything else     → HG 10 master   (writes)

    Weighted Least Connections — within a hostgroup, pick the
    backend with the lowest (active_connections / weight) score.
    Add replicas to HG 20 with higher weight to bias traffic toward them.

  To add a second replica:
    1. Start mysql-replica-2 on port 3312, server-id=3
    2. Add Backend(host="127.0.0.1", port=6035, hostgroup=20) to the router
    3. Add a [routing:reads2] block in mysqlrouter.conf pointing to :3312
    → ProxyRouter will immediately start balancing reads across both replicas.
    """)
