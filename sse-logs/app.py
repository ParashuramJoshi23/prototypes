"""
SSE streaming logs demo.

Routes
------
GET  /                          → UI
POST /deployments               → create deployment, start log generator
GET  /deployments               → list all deployments (JSON)
GET  /deployments/<id>/logs     → all stored log lines for a deployment (JSON)
GET  /deployments/<id>/stream   → SSE stream (tail-follow until complete)
"""

import os
import time
import uuid

from flask import Flask, Response, jsonify, render_template, request, stream_with_context

import generator

app = Flask(__name__)

LOGS_DIR = generator.LOGS_DIR


# ── HTTP ─────────────────────────────────────────────────────────────────────

@app.get("/")
def index():
    return render_template("index.html")


@app.post("/deployments")
def create_deployment():
    from faker import Faker
    fake = Faker()
    deploy_id = uuid.uuid4().hex[:8]
    app_name  = f"{fake.slug()}-service"
    generator.start(deploy_id, app_name)
    return jsonify({"id": deploy_id, "name": app_name, "status": "running"}), 201


@app.get("/deployments")
def list_deployments():
    return jsonify(generator.list_deployments())


@app.get("/deployments/<deploy_id>/logs")
def get_logs(deploy_id: str):
    meta = generator.read_meta(deploy_id)
    if meta is None:
        return jsonify({"error": "not found"}), 404
    return jsonify({
        "meta": meta,
        "lines": generator.read_logs(deploy_id),
    })


@app.get("/deployments/<deploy_id>/stream")
def stream(deploy_id: str):
    """
    SSE endpoint — tail-follows the log file until the deployment finishes.

    Events
    ------
    message   →  one log line
    done      →  deployment finished, client should close the EventSource
    """
    meta = generator.read_meta(deploy_id)
    if meta is None:
        return jsonify({"error": "not found"}), 404

    def generate():
        log_path = os.path.join(LOGS_DIR, f"{deploy_id}.log")

        # Wait for the log file to be created (generator may not have started yet)
        waited = 0.0
        while not os.path.exists(log_path) and waited < 5:
            time.sleep(0.1)
            waited += 0.1

        if not os.path.exists(log_path):
            yield "event: error\ndata: log file not found\n\n"
            return

        with open(log_path) as f:
            while True:
                line = f.readline()
                if line:
                    # Strip trailing newline; SSE format adds its own
                    yield f"data: {line.rstrip()}\n\n"
                else:
                    # No new data — check if deployment finished
                    meta = generator.read_meta(deploy_id)
                    if meta and meta.get("status") in ("complete", "failed"):
                        yield "event: done\ndata: \n\n"
                        return
                    time.sleep(0.1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control":    "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering if behind a proxy
            "Connection":       "keep-alive",
        },
    )


if __name__ == "__main__":
    os.makedirs(LOGS_DIR, exist_ok=True)
    print("SSE logs demo → http://127.0.0.1:5050")
    app.run(debug=False, port=5050, threaded=True)
