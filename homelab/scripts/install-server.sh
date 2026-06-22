#!/usr/bin/env bash
# Install the k3s SERVER (control-plane) inside the mini A VM.
# Disables traefik + servicelb to save RAM (prototypes use port-forward/NodePort).
#
#   Usage: scripts/install-server.sh [vm-name]
set -euo pipefail

VM="${1:-homelab-a}"
HERE="$(cd "$(dirname "$0")" && pwd)"

# Bind k3s to the tailnet IP if Tailscale is up in the VM (so the mini B agent
# can reach it across machines); otherwise fall back to the VM's default IP.
NODE_IP="$(orb -m "$VM" bash -lc 'tailscale ip -4 2>/dev/null | head -1 || true')"
if [ -z "$NODE_IP" ]; then
  NODE_IP="$(orb -m "$VM" bash -lc "ip -4 route get 1.1.1.1 | awk '{print \$7; exit}'")"
fi
echo ">> installing k3s server on '$VM' (node-ip=$NODE_IP)"

orb -m "$VM" bash -lc "curl -sfL https://get.k3s.io | INSTALL_K3S_EXEC='server \
  --disable traefik --disable servicelb \
  --write-kubeconfig-mode 644 \
  --secrets-encryption \
  --node-ip $NODE_IP --advertise-address $NODE_IP --tls-san $NODE_IP' sh -"

echo ">> waiting for the node to be Ready"
orb -m "$VM" bash -lc 'sudo k3s kubectl wait --for=condition=Ready node --all --timeout=180s'

# Stash join info for install-agent.sh (lands on the shared Mac filesystem).
JOIN="$HERE/.cluster-join"
{
  echo "SERVER_URL=https://$NODE_IP:6443"
  echo "TOKEN=$(orb -m "$VM" sudo cat /var/lib/rancher/k3s/server/node-token)"
} > "$JOIN"
chmod 600 "$JOIN"
echo ">> wrote join info to $JOIN (git-ignored; used by install-agent.sh)"
echo ">> server up. Next: scripts/fetch-kubeconfig.sh $VM"
