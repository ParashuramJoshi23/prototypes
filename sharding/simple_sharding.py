"""
Simplest possible database sharding demo.

Two SQLite databases (db1.sqlite, db2.sqlite).
Rule: user_id == 2 → DB 2, everything else → DB 1.
We only READ from them.
"""

import sqlite3
import os

# ---------- SETUP: Create two small databases with some data ----------

def setup_databases():
    # DB 1: holds user 1 and user 3
    conn1 = sqlite3.connect("db1.sqlite")
    conn1.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER, name TEXT, city TEXT)")
    conn1.execute("DELETE FROM users")  # fresh start
    conn1.execute("INSERT INTO users VALUES (1, 'Ravi', 'Bangalore')")
    conn1.execute("INSERT INTO users VALUES (3, 'Amit', 'Mumbai')")
    conn1.commit()
    conn1.close()

    # DB 2: holds user 2
    conn2 = sqlite3.connect("db2.sqlite")
    conn2.execute("CREATE TABLE IF NOT EXISTS users (user_id INTEGER, name TEXT, city TEXT)")
    conn2.execute("DELETE FROM users")
    conn2.execute("INSERT INTO users VALUES (2, 'Priya', 'Delhi')")
    conn2.commit()
    conn2.close()

    print("Created db1.sqlite (users 1, 3) and db2.sqlite (user 2)\n")


# ---------- THE SHARD ROUTER: This is the entire concept ----------

def get_db(user_id):
    """Pick which database to query."""
    if user_id == 2:
        return sqlite3.connect("db2.sqlite")
    else:
        return sqlite3.connect("db1.sqlite")


# ---------- QUERY: Just a normal SELECT, but on the right DB ----------

def find_user(user_id):
    db = get_db(user_id)  # ← This is sharding. That's it.
    cursor = db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    db.close()

    if row:
        print(f"  user_id={row[0]}, name={row[1]}, city={row[2]}")
    else:
        print(f"  user {user_id} not found")


# ---------- RUN IT ----------

setup_databases()

for uid in [1, 2, 3]:
    db_name = "db2" if uid == 2 else "db1"
    print(f"Looking up user {uid} → routed to {db_name}")
    find_user(uid)
    print()

# Cleanup
os.remove("db1.sqlite")
os.remove("db2.sqlite")
