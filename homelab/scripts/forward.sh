#!/usr/bin/env bash
# Port-forward a project's service to your Mac with one command.
# Handles the two things that trip people up: exporting KUBECONFIG and making
# sure the API SSH tunnel is up.
#
#   Usage: scripts/forward.sh <project> [local-port]
#   Example: scripts/forward.sh g2-reviews        # -> localhost:8000 (the svc port)
#            scripts/forward.sh g2-reviews 8002    # -> localhost:8002
#
# Leave it running; Ctrl-C to stop. By convention namespace == project name and
# the Service is named after the project.
set -euo pipefail

PROJECT="${1:?project name, e.g. g2-reviews}"
HERE="$(cd "$(dirname "$0")" && pwd)"

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/homelab.yaml}"

# 1. ensure the API tunnel (:6443) is up — without it kubectl can't reach the VM.
if ! lsof -nP -iTCP:6443 -sTCP:LISTEN >/dev/null 2>&1; then
  echo ">> API tunnel down — re-establishing via fetch-kubeconfig.sh"
  "$HERE/fetch-kubeconfig.sh" homelab-a >/dev/null
fi

# 2. find the service port (target the first declared port).
SVC_PORT="$(kubectl get svc "$PROJECT" -n "$PROJECT" \
  -o jsonpath='{.spec.ports[0].port}' 2>/dev/null || true)"
if [ -z "$SVC_PORT" ]; then
  echo "ERROR: no service '$PROJECT' in namespace '$PROJECT'. Services there:"
  kubectl get svc -n "$PROJECT" 2>/dev/null || echo "  (namespace not found — is the project deployed?)"
  exit 1
fi

LOCAL="${2:-$SVC_PORT}"
echo ">> http://localhost:$LOCAL  ->  svc/$PROJECT:$SVC_PORT  (ns $PROJECT)"
echo ">> Ctrl-C to stop."
exec kubectl port-forward -n "$PROJECT" "svc/$PROJECT" "$LOCAL:$SVC_PORT"
