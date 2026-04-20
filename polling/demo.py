"""
Demo: Short polling vs Long polling for mock EC2 creation.

Starts the Flask server in a background thread, creates two jobs,
then races both polling strategies side-by-side and prints a comparison.
"""

import sys
import threading
import time

import requests

# ─── Start embedded server ─────────────────────────────────────────────────

BASE = "http://127.0.0.1:5050"
POLL_INTERVAL = 1.0   # seconds between short-poll requests
LONG_TIMEOUT  = 30.0  # max server hold time per long-poll request


def _start_server() -> None:
    from app import app
    # Slightly longer delays so the difference is more visible
    app.config["STATE_DELAYS"] = [2, 3, 4]   # total ~9 s to reach "complete"
    app.run(debug=False, threaded=True, port=5050, use_reloader=False)


server_thread = threading.Thread(target=_start_server, daemon=True)
server_thread.start()

# Give Flask a moment to bind the port
time.sleep(1.0)


# ─── Short polling ──────────────────────────────────────────────────────────

def run_short_poll(job_id: str) -> dict:
    """Poll every POLL_INTERVAL seconds until status == 'complete'."""
    requests_made = 0
    start = time.perf_counter()

    status = ""
    while status != "complete":
        resp = requests.get(f"{BASE}/jobs/{job_id}/status", timeout=5)
        resp.raise_for_status()
        data = resp.json()
        requests_made += 1
        new_status = data["status"]

        if new_status != status:
            elapsed = time.perf_counter() - start
            print(f"  [short-poll] req #{requests_made:>3}  {elapsed:5.1f}s  status → {new_status}")
            status = new_status

        if status != "complete":
            time.sleep(POLL_INTERVAL)

    elapsed = time.perf_counter() - start
    return {"requests": requests_made, "elapsed": elapsed}


# ─── Long polling ───────────────────────────────────────────────────────────

def run_long_poll(job_id: str) -> dict:
    """Long-poll: send current_status each time, server blocks until it changes."""
    requests_made = 0
    start = time.perf_counter()

    current_status = ""
    while current_status != "complete":
        url = (
            f"{BASE}/jobs/{job_id}/status/long"
            f"?current_status={current_status}&timeout={LONG_TIMEOUT}"
        )
        resp = requests.get(url, timeout=LONG_TIMEOUT + 5)
        resp.raise_for_status()
        data = resp.json()
        requests_made += 1
        new_status = data["status"]

        elapsed = time.perf_counter() - start
        print(f"  [long-poll]  req #{requests_made:>3}  {elapsed:5.1f}s  status → {new_status}")
        current_status = new_status

    elapsed = time.perf_counter() - start
    return {"requests": requests_made, "elapsed": elapsed}


# ─── Main ───────────────────────────────────────────────────────────────────

def main() -> None:
    sep = "─" * 60

    # ── Short polling ──
    print(sep)
    print("Creating EC2 job for SHORT POLLING demo …")
    r = requests.post(f"{BASE}/jobs", timeout=5)
    r.raise_for_status()
    short_job = r.json()
    print(f"  job_id={short_job['job_id']}  instance={short_job['instance_id']}")
    print(f"  Polling every {POLL_INTERVAL}s …\n")

    short_result = run_short_poll(short_job["job_id"])

    # ── Long polling ──
    print()
    print(sep)
    print("Creating EC2 job for LONG POLLING demo …")
    r = requests.post(f"{BASE}/jobs", timeout=5)
    r.raise_for_status()
    long_job = r.json()
    print(f"  job_id={long_job['job_id']}  instance={long_job['instance_id']}")
    print(f"  Holding connection (server pushes on change) …\n")

    long_result = run_long_poll(long_job["job_id"])

    # ── Comparison ──
    print()
    print(sep)
    print(f"{'':30} {'SHORT':>10} {'LONG':>10}")
    print(sep)
    print(f"{'Total HTTP requests':30} {short_result['requests']:>10d} {long_result['requests']:>10d}")
    print(f"{'Time to detect completion (s)':30} {short_result['elapsed']:>10.2f} {long_result['elapsed']:>10.2f}")
    print(sep)
    savings = short_result["requests"] - long_result["requests"]
    print(f"  Long polling saved {savings} unnecessary HTTP requests.")
    print(sep)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(0)
