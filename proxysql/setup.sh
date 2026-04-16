#!/bin/bash
# Sets up three local MySQL instances + MySQL Router for read/write splitting.
#
#   MySQL master    :3310  (writes)
#   MySQL replica-1 :3311  (reads, read-only=ON)
#   MySQL replica-2 :3312  (reads, read-only=ON)
#   MySQL Router    :6033  → master     (write endpoint)
#                   :6034  → replica-1  (read endpoint)
#                   :6035  → replica-2  (read endpoint)
#
# Re-running is safe — skips initialisation if data dirs already exist.

set -e

DEMO_DIR="$(cd "$(dirname "$0")" && pwd)"
DATA="$DEMO_DIR/data"
RUNTIME="/tmp/proxysql_demo"
MASTER_PORT=3310
REPLICA_PORT=3311
REPLICA2_PORT=3312
BREW="$(brew --prefix)"
MYSQLD="$BREW/bin/mysqld"
MYSQL="$BREW/bin/mysql"
MYSQLADMIN="$BREW/bin/mysqladmin"
MYSQLROUTER="$BREW/bin/mysqlrouter"
WHOAMI="$(whoami)"


# ─────────────────────────────────────────
# 1. Generate MySQL config files
# ─────────────────────────────────────────
mkdir -p "$DATA/master" "$DATA/replica" "$DATA/replica2"

cat > "$DATA/master.cnf" <<EOF
[mysqld]
user                     = $WHOAMI
server-id                = 1
port                     = $MASTER_PORT
datadir                  = $DATA/master
socket                   = $DATA/master.sock
pid-file                 = $DATA/master.pid
log-error                = $DATA/master-error.log
log-bin                  = mysql-bin
binlog-format            = ROW
gtid-mode                = ON
enforce-gtid-consistency = ON
log-replica-updates      = ON
EOF

cat > "$DATA/replica.cnf" <<EOF
[mysqld]
user                     = $WHOAMI
server-id                = 2
port                     = $REPLICA_PORT
datadir                  = $DATA/replica
socket                   = $DATA/replica.sock
pid-file                 = $DATA/replica.pid
log-error                = $DATA/replica-error.log
log-bin                  = mysql-bin
binlog-format            = ROW
gtid-mode                = ON
enforce-gtid-consistency = ON
log-replica-updates      = ON
read-only                = ON
EOF

cat > "$DATA/replica2.cnf" <<EOF
[mysqld]
user                     = $WHOAMI
server-id                = 3
port                     = $REPLICA2_PORT
datadir                  = $DATA/replica2
socket                   = $DATA/replica2.sock
pid-file                 = $DATA/replica2.pid
log-error                = $DATA/replica2-error.log
log-bin                  = mysql-bin
binlog-format            = ROW
gtid-mode                = ON
enforce-gtid-consistency = ON
log-replica-updates      = ON
read-only                = ON
EOF


# ─────────────────────────────────────────
# 2. Initialise data directories (once only)
# ─────────────────────────────────────────
if [ ! -d "$DATA/master/mysql" ]; then
    echo "==> Initialising master datadir..."
    "$MYSQLD" --defaults-file="$DATA/master.cnf" --initialize-insecure
fi

if [ ! -d "$DATA/replica/mysql" ]; then
    echo "==> Initialising replica-1 datadir..."
    "$MYSQLD" --defaults-file="$DATA/replica.cnf" --initialize-insecure
fi

if [ ! -d "$DATA/replica2/mysql" ]; then
    echo "==> Initialising replica-2 datadir..."
    "$MYSQLD" --defaults-file="$DATA/replica2.cnf" --initialize-insecure
fi


# ─────────────────────────────────────────
# 3. Start MySQL master
# ─────────────────────────────────────────
echo "==> Starting MySQL master on port $MASTER_PORT..."
"$MYSQLD" --defaults-file="$DATA/master.cnf" &

echo -n "  Waiting for master"
until "$MYSQLADMIN" --socket="$DATA/master.sock" -u root ping &>/dev/null 2>&1; do
    echo -n "."; sleep 1
done
echo " ready."

# Configure master: schema, users
"$MYSQL" -u root --socket="$DATA/master.sock" <<SQL
CREATE DATABASE IF NOT EXISTS demo;
USE demo;
CREATE TABLE IF NOT EXISTS users (
    id   INT AUTO_INCREMENT PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    city VARCHAR(100) NOT NULL
);
CREATE USER IF NOT EXISTS 'app_user'@'%' IDENTIFIED BY 'app_password';
GRANT ALL PRIVILEGES ON demo.* TO 'app_user'@'%';
CREATE USER IF NOT EXISTS 'replicator'@'%' IDENTIFIED BY 'replicator_pass';
GRANT REPLICATION SLAVE ON *.* TO 'replicator'@'%';
FLUSH PRIVILEGES;
SQL


# ─────────────────────────────────────────
# 4. Start MySQL replicas
# ─────────────────────────────────────────
for replica_num in 1 2; do
    if [ "$replica_num" = "1" ]; then
        port=$REPLICA_PORT; sock="$DATA/replica.sock"; cnf="$DATA/replica.cnf"
    else
        port=$REPLICA2_PORT; sock="$DATA/replica2.sock"; cnf="$DATA/replica2.cnf"
    fi

    echo "==> Starting MySQL replica-$replica_num on port $port..."
    "$MYSQLD" --defaults-file="$cnf" &

    echo -n "  Waiting for replica-$replica_num"
    until "$MYSQLADMIN" --socket="$sock" -u root ping &>/dev/null 2>&1; do
        echo -n "."; sleep 1
    done
    echo " ready."
done


# ─────────────────────────────────────────
# 5. Wire up replication (GTID, auto-position)
# ─────────────────────────────────────────
echo "==> Configuring replication for both replicas..."
for sock in "$DATA/replica.sock" "$DATA/replica2.sock"; do
    "$MYSQL" -u root --socket="$sock" <<SQL
STOP REPLICA;
CHANGE REPLICATION SOURCE TO
    SOURCE_HOST          = '127.0.0.1',
    SOURCE_PORT          = $MASTER_PORT,
    SOURCE_USER          = 'replicator',
    SOURCE_PASSWORD      = 'replicator_pass',
    SOURCE_AUTO_POSITION = 1;
START REPLICA;
SQL
done

for label_sock in "replica-1:$DATA/replica.sock" "replica-2:$DATA/replica2.sock"; do
    label="${label_sock%%:*}"; sock="${label_sock#*:}"
    echo "  $label status:"
    "$MYSQL" -u root --socket="$sock" \
        -e "SHOW REPLICA STATUS\G" 2>/dev/null \
        | grep -E "Running|Error|Behind|Source_Host" | sed 's/^/    /'
done


# ─────────────────────────────────────────
# 6. Start MySQL Router
# ─────────────────────────────────────────
echo ""
echo "==> Starting MySQL Router..."
pkill -f "mysqlrouter -c $RUNTIME" 2>/dev/null; sleep 1 || true
mkdir -p "$RUNTIME"

sed \
    -e "s|MASTER_PORT|$MASTER_PORT|g"     \
    -e "s|REPLICA_PORT|$REPLICA_PORT|g"   \
    -e "s|REPLICA2_PORT|$REPLICA2_PORT|g" \
    -e "s|RUNTIME_DIR|$RUNTIME|g"         \
    "$DEMO_DIR/mysqlrouter.conf.template" > "$RUNTIME/mysqlrouter.conf"

"$MYSQLROUTER" -c "$RUNTIME/mysqlrouter.conf" &
sleep 2

echo ""
echo "All services running:"
echo "  MySQL master    → 127.0.0.1:$MASTER_PORT   (direct)"
echo "  MySQL replica-1 → 127.0.0.1:$REPLICA_PORT   (direct)"
echo "  MySQL replica-2 → 127.0.0.1:$REPLICA2_PORT   (direct)"
echo "  MySQL Router    → 127.0.0.1:6033  (write endpoint → master)"
echo "                    127.0.0.1:6034  (read  endpoint → replica-1)"
echo "                    127.0.0.1:6035  (read  endpoint → replica-2)"
echo ""
echo "Next: python3 proxysql_demo.py"
echo "Stop: ./teardown.sh"
