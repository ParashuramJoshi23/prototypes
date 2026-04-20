import os
import time
import uuid

from faker import Faker
from flask import Flask, Response, jsonify, render_template, stream_with_context

import generator

app  = Flask(__name__)
fake = Faker()


@app.get("/")
def index():
    return render_template("index.html")


@app.post("/deployments")
def create_deployment():
    deploy_id = uuid.uuid4().hex[:8]
    app_name  = f"{fake.slug()}-service"
    generator.start(deploy_id, app_name)
    return jsonify({"id": deploy_id, "name": app_name}), 201


@app.get("/deployments/<deploy_id>/stream")
def stream(deploy_id: str):
    log_path = os.path.join(generator.LOGS_DIR, f"{deploy_id}.log")

    def generate():
        # Wait up to 5 s for the log file to appear
        waited = 0.0
        while not os.path.exists(log_path) and waited < 5:
            time.sleep(0.1)
            waited += 0.1

        with open(log_path) as f:
            while True:
                line = f.readline()
                if line:
                    yield f"data: {line.rstrip()}\n\n"
                else:
                    meta = generator.read_meta(deploy_id)
                    if meta and meta.get("status") in ("complete", "failed"):
                        yield "event: done\ndata: \n\n"
                        return
                    time.sleep(0.1)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


if __name__ == "__main__":
    os.makedirs(generator.LOGS_DIR, exist_ok=True)
    print("SSE logs demo → http://127.0.0.1:5050")
    app.run(debug=False, port=5050, threaded=True)
