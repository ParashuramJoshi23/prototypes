#!/usr/bin/env bash
# Stand up the shared Cloudflare Tunnel that fronts the cluster, and mint its
# in-cluster Secret. The tunnel is how prototypes become publicly reachable
# (e.g. embedded in a blog) without opening a port or exposing the home IP.
#
# Prereqs (one-time, on the Mac host):
#   - `cloudflared` installed        (brew install cloudflared)
#   - `cloudflared tunnel login`     (authorizes your Cloudflare account + zone)
#   - the domain's zone (parashuramjoshi.in) on Cloudflare (nameservers pointed
#     at Cloudflare) so DNS records can be created for it
#
# Idempotent: re-running reuses an existing tunnel and re-applies the Secret.
#
#   Usage: scripts/setup-tunnel.sh [tunnel-name]
#   Example: scripts/setup-tunnel.sh
#
# PUBLISHED_HOSTS below must match the ingress hostnames in
# homelab/edge/cloudflared.yaml. Add a host here when you publish a new project.
set -euo pipefail

TUNNEL="${1:-homelab-demos}"

# Public hostnames to route to this tunnel (one per published prototype).
# Keep in sync with the `ingress:` block in homelab/edge/cloudflared.yaml.
PUBLISHED_HOSTS=(
  "sse.parashuramjoshi.in"
)

export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/homelab.yaml}"

command -v cloudflared >/dev/null || { echo "ERROR: cloudflared not installed (brew install cloudflared)"; exit 1; }

# ── 1. create the tunnel (idempotent) ───────────────────────────────────────
if cloudflared tunnel list --name "$TUNNEL" --output json 2>/dev/null | grep -q '"id"'; then
  echo ">> tunnel '$TUNNEL' already exists — reusing"
else
  echo ">> creating tunnel '$TUNNEL'"
  cloudflared tunnel create "$TUNNEL"
fi

# resolve UUID + credentials file
UUID="$(cloudflared tunnel list --name "$TUNNEL" --output json | grep -oE '[0-9a-f-]{36}' | head -1)"
CREDS="$HOME/.cloudflared/$UUID.json"
[ -f "$CREDS" ] || { echo "ERROR: credentials file not found at $CREDS"; exit 1; }
echo "   tunnel UUID: $UUID"

# ── 2. mint the in-cluster Secret from credentials.json ──────────────────────
kubectl create namespace edge --dry-run=client -o yaml | kubectl apply -f -
kubectl create secret generic cloudflared-credentials -n edge \
  --from-file=credentials.json="$CREDS" \
  --dry-run=client -o yaml | kubectl apply -f -
echo "   k8s: secret 'cloudflared-credentials' in ns 'edge' ✔"

# ── 3. route DNS for each published hostname ─────────────────────────────────
# Creates a proxied CNAME <host> -> <UUID>.cfargotunnel.com in the Cloudflare
# zone. Requires the host's zone (parashuramjoshi.in) to be on Cloudflare.
for host in "${PUBLISHED_HOSTS[@]}"; do
  echo ">> routing DNS: $host -> $UUID.cfargotunnel.com"
  cloudflared tunnel route dns "$TUNNEL" "$host" || echo "   (route may already exist — ok)"
done

cat <<EOF

Tunnel '$TUNNEL' ready. Routed: ${PUBLISHED_HOSTS[*]}
  Next:
    1. kubectl apply -k homelab/edge
    2. kubectl -n edge rollout status deploy/cloudflared
    3. Visit https://${PUBLISHED_HOSTS[0]}  (or embed it — see edge/README.md)
EOF
