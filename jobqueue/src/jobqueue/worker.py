"""The worker loop: claim -> run -> mark done."""

import os
import signal
import socket
import subprocess
import time

from jobqueue import db

TIMEOUT_S = 300
MAX_OUTPUT = 64 * 1024


def run_command(command: str) -> tuple[int, str]:
    """Run a shell command, returning (exit_code, combined stdout+stderr)."""
    # start_new_session puts the job in its own process group, so a Ctrl+C in
    # the worker's terminal doesn't reach it and the job can finish normally.
    proc = subprocess.Popen(
        command,
        shell=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    try:
        out, _ = proc.communicate(timeout=TIMEOUT_S)
        note = b""
    except subprocess.TimeoutExpired:
        # Kill the whole group, not just the shell, so no children keep the pipe open.
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
        note = f"\n[jq: killed after {TIMEOUT_S}s timeout]".encode()
    out = out[:MAX_OUTPUT] + note
    # Postgres TEXT can't hold NUL bytes.
    text = out.decode("utf-8", errors="replace").replace("\x00", "")
    return proc.returncode, text


def run_worker() -> None:
    worker_id = f"{socket.gethostname()}:{os.getpid()}"
    stopping = False

    def on_sigint(signum, frame):
        nonlocal stopping
        # Further Ctrl+C presses are ignored on purpose: `uv run` forwards SIGINT
        # to us on top of the terminal's own, so one keypress arrives twice.
        # Ctrl+\ (SIGQUIT) is the way to force-quit.
        if not stopping:
            print("stopping after current job (Ctrl+\\ to force)", flush=True)
        stopping = True

    signal.signal(signal.SIGINT, on_sigint)
    print(f"worker {worker_id} started", flush=True)

    with db.connect() as conn:
        while not stopping:
            job = db.claim_next(conn, worker_id)
            if job is None:
                time.sleep(1)
                continue
            start = time.monotonic()
            exit_code, output = run_command(job["command"])
            db.finish(conn, job["id"], exit_code, output)
            took_ms = round((time.monotonic() - start) * 1000)
            status = "succeeded" if exit_code == 0 else "failed"
            print(
                f"job={job['id']} status={status} exit={exit_code} took={took_ms}",
                flush=True,
            )
    print("worker stopped", flush=True)
