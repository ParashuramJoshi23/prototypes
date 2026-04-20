"""
Tests for short and long polling endpoints.

Uses Flask's built-in test client so no real HTTP server is needed.
State delays are overridden to near-zero so tests run fast.
"""

import time

import pytest

# Import app artefacts
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app import app, reset_state, EC2_STATES


# ─── Fixtures ───────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_state():
    """Wipe all jobs before every test."""
    reset_state()
    yield
    reset_state()


@pytest.fixture
def client():
    app.config["TESTING"] = True
    app.config["STATE_DELAYS"] = [0.05, 0.05, 0.05]   # fast transitions
    with app.test_client() as c:
        yield c


# ─── Job creation ────────────────────────────────────────────────────────────

class TestCreateJob:
    def test_returns_201(self, client):
        r = client.post("/jobs")
        assert r.status_code == 201

    def test_initial_status_is_pending(self, client):
        data = client.post("/jobs").get_json()
        assert data["status"] == "pending"

    def test_response_has_expected_fields(self, client):
        data = client.post("/jobs").get_json()
        for field in ("job_id", "status", "instance_id", "created_at"):
            assert field in data, f"missing field: {field}"

    def test_each_job_gets_unique_id(self, client):
        ids = {client.post("/jobs").get_json()["job_id"] for _ in range(5)}
        assert len(ids) == 5


# ─── Short polling ───────────────────────────────────────────────────────────

class TestShortPoll:
    def test_returns_current_status_immediately(self, client):
        job = client.post("/jobs").get_json()
        r = client.get(f"/jobs/{job['job_id']}/status")
        assert r.status_code == 200
        assert r.get_json()["status"] in EC2_STATES

    def test_unknown_job_returns_404(self, client):
        r = client.get("/jobs/doesnotexist/status")
        assert r.status_code == 404

    def test_status_eventually_becomes_complete(self, client):
        job = client.post("/jobs").get_json()
        job_id = job["job_id"]
        deadline = time.time() + 5.0
        status = ""
        while time.time() < deadline:
            status = client.get(f"/jobs/{job_id}/status").get_json()["status"]
            if status == "complete":
                break
            time.sleep(0.05)
        assert status == "complete", f"job never reached 'complete', last status: {status}"

    def test_status_transitions_in_order(self, client):
        """Each observed status must be >= the previous one in EC2_STATES."""
        job = client.post("/jobs").get_json()
        job_id = job["job_id"]
        seen = []
        deadline = time.time() + 5.0
        while time.time() < deadline:
            s = client.get(f"/jobs/{job_id}/status").get_json()["status"]
            if not seen or s != seen[-1]:
                seen.append(s)
            if s == "complete":
                break
            time.sleep(0.02)

        indices = [EC2_STATES.index(s) for s in seen]
        assert indices == sorted(indices), f"out-of-order transitions: {seen}"


# ─── Long polling ────────────────────────────────────────────────────────────

class TestLongPoll:
    def test_returns_immediately_when_status_already_changed(self, client):
        job = client.post("/jobs").get_json()
        job_id = job["job_id"]
        # Wait for at least one transition
        time.sleep(0.15)
        # Long-poll with a bogus "current_status" of pending when it has moved on
        r = client.get(
            f"/jobs/{job_id}/status/long",
            query_string={"current_status": "pending", "timeout": 5},
        )
        assert r.status_code == 200
        data = r.get_json()
        assert data["status"] != "pending"

    def test_unknown_job_returns_404(self, client):
        r = client.get(
            "/jobs/doesnotexist/status/long",
            query_string={"current_status": "pending"},
        )
        assert r.status_code == 404

    def test_long_poll_blocks_until_status_changes(self, client):
        """
        Verify the server holds the connection while status matches current_status
        and only responds once it changes.
        """
        # Use a slow delay so we can measure the wait
        app.config["STATE_DELAYS"] = [0.3, 0.3, 0.3]
        job = client.post("/jobs").get_json()
        job_id = job["job_id"]

        start = time.perf_counter()
        r = client.get(
            f"/jobs/{job_id}/status/long",
            query_string={"current_status": "pending", "timeout": 5},
        )
        elapsed = time.perf_counter() - start

        assert r.status_code == 200
        data = r.get_json()
        # Server should have waited at least the first STATE_DELAY
        assert elapsed >= 0.25, f"response came too fast ({elapsed:.3f}s) — wasn't really blocking"
        assert data["status"] != "pending"

    def test_long_poll_times_out_gracefully(self, client):
        """
        If no status change within timeout, server returns the (unchanged) status.
        """
        # Artificially slow transitions so timeout fires first
        app.config["STATE_DELAYS"] = [5, 5, 5]
        job = client.post("/jobs").get_json()
        job_id = job["job_id"]

        start = time.perf_counter()
        r = client.get(
            f"/jobs/{job_id}/status/long",
            query_string={"current_status": "pending", "timeout": 0.3},
        )
        elapsed = time.perf_counter() - start

        assert r.status_code == 200
        # Should return after ~0.3 s (the timeout), not 5 s
        assert elapsed < 2.0, f"took too long to time out ({elapsed:.2f}s)"
        # Status is still pending (no transition happened yet)
        assert r.get_json()["status"] == "pending"

    def test_long_poll_detects_all_state_changes(self, client):
        """
        A client that re-polls immediately after each response should observe
        all EC2_STATES transitions.
        """
        app.config["STATE_DELAYS"] = [0.1, 0.1, 0.1]
        job = client.post("/jobs").get_json()
        job_id = job["job_id"]

        observed = ["pending"]
        current = "pending"
        deadline = time.time() + 5.0

        while current != "complete" and time.time() < deadline:
            r = client.get(
                f"/jobs/{job_id}/status/long",
                query_string={"current_status": current, "timeout": 3},
            )
            new = r.get_json()["status"]
            if new != current:
                observed.append(new)
                current = new

        assert observed == EC2_STATES, f"didn't see all states: {observed}"
