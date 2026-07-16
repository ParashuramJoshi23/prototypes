#!/usr/bin/env bash
# Stand up the shared Cloudflare Tunnel that fronts the cluster, and mint its
# in-cluster Secret. The tunnel is how prototypes become publicly reachable
# (e.g. embedded in a blog) without opening a port or exposing the home IP.
#
# Prereqs (one-time, on the Mac host):
#   - `cloudflared` installed        (brew install cloudflared)
#   - `cloudflared tunnel login`     (authorizes your Cloudflare account + zone)
#   - a domain in that Cloudflare account (the <base-domain> below)
#
# Idempotent: re-running reuses an existing tunnel and re-applies the Secret.
#
#   Usage: scripts/setup-tunnel.sh <base-domain> [tunnel-name]
#   Example: scripts/setup-tunnel.sh demos.example.com
#
# After this, edit homelab/edge/cloudflared.yaml so the ingress hostnames use
# <base-domain>, then: kubectl apply -k homelab/edge
set -euo pipefail

BASE_DOMAIN="${1:?base domain for demo hostnames, e.g. demos.example.com}"
TUNNEL="${2:-homelab-demos}"

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
# Add a line here for every prototype you publish (must match the ingress rules
# in edge/cloudflared.yaml).
for host in "sse-logs.$BASE_DOMAIN"; do
  echo ">> routing DNS: $host -> $UUID.cfargotunnel.com"
  cloudflared tunnel route dns "$TUNNEL" "$host" || echo "   (route may already exist — ok)"
done

cat <<EOF

Tunnel '$TUNNEL' ready.
  Next:
    1. In homelab/edge/cloudflared.yaml, set the ingress hostnames to use
       '$BASE_DOMAIN' (replace 'demos.example.com').
    2. kubectl apply -k homelab/edge
    3. kubectl -n edge rollout status deploy/cloudflared
    4. Visit https://sse-logs.$BASE_DOMAIN  (or embed it — see edge/README.md)
EOF
