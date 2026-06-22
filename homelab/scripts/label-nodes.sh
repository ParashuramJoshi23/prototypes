#!/usr/bin/env bash
# Label a node with its tenant zone so the platform StatefulSets pin correctly.
# Mini A = "a", Mini B = "b". The two JVM tenants (Kafka, Elasticsearch) are
# kept on separate tenants by the platform manifests.
#
#   Usage: scripts/label-nodes.sh <node-name> <a|b>
set -euo pipefail

NODE="${1:?node name (see: kubectl get nodes)}"
TENANT="${2:?tenant: a or b}"

kubectl label node "$NODE" homelab.tenant="$TENANT" --overwrite
echo ">> labelled $NODE homelab.tenant=$TENANT"
kubectl get nodes -L homelab.tenant
