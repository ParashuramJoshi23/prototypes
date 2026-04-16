"""
Database sharding demo — Flask API
===================================
Two SQLite shards (db1.sqlite, db2.sqlite).
Shard is chosen by:  shard = user_id % NUM_SHARDS

Endpoints:
    GET  /users              — list all users across all shards
    GET  /user/<id>          — look up a single user (routed to correct shard)

Run:
    pip install -r requirements.txt
    python simple_sharding.py
"""

import sqlite3
import os
from flask import Flask, jsonify

app = Flask(__name__)

NUM_SHARDS = 2
DB_FILES   = {1: "db1.sqlite", 2: "db2.sqlite"}


# ─────────────────────────────────────────
# Shard router
# ─────────────────────────────────────────

def shard_for(user_id: int) -> int:
    """Returns shard number (1 or 2) for a given user_id."""
    return (user_id % NUM_SHARDS) + 1   # 1-indexed: 1 or 2


def get_conn(shard: int) -> sqlite3.Connection:
    conn = sqlite3.connect(DB_FILES[shard])
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────
# DB setup
# ─────────────────────────────────────────

def setup_databases():
    for shard, path in DB_FILES.items():
        conn = sqlite3.connect(path)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                name    TEXT NOT NULL,
                city    TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()

    seed = [
        (1, "Ravi",  "Bangalore"),
        (2, "Priya", "Delhi"),
        (3, "Amit",  "Mumbai"),
        (4, "Sara",  "Chennai"),
        (5, "Kiran", "Hyderabad"),
    ]
    for user_id, name, city in seed:
        shard = shard_for(user_id)
        conn  = get_conn(shard)
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, name, city) VALUES (?, ?, ?)",
            (user_id, name, city),
        )
        conn.commit()
        conn.close()

    print(f"Shards ready: {DB_FILES}")
    print(f"Routing rule: shard = (user_id % {NUM_SHARDS}) + 1\n")


# ─────────────────────────────────────────
# Routes
# ─────────────────────────────────────────

@app.get("/users")
def list_users():
    """Return all users from every shard."""
    all_users = []
    for shard, path in DB_FILES.items():
        conn = get_conn(shard)
        rows = conn.execute("SELECT * FROM users ORDER BY user_id").fetchall()
        conn.close()
        for row in rows:
            all_users.append({**dict(row), "shard": shard})
    all_users.sort(key=lambda u: u["user_id"])
    return jsonify(all_users)


@app.get("/user/<int:user_id>")
def get_user(user_id):
    """Look up a single user — routed to the correct shard."""
    shard = shard_for(user_id)
    conn  = get_conn(shard)
    row   = conn.execute(
        "SELECT * FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    conn.close()

    if row is None:
        return jsonify({"error": f"user {user_id} not found", "shard": shard}), 404

    return jsonify({**dict(row), "shard": shard})


# ─────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────

if __name__ == "__main__":
    setup_databases()
    print("Endpoints:")
    print("  GET  http://localhost:8080/users")
    print("  GET  http://localhost:8080/user/<id>\n")
    app.run(debug=False, port=8080)
