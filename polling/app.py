"""
Flask app demonstrating short polling vs long polling for mock EC2 instance creation.

Short polling: client repeatedly calls GET /jobs/<id>/status every N seconds.
              Server always responds immediately with the current state.

Long polling:  client calls GET /jobs/<id>/status/long?current_status=<s>
              Server loops with sleep until status changes (or timeout), then responds.
              Client re-polls immediately after each response.
"""

import time
import uuid
from flask import Flask, jsonify, request

app = Flask(__name__)

# {job_id: {job_id, instance_id, created_at, delays}}
_jobs: dict = {}

EC2_STATES = ["pending", "initializing", "running", "complete"]

# Seconds between successive state transitions.
# Override via app.config["STATE_DELAYS"] before starting (useful in tests).
DEFAULT_STATE_DELAYS = [2, 3, 4]  # pending→initializing, initializing→running, running→complete

# How often the long-poll handler wakes up to re-check the status.
LONG_POLL_TICK = 0.1


# --------------------------------------------------------------------------- #
# EC2 simulation (pure, time-based — no background thread)
# --------------------------------------------------------------------------- #

def simulate_ec2(elapsed: float, delays: list[float]) -> str:
    """
    Return the EC2 state for a job that is `elapsed` seconds old.

    Works by accumulating each delay threshold:
      elapsed < d0               → pending
      d0 <= elapsed < d0+d1      → initializing
      d0+d1 <= elapsed < d0+d1+d2 → running
      elapsed >= d0+d1+d2        → complete
    """
    cumulative = 0.0
    for i, delay in enumerate(delays):
        cumulative += delay
        if elapsed < cumulative:
            return EC2_STATES[i]
    return EC2_STATES[-1]


# --------------------------------------------------------------------------- #
# Routes
# --------------------------------------------------------------------------- #

@app.post("/jobs")
def create_job():
    """Start a mock EC2 creation job. Returns job metadata including job_id."""
    job_id = uuid.uuid4().hex[:8]
    delays = app.config.get("STATE_DELAYS", DEFAULT_STATE_DELAYS)
    _jobs[job_id] = {
        "job_id": job_id,
        "instance_id": f"i-{uuid.uuid4().hex[:17]}",
        "created_at": time.time(),
        "delays": list(delays),
    }
    return jsonify(_snapshot(job_id)), 201


@app.get("/jobs/<job_id>/status")
def short_poll(job_id: str):
    """
    Short polling endpoint.
    Always responds immediately with the current computed status.
    """
    if job_id not in _jobs:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(_snapshot(job_id))


@app.get("/jobs/<job_id>/status/long")
def long_poll(job_id: str):
    """
    Long polling endpoint.
    Query params:
      current_status  – the status the client already knows about
      timeout         – max seconds to hold the connection (default 30)

    Behaviour:
    - Re-checks the computed status every LONG_POLL_TICK seconds.
    - Returns as soon as the status differs from current_status.
    - Returns the (possibly unchanged) status when timeout elapses.
    """
    if job_id not in _jobs:
        return jsonify({"error": "Job not found"}), 404

    current_status = request.args.get("current_status", "")
    timeout = float(request.args.get("timeout", 30))
    deadline = time.time() + timeout

    while time.time() < deadline:
        snapshot = _snapshot(job_id)
        if snapshot["status"] != current_status:
            return jsonify(snapshot)
        time.sleep(LONG_POLL_TICK)

    # Timeout expired — return whatever the status is now
    return jsonify(_snapshot(job_id))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #

def _snapshot(job_id: str) -> dict:
    """Build a response dict with the current computed status."""
    job = _jobs[job_id]
    elapsed = time.time() - job["created_at"]
    status = simulate_ec2(elapsed, job["delays"])
    return {
        "job_id": job_id,
        "status": status,
        "instance_id": job["instance_id"],
        "created_at": job["created_at"],
    }


def reset_state() -> None:
    """Clear all jobs — used between tests."""
    _jobs.clear()


if __name__ == "__main__":
    app.run(debug=False, threaded=True, port=5050)
