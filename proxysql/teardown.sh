#!/bin/bash
# Stops MySQL master, replica, and MySQL Router.
# Leaves data/ intact — run setup.sh again to restart without re-initialising.
# Pass --clean to also wipe data/ and /tmp/proxysql_demo.

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$DEMO_DIR/data"
MYSQLADMIN="$(brew --prefix)/bin/mysqladmin"

stop_mysql() {
    local label=$1 sock=$2
    if "$MYSQLADMIN" --socket="$sock" -u root ping &>/dev/null 2>&1; then
        echo "Stopping $label..."
        "$MYSQLADMIN" --socket="$sock" -u root shutdown
    else
        echo "$label not running."
    fi
}

stop_mysql "MySQL master"    "$DATA/master.sock"
stop_mysql "MySQL replica-1" "$DATA/replica.sock"
stop_mysql "MySQL replica-2" "$DATA/replica2.sock"

if pgrep -f "mysqlrouter -c /tmp/proxysql_demo" &>/dev/null; then
    echo "Stopping MySQL Router..."
    pkill -f "mysqlrouter -c /tmp/proxysql_demo" || true
else
    echo "MySQL Router not running."
fi

if [ "$1" = "--clean" ]; then
    echo "Removing data/ and /tmp/proxysql_demo ..."
    rm -rf "$DATA" /tmp/proxysql_demo
    echo "Clean done. Run setup.sh to start fresh."
fi

echo "Done."
