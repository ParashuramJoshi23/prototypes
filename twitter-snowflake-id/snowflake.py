"""
Twitter Snowflake ID — Pure-Python Prototype
=============================================
Generates 64-bit, time-ordered, globally-unique IDs with zero coordination.

Bit layout (MSB → LSB):
  [0]      1 bit  — sign, always 0
  [1–41]  41 bits — epoch ms (gives ~69 years from EPOCH)
  [42–51] 10 bits — machine (5-bit datacenter_id + 5-bit worker_id)
  [52–63] 12 bits — per-ms sequence counter

This file is self-contained:
  - SnowflakeGenerator   — the core generator (thread-safe)
  - parse()              — decompose an ID back into its fields
  - demo_single()        — 10 IDs from one generator
  - demo_multithreaded() — 8 threads × 500 IDs, verifies uniqueness + order

Run:
    python snowflake.py
"""

import threading
import time
from dataclasses import dataclass

# ─────────────────────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────────────────────

# 2010-11-04T01:42:54.657Z — Twitter's original epoch
EPOCH_MS = 1288834974657

DATACENTER_ID_BITS = 5
WORKER_ID_BITS     = 5
SEQUENCE_BITS      = 12

MAX_DATACENTER_ID  = (1 << DATACENTER_ID_BITS) - 1   # 31
MAX_WORKER_ID      = (1 << WORKER_ID_BITS) - 1        # 31
MAX_SEQUENCE       = (1 << SEQUENCE_BITS) - 1         # 4095

# Bit shift positions
WORKER_SHIFT      = SEQUENCE_BITS                          # 12
DATACENTER_SHIFT  = SEQUENCE_BITS + WORKER_ID_BITS         # 17
TIMESTAMP_SHIFT   = SEQUENCE_BITS + WORKER_ID_BITS + DATACENTER_ID_BITS  # 22


# ─────────────────────────────────────────────────────────────────────────────
# Generator
# ─────────────────────────────────────────────────────────────────────────────

class SnowflakeGenerator:
    """
    Thread-safe Snowflake ID generator for a single (datacenter, worker) node.

    datacenter_id: 0–31
    worker_id:     0–31
    """

    def __init__(self, datacenter_id: int = 0, worker_id: int = 0):
        if not 0 <= datacenter_id <= MAX_DATACENTER_ID:
            raise ValueError(f"datacenter_id must be 0–{MAX_DATACENTER_ID}")
        if not 0 <= worker_id <= MAX_WORKER_ID:
            raise ValueError(f"worker_id must be 0–{MAX_WORKER_ID}")

        self.datacenter_id = datacenter_id
        self.worker_id = worker_id
        self._sequence = 0
        self._last_ms = -1
        self._lock = threading.Lock()

    def next_id(self) -> int:
        with self._lock:
            now = self._current_ms()

            if now < self._last_ms:
                # Clock moved backwards — common on VMs with NTP corrections.
                # Safe strategy: wait until we catch up rather than generating
                # IDs that could collide with previously-issued ones.
                drift = self._last_ms - now
                if drift > 5:
                    raise RuntimeError(
                        f"Clock moved back {drift} ms — refusing to generate IDs"
                    )
                while now < self._last_ms:
                    now = self._current_ms()

            if now == self._last_ms:
                self._sequence = (self._sequence + 1) & MAX_SEQUENCE
                if self._sequence == 0:
                    # Sequence exhausted in this ms: spin until the next ms.
                    now = self._wait_next_ms(self._last_ms)
            else:
                self._sequence = 0

            self._last_ms = now

            return (
                ((now - EPOCH_MS) << TIMESTAMP_SHIFT)
                | (self.datacenter_id << DATACENTER_SHIFT)
                | (self.worker_id     << WORKER_SHIFT)
                | self._sequence
            )

    # ── helpers ──────────────────────────────────────────────────────────────

    @staticmethod
    def _current_ms() -> int:
        return int(time.time() * 1000)

    @staticmethod
    def _wait_next_ms(last_ms: int) -> int:
        ms = SnowflakeGenerator._current_ms()
        while ms <= last_ms:
            ms = SnowflakeGenerator._current_ms()
        return ms


# ─────────────────────────────────────────────────────────────────────────────
# Parse / inspect
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class ParsedSnowflake:
    raw:           int
    timestamp_ms:  int          # absolute epoch ms
    datacenter_id: int
    worker_id:     int
    sequence:      int

    @property
    def timestamp_s(self) -> float:
        return self.timestamp_ms / 1000

    def __str__(self) -> str:
        import datetime
        dt = datetime.datetime.utcfromtimestamp(self.timestamp_s)
        return (
            f"ID={self.raw}\n"
            f"  timestamp  : {dt.isoformat()}Z  ({self.timestamp_ms} ms)\n"
            f"  datacenter : {self.datacenter_id}\n"
            f"  worker     : {self.worker_id}\n"
            f"  sequence   : {self.sequence}"
        )


def parse(snowflake_id: int) -> ParsedSnowflake:
    ts  = (snowflake_id >> TIMESTAMP_SHIFT) + EPOCH_MS
    dc  = (snowflake_id >> DATACENTER_SHIFT) & MAX_DATACENTER_ID
    wid = (snowflake_id >> WORKER_SHIFT)     & MAX_WORKER_ID
    seq =  snowflake_id                      & MAX_SEQUENCE
    return ParsedSnowflake(snowflake_id, ts, dc, wid, seq)


# ─────────────────────────────────────────────────────────────────────────────
# Demos
# ─────────────────────────────────────────────────────────────────────────────

def demo_single():
    print("=" * 60)
    print("DEMO 1 — Single generator, 10 IDs")
    print("=" * 60)
    gen = SnowflakeGenerator(datacenter_id=1, worker_id=3)
    ids = [gen.next_id() for _ in range(10)]
    for sid in ids:
        print(parse(sid))
        print()

    assert ids == sorted(ids), "IDs must be monotonically increasing"
    print("✓ All IDs are sorted (monotonically increasing)\n")


def demo_multithreaded(num_threads: int = 8, ids_per_thread: int = 500):
    print("=" * 60)
    print(f"DEMO 2 — {num_threads} threads × {ids_per_thread} IDs "
          f"= {num_threads * ids_per_thread} total")
    print("=" * 60)

    gen = SnowflakeGenerator(datacenter_id=0, worker_id=0)
    all_ids: list[int] = []
    lock = threading.Lock()

    def worker():
        local = [gen.next_id() for _ in range(ids_per_thread)]
        with lock:
            all_ids.extend(local)

    threads = [threading.Thread(target=worker) for _ in range(num_threads)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    total = len(all_ids)
    unique = len(set(all_ids))
    print(f"Generated : {total}")
    print(f"Unique    : {unique}")
    assert total == unique, f"Collision detected! {total - unique} duplicates"
    print("✓ Zero collisions across all threads\n")

    sorted_ids = sorted(all_ids)
    min_id, max_id = sorted_ids[0], sorted_ids[-1]
    print(f"Earliest  : {parse(min_id).timestamp_ms} ms")
    print(f"Latest    : {parse(max_id).timestamp_ms} ms")
    print()


def demo_multi_node():
    print("=" * 60)
    print("DEMO 3 — Two independent nodes, no coordination needed")
    print("=" * 60)

    node_a = SnowflakeGenerator(datacenter_id=1, worker_id=0)
    node_b = SnowflakeGenerator(datacenter_id=2, worker_id=0)

    ids_a = {node_a.next_id() for _ in range(1000)}
    ids_b = {node_b.next_id() for _ in range(1000)}
    overlap = ids_a & ids_b
    print(f"Node A IDs : 1000   Node B IDs : 1000   Overlap : {len(overlap)}")
    assert not overlap, "Cross-node collision!"
    print("✓ Zero cross-node collisions\n")


def demo_bit_layout():
    print("=" * 60)
    print("DEMO 4 — Bit layout visualizer")
    print("=" * 60)
    gen = SnowflakeGenerator(datacenter_id=3, worker_id=7)
    sid = gen.next_id()
    p   = parse(sid)

    bits = f"{sid:064b}"
    print(f"Raw ID : {sid}")
    print(f"Binary : {bits}")
    print()
    print(f"  [0]      sign       : {bits[0]}")
    print(f"  [1–41]   timestamp  : {bits[1:42]}  → {p.timestamp_ms} ms")
    print(f"  [42–46]  datacenter : {bits[42:47]}  → {p.datacenter_id}")
    print(f"  [47–51]  worker     : {bits[47:52]}  → {p.worker_id}")
    print(f"  [52–63]  sequence   : {bits[52:64]}  → {p.sequence}")
    print()


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    demo_single()
    demo_multithreaded()
    demo_multi_node()
    demo_bit_layout()
