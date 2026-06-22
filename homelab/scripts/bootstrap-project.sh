#!/usr/bin/env bash
# Onboard a prototype onto the shared platform — the "share the instance, never
# the data" boundary. Idempotent: safe to re-run.
#
# Creates, for <project>:
#   - a Postgres DATABASE + owning role (random password)
#   - an S3 bucket in LocalStack
#   - a k8s namespace
#   - a Secret (db password + AWS creds) in that namespace
#
# Redis is shared by logical DB index (passed as arg, tracked in registry.md);
# Kafka is shared by topic prefix "<project>." — neither needs server-side setup.
#
#   Usage: scripts/bootstrap-project.sh <project> <redis-db-index>
#   Example: scripts/bootstrap-project.sh g2-reviews 1
set -euo pipefail

PROJECT="${1:?project name, e.g. g2-reviews}"
REDIS_DB="${2:?redis logical db index 0-15 (see registry.md)}"

# k8s/Postgres identifiers can't contain dashes in all positions — normalise.
DB="$(echo "$PROJECT" | tr '-' '_')"
ROLE="${DB}_user"
BUCKET="${PROJECT}-media"
NS="$PROJECT"

echo ">> onboarding '$PROJECT'  (db=$DB role=$ROLE redis_db=$REDIS_DB bucket=$BUCKET ns=$NS)"

# ── 1. Postgres: database + owning role ─────────────────────────────────────
SUPERPASS="$(kubectl get secret -n platform postgres-superuser \
  -o jsonpath='{.data.POSTGRES_PASSWORD}' | base64 -d)"
PGPASS="$(openssl rand -hex 16)"

psql() { kubectl exec -i -n platform statefulset/postgres -- \
  env PGPASSWORD="$SUPERPASS" psql -U postgres -v ON_ERROR_STOP=1 "$@"; }

# role (idempotent) — set/refresh password each run
psql -d postgres <<SQL
DO \$\$ BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='$ROLE') THEN
    CREATE ROLE $ROLE LOGIN PASSWORD '$PGPASS';
  ELSE
    ALTER ROLE $ROLE WITH PASSWORD '$PGPASS';
  END IF;
END \$\$;
SQL

# database (idempotent) owned by the role
psql -d postgres -tAc \
  "SELECT 1 FROM pg_database WHERE datname='$DB'" | grep -q 1 \
  || psql -d postgres -c "CREATE DATABASE $DB OWNER $ROLE"
psql -d postgres -c "ALTER DATABASE $DB OWNER TO $ROLE"
echo "   postgres: db '$DB' owned by '$ROLE' ✔"

# ── 2. LocalStack: bucket ───────────────────────────────────────────────────
kubectl exec -n platform statefulset/localstack -- \
  awslocal s3 mb "s3://$BUCKET" 2>/dev/null \
  && echo "   s3: created bucket '$BUCKET' ✔" \
  || echo "   s3: bucket '$BUCKET' already exists ✔"

# ── 3. Namespace + Secret ───────────────────────────────────────────────────
kubectl create namespace "$NS" --dry-run=client -o yaml | kubectl apply -f -

DB_URL="postgresql://$ROLE:$PGPASS@postgres.platform.svc.cluster.local:5432/$DB"
kubectl create secret generic "$PROJECT-secrets" -n "$NS" \
  --from-literal=DATABASE_URL="$DB_URL" \
  --from-literal=AWS_ACCESS_KEY_ID="test" \
  --from-literal=AWS_SECRET_ACCESS_KEY="test" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "   k8s: namespace '$NS' + secret '$PROJECT-secrets' ✔"

cat <<EOF

Done. Wiring for '$PROJECT':
  Secret '$PROJECT-secrets' (sensitive — never committed):
    DATABASE_URL  postgresql://$ROLE:***@postgres.platform.svc.cluster.local:5432/$DB
    AWS_ACCESS_KEY_ID / AWS_SECRET_ACCESS_KEY = test / test
  ConfigMap homelab/projects/$PROJECT/configmap.yaml (non-secret, committed):
    REDIS_URL     redis://redis.platform.svc.cluster.local:6379/$REDIS_DB
    KAFKA_BROKER  kafka.platform.svc.cluster.local:9092   (topic prefix: $PROJECT.)
    S3_ENDPOINT_URL  http://localstack.platform.svc.cluster.local:4566   (bucket: $BUCKET)

The app gets DATABASE_URL from the Secret and the rest from the ConfigMap via
envFrom — no prototype source changes. Remember to add '$PROJECT' to registry.md.
EOF
