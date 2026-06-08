import hashlib
import json
import os

import requests
from flask import Flask, Response, request

app = Flask(__name__)

CACHE_FILE = "cache.json"
ORIGIN = "https://www.google.com"


def load_cache():
    if os.path.exists(CACHE_FILE):
        with open(CACHE_FILE) as f:
            return json.load(f)
    return {}


def save_cache(cache):
    with open(CACHE_FILE, "w") as f:
        json.dump(cache, f, indent=2)


def cache_key(method, path, body):
    raw = f"{method}:{path}:{body}"
    return hashlib.sha256(raw.encode()).hexdigest()


@app.route("/", defaults={"path": ""}, methods=["GET", "POST", "PUT", "DELETE"])
@app.route("/<path:path>", methods=["GET", "POST", "PUT", "DELETE"])
def proxy(path):
    body = request.get_data(as_text=True)
    key = cache_key(request.method, request.full_path, body)

    cache = load_cache()

    if key in cache:
        entry = cache[key]
        print(f"[CACHE HIT]  {request.method} /{path}")
        return Response(
            entry["body"],
            status=entry["status"],
            headers=entry["headers"],
        )

    print(f"[CACHE MISS] {request.method} /{path} -> forwarding to {ORIGIN}")
    url = f"{ORIGIN}/{path}"
    if request.query_string:
        url += f"?{request.query_string.decode()}"

    resp = requests.request(
        method=request.method,
        url=url,
        headers={k: v for k, v in request.headers if k.lower() != "host"},
        data=body,
        allow_redirects=True,
        timeout=10,
    )

    # Strip hop-by-hop headers before caching / returning
    skip = {"transfer-encoding", "content-encoding", "connection"}
    headers = {k: v for k, v in resp.headers.items() if k.lower() not in skip}

    cache[key] = {"body": resp.text, "status": resp.status_code, "headers": headers}
    save_cache(cache)

    return Response(resp.text, status=resp.status_code, headers=headers)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=9000, debug=True)
