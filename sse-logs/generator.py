"""
Background deployment log generator.

Each deployment runs in its own daemon thread.  Log lines are written
to  logs/<id>.log  (one entry per line) and the deployment status is
tracked in  logs/<id>.meta  (JSON).

Log format:  <ISO-8601 timestamp> [LEVEL] <message>
"""

import json
import os
import random
import threading
import time
from datetime import datetime, timezone

from faker import Faker

fake = Faker()

LOGS_DIR = os.path.join(os.path.dirname(__file__), "logs")

# ── Log-level weights ────────────────────────────────────────────────────────
LEVELS = ["INFO", "INFO", "INFO", "INFO", "WARN", "ERROR"]

# ── Deployment phases and their templated log messages ───────────────────────
# Each tuple: (level_override_or_None, template)
PHASES: list[tuple[str, list[tuple[str | None, str]]]] = [
    ("INIT", [
        (None,    "Initializing deployment pipeline"),
        (None,    "Loading configuration from deploy.yaml"),
        (None,    "Target environment: {env}  region: {region}"),
        (None,    "Deployment ID: {deploy_id}  version: {version}"),
    ]),
    ("PROVISION", [
        (None,    "Provisioning {instance_type} instance"),
        (None,    "Instance {instance_id} transitioning to running"),
        ("WARN",  "Waiting for instance to pass status checks..."),
        (None,    "Instance {instance_id} is healthy"),
        (None,    "Assigned elastic IP: {ip}"),
    ]),
    ("PULL", [
        (None,    "Authenticating with container registry"),
        (None,    "Pulling image {image}:{tag}"),
        (None,    "Layer {sha_short}: Already exists"),
        (None,    "Layer {sha_short}: Pull complete"),
        (None,    "Digest: sha256:{sha_long}"),
        (None,    "Image pull complete ({size} MB)"),
    ]),
    ("CONFIGURE", [
        (None,    "Injecting {n_env} environment variables"),
        (None,    "Mounting volume {vol_src} → /app/data"),
        (None,    "Configuring reverse proxy for port {port}"),
        ("WARN",  "Deprecated TLS 1.1 detected — forcing TLS 1.2"),
        (None,    "Firewall rules updated"),
    ]),
    ("START", [
        (None,    "Stopping old container {old_ctr}"),
        (None,    "Starting container {new_ctr}"),
        (None,    "Container bound to 0.0.0.0:{port}"),
        (None,    "Process PID {pid} is running"),
    ]),
    ("HEALTH", [
        (None,    "Running health check: GET {endpoint}/healthz"),
        ("WARN",  "Health check attempt 1/3 — waiting {ms}ms"),
        (None,    "Health check passed: HTTP 200 in {ms}ms"),
        (None,    "Load balancer target registered"),
        (None,    "Service live at https://{domain}"),
    ]),
    ("DONE", [
        (None,    "Rolling update complete — {n_inst} instance(s) healthy"),
        (None,    "Deployment {deploy_id} finished successfully"),
    ]),
]


def _fake_vars(deploy_id: str) -> dict:
    """Generate faker-backed placeholder values for a deployment."""
    image = fake.slug().replace("-", "/", 1)
    tag = f"{random.randint(1,9)}.{random.randint(0,20)}.{random.randint(0,9)}"
    return {
        "env":           random.choice(["production", "staging", "canary"]),
        "region":        random.choice(["us-east-1", "eu-west-2", "ap-south-1"]),
        "deploy_id":     deploy_id,
        "version":       tag,
        "instance_type": random.choice(["t3.medium", "t3.large", "m5.xlarge"]),
        "instance_id":   "i-" + fake.hexify("^^^^^^^^^^"),
        "ip":            fake.ipv4_public(),
        "image":         image,
        "tag":           tag,
        "sha_short":     fake.hexify("^^^^^^^^"),
        "sha_long":      fake.hexify("^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^"),
        "size":          str(random.randint(80, 450)),
        "n_env":         str(random.randint(8, 24)),
        "vol_src":       f"/data/{fake.slug()}",
        "port":          str(random.choice([8080, 3000, 5000, 8000])),
        "old_ctr":       fake.hexify("^^^^^^^^^^^^"),
        "new_ctr":       fake.hexify("^^^^^^^^^^^^"),
        "pid":           str(random.randint(10000, 99999)),
        "endpoint":      f"http://localhost:{random.choice([8080, 3000, 5000])}",
        "ms":            str(random.randint(120, 980)),
        "domain":        fake.domain_name(),
        "n_inst":        str(random.randint(2, 6)),
    }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _log_path(deploy_id: str) -> str:
    return os.path.join(LOGS_DIR, f"{deploy_id}.log")


def _meta_path(deploy_id: str) -> str:
    return os.path.join(LOGS_DIR, f"{deploy_id}.meta")


# ── Public API ───────────────────────────────────────────────────────────────

def start(deploy_id: str, app_name: str) -> None:
    """Spawn a daemon thread that writes logs for this deployment."""
    os.makedirs(LOGS_DIR, exist_ok=True)
    _write_meta(deploy_id, app_name, "running")
    t = threading.Thread(
        target=_run,
        args=(deploy_id, app_name),
        daemon=True,
    )
    t.start()


def read_meta(deploy_id: str) -> dict | None:
    path = _meta_path(deploy_id)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def read_logs(deploy_id: str) -> list[str]:
    path = _log_path(deploy_id)
    if not os.path.exists(path):
        return []
    with open(path) as f:
        return [line.rstrip() for line in f if line.strip()]


def list_deployments() -> list[dict]:
    os.makedirs(LOGS_DIR, exist_ok=True)
    results = []
    for fname in sorted(os.listdir(LOGS_DIR), reverse=True):
        if fname.endswith(".meta"):
            deploy_id = fname[:-5]
            meta = read_meta(deploy_id)
            if meta:
                results.append(meta)
    return results


# ── Internal ─────────────────────────────────────────────────────────────────

def _write_meta(deploy_id: str, app_name: str, status: str) -> None:
    meta = {
        "id":         deploy_id,
        "name":       app_name,
        "status":     status,
        "created_at": _now_iso(),
    }
    # Preserve created_at if already exists
    existing = read_meta(deploy_id)
    if existing:
        meta["created_at"] = existing["created_at"]
    with open(_meta_path(deploy_id), "w") as f:
        json.dump(meta, f)


def _write_log_line(deploy_id: str, level: str, message: str) -> None:
    line = f"{_now_iso()} [{level}] {message}\n"
    with open(_log_path(deploy_id), "a") as f:
        f.write(line)


def _run(deploy_id: str, app_name: str) -> None:
    """Write all phases to the log file then mark the deployment complete."""
    vars_ = _fake_vars(deploy_id)

    for phase_name, entries in PHASES:
        _write_log_line(deploy_id, "INFO", f"── Phase: {phase_name} ──")
        time.sleep(random.uniform(0.2, 0.4))

        for level_override, template in entries:
            try:
                message = template.format(**vars_)
            except KeyError:
                message = template

            level = level_override or random.choices(
                ["INFO", "WARN", "ERROR"],
                weights=[85, 12, 3],
            )[0]

            _write_log_line(deploy_id, level, message)
            time.sleep(random.uniform(0.3, 0.7))

    _write_meta(deploy_id, app_name, "complete")
