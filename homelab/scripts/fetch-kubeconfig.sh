#!/usr/bin/env bash
# Give the Mac host's kubectl access to the in-VM k3s API.
#
# OrbStack doesn't route raw L3 traffic from the Mac to the machine's k3s API,
# but its SSH path (<machine>@orb) works. So we open an SSH local port-forward
# to the VM's 127.0.0.1:6443 and use the default kubeconfig unchanged — the k3s
# server cert already trusts 127.0.0.1, so TLS stays valid. kubectl port-forward
# also tunnels through the API server, so app access works over this too.
#
#   Usage: scripts/fetch-kubeconfig.sh [vm-name]
#   Then:  export KUBECONFIG=$HOME/.kube/homelab.yaml
set -euo pipefail

VM="${1:-homelab-a}"
DEST="$HOME/.kube/homelab.yaml"
LPORT=6443

# 1. copy kubeconfig as-is (server stays https://127.0.0.1:6443)
mkdir -p "$HOME/.kube"
orb -m "$VM" sudo cat /etc/rancher/k3s/k3s.yaml > "$DEST"
chmod 600 "$DEST"

# 2. (re)establish the background SSH tunnel for the API port
if lsof -nP -iTCP:$LPORT -sTCP:LISTEN >/dev/null 2>&1; then
  echo ">> something already listens on :$LPORT (assuming an existing tunnel)"
else
  ssh -fN -o ExitOnForwardFailure=yes -L "$LPORT:127.0.0.1:6443" "$VM@orb"
  echo ">> opened SSH tunnel localhost:$LPORT -> $VM:6443"
fi

echo ">> wrote $DEST"
echo ">> export KUBECONFIG=$DEST"
kubectl --kubeconfig "$DEST" get nodes
