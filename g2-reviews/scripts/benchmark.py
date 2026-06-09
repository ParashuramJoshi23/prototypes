"""
Latency benchmark for the G2 Reviews API (1M rows in DB).

Uses multiple independent aiohttp sessions in separate asyncio tasks
to avoid single-event-loop distortion. Reports true per-request latency
percentiles for each scenario.

Run after: uvicorn app.main:app --workers 4
"""
import asyncio
import random
import statistics
import time
from dataclasses import dataclass, field

import aiohttp

BASE = "http://localhost:8002/api/v1"

PRODUCT_IDS = [
    "c659e0f3-a052-45cd-979f-1a9d85800868",
    "b2c0550c-7121-4da2-a955-ff946cc27627",
    "21284d72-7e47-4303-a20f-be2a10750fd8",
]

WARM_REVIEW_IDS = [
    "5b4b0996-9622-44c9-9726-44f5300fbe19",
    "25fa76a2-47b9-411b-85ce-5315094048a4",
    "4b0d8b98-7b8c-46b0-a48c-c18a91b0dff7",
    "ce262331-98d1-47b0-a7dd-362d7335b58c",
    "cfcbeb7b-5591-4ea8-8044-7b303c8ec38f",
    "2606d091-f302-4367-9b46-745da22b972c",
    "98157a16-d72b-4172-a024-a310de997606",
    "3cb7aedb-336f-481c-b0a6-d0e904ec42b9",
    "319052a0-86e1-4e7b-87d2-e4f868375df3",
    "e2cb0a73-ad0f-4090-bac1-12b99d1cd206",
]


@dataclass
class Result:
    name: str
    latencies: list[float] = field(default_factory=list)
    errors: int = 0

    def pct(self, p: float) -> float:
        s = sorted(self.latencies)
        return s[max(0, min(int(len(s) * p / 100), len(s) - 1))]

    def report(self) -> str:
        if not self.latencies:
            return f"  {self.name}: no data"
        s = sorted(self.latencies)
        n = len(s)
        dur_s = sum(self.latencies) / 1000
        tput = n / dur_s if dur_s > 0 else 0
        p95 = self.pct(95)
        flag = "✓" if p95 < 5.0 else "~" if p95 < 15.0 else "✗"
        return (
            f"  {flag}  {self.name:<48}"
            f"  n={n:>5,}"
            f"  min={s[0]:>5.2f}"
            f"  p50={self.pct(50):>5.2f}"
            f"  p95={p95:>5.2f}"
            f"  p99={self.pct(99):>5.2f}"
            f"  max={s[-1]:>5.2f}"
            f"  err={self.errors}"
            f"  {tput:>6,.0f} rps"
        )


async def timed_get(session: aiohttp.ClientSession, url: str) -> float | None:
    t0 = time.perf_counter()
    try:
        async with session.get(url) as resp:
            await resp.read()
            if resp.status != 200:
                return None
            return (time.perf_counter() - t0) * 1000
    except Exception:
        return None


async def run_scenario(
    name: str,
    urls: list[str],
    concurrency: int,
) -> Result:
    result = Result(name)
    sem = asyncio.Semaphore(concurrency)
    conn = aiohttp.TCPConnector(limit=concurrency + 10, enable_cleanup_closed=True)
    timeout = aiohttp.ClientTimeout(total=5)

    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
        async def fetch(url: str):
            async with sem:
                ms = await timed_get(session, url)
                if ms is not None:
                    result.latencies.append(ms)
                else:
                    result.errors += 1

        # Warm the connection pool first (2 requests, not counted)
        for u in urls[:2]:
            await timed_get(session, u)

        await asyncio.gather(*[fetch(u) for u in urls])

    return result


async def sequential_sample(url: str, n: int = 200) -> list[float]:
    """Sequential requests — no concurrency noise, ground-truth single-request latency."""
    conn = aiohttp.TCPConnector(limit=1)
    timeout = aiohttp.ClientTimeout(total=5)
    lats = []
    async with aiohttp.ClientSession(connector=conn, timeout=timeout) as session:
        # warm
        await timed_get(session, url)
        await timed_get(session, url)
        for _ in range(n):
            ms = await timed_get(session, url)
            if ms is not None:
                lats.append(ms)
    return lats


async def main():
    print()
    print("=" * 100)
    print("  G2 Reviews API — Latency Benchmark   [1,000,000 rows, 4 workers]")
    print("=" * 100)

    pid = PRODUCT_IDS[0]
    rid = WARM_REVIEW_IDS[0]

    # ── A. Sequential (ground truth, zero queuing noise) ─────────────────────
    print("\n  [A] Sequential latency — ground truth (concurrency=1, n=200 each)\n")
    print(f"  {'Endpoint':<52}  {'min':>6}  {'p50':>6}  {'p95':>6}  {'p99':>6}  {'max':>6}  ms")
    print("  " + "-" * 96)

    for label, url in [
        ("GET /reviews/{id}            [cache HIT]", f"{BASE}/reviews/{rid}"),
        ("GET /products/{id}/stats     [MV cache HIT]", f"{BASE}/products/{pid}/stats"),
        ("GET /products/{id}/top-reviews [MV cache HIT]", f"{BASE}/products/{pid}/top-reviews"),
        ("GET /products/{id}/reviews?page=1 [cache HIT]", f"{BASE}/products/{pid}/reviews?page=1&size=20"),
        ("GET /products/{id}/reviews?page=5 [cache MISS→DB]", f"{BASE}/products/{pid}/reviews?page=5&size=20"),
    ]:
        lats = await sequential_sample(url, n=200)
        if lats:
            s = sorted(lats)
            n_l = len(s)
            p = lambda pct: s[min(int(n_l * pct / 100), n_l - 1)]
            p95 = p(95)
            flag = "✓" if p95 < 5.0 else "~"
            print(f"  {flag}  {label:<52}  {s[0]:>6.2f}  {p(50):>6.2f}  {p95:>6.2f}  {p(99):>6.2f}  {s[-1]:>6.2f}")

    # ── B. Concurrent load (per-worker capacity) ──────────────────────────────
    print("\n  [B] Concurrent load — 4 workers, matched concurrency  (all times in ms)\n")
    print(f"  {'  Scenario':<54}  {'n':>6}  {'min':>6}  {'p50':>6}  {'p95':>6}  {'p99':>6}  {'max':>6}  err   rps")
    print("  " + "-" * 112)

    scenarios = [
        ("GET /reviews/{id}  [cache HIT, c=20]",
         [f"{BASE}/reviews/{random.choice(WARM_REVIEW_IDS)}" for _ in range(2000)], 20),
        ("GET /reviews/{id}  [cache HIT, c=80]",
         [f"{BASE}/reviews/{random.choice(WARM_REVIEW_IDS)}" for _ in range(4000)], 80),
        ("GET /products/{id}/stats  [MV cache HIT, c=20]",
         [f"{BASE}/products/{random.choice(PRODUCT_IDS)}/stats" for _ in range(2000)], 20),
        ("GET /products/{id}/top-reviews  [MV cache HIT, c=20]",
         [f"{BASE}/products/{random.choice(PRODUCT_IDS)}/top-reviews" for _ in range(2000)], 20),
        ("GET /products/{id}/reviews p1  [cache HIT, c=20]",
         [f"{BASE}/products/{random.choice(PRODUCT_IDS)}/reviews?page=1&size=20" for _ in range(2000)], 20),
        ("GET /products/{id}/reviews p5  [cache MISS→DB, c=10]",
         [f"{BASE}/products/{random.choice(PRODUCT_IDS)}/reviews?page=5&size=20" for _ in range(500)], 10),
    ]

    for name, urls, conc in scenarios:
        r = await run_scenario(name, urls, concurrency=conc)
        print(r.report())

    # ── C. P95 summary ────────────────────────────────────────────────────────
    print("\n  [C] P95 < 5ms target — sequential baseline\n")
    checks = [
        ("GET /reviews/{id}            [cache HIT]",   f"{BASE}/reviews/{rid}"),
        ("GET /products/{id}/stats     [MV cache HIT]", f"{BASE}/products/{pid}/stats"),
        ("GET /products/{id}/top-reviews [MV cache HIT]", f"{BASE}/products/{pid}/top-reviews"),
        ("GET /products/{id}/reviews?p=1 [cache HIT]", f"{BASE}/products/{pid}/reviews?page=1&size=20"),
        ("GET /products/{id}/reviews?p=5 [cache MISS]", f"{BASE}/products/{pid}/reviews?page=5&size=20"),
    ]
    all_pass = True
    for label, url in checks:
        lats = await sequential_sample(url, n=200)
        s = sorted(lats)
        n_l = len(s)
        p95 = s[min(int(n_l * 95 / 100), n_l - 1)]
        p99 = s[min(int(n_l * 99 / 100), n_l - 1)]
        status = "✓ PASS" if p95 < 5.0 else "✗ FAIL"
        if p95 >= 5.0:
            all_pass = False
        print(f"    {status}  {label:<52}  P95={p95:.2f}ms  P99={p99:.2f}ms")

    print()
    print(f"  Overall: {'ALL PASS ✓' if all_pass else 'some endpoints above target'}")
    print()


if __name__ == "__main__":
    asyncio.run(main())
