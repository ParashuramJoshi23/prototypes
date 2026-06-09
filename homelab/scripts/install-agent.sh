#!/usr/bin/env bash
# Join a second node (mini B VM) to the cluster as a k3s AGENT.
# Requires: install-server.sh already run (produces scripts/.cluster-join),
# and BOTH VMs on the tailnet (run create-vm.sh with TS_AUTHKEY on each).
#
#   Usage: scripts/install-agent.sh [vm-name]
set -euo pipefail

VM="${1:-homelab-b}"
HERE="$(cd "$(dirname "$0")" && pwd)"
JOIN="$HERE/.cluster-join"

[ -f "$JOIN" ] || { echo "ERROR: $JOIN missing — run install-server.sh on mini A first."; exit 1; }
# shellcheck disable=SC1090
source "$JOIN"

NODE_IP="$(orb -m "$VM" bash -lc 'tailscale ip -4 2>/dev/null | head -1 || true')"
if [ -z "$NODE_IP" ]; then
  echo "ERROR: '$VM' has no tailnet IP. Cross-mini join needs Tailscale in the VM."
  echo "       Re-run: TS_AUTHKEY=tskey-... scripts/create-vm.sh $VM"
  exit 1
fi

echo ">> joining '$VM' ($NODE_IP) to $SERVER_URL as agent"
orb -m "$VM" bash -lc "curl -sfL https://get.k3s.io | \
  K3S_URL='$SERVER_URL' K3S_TOKEN='$TOKEN' \
  INSTALL_K3S_EXEC='agent --node-ip $NODE_IP' sh -"

echo ">> agent joined. Now label it:  scripts/label-nodes.sh <node-name> b"
echo "   (find the node name with: kubectl get nodes)"
