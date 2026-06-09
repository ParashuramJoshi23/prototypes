#!/usr/bin/env bash
# Create an OrbStack Ubuntu machine to host a k3s node.
# k3s is Linux-only, so each mini runs k3s inside one of these VMs.
# Run on the mini that should host the node.
#
#   Usage: scripts/create-vm.sh [vm-name]
#   Optional: TS_AUTHKEY=tskey-... scripts/create-vm.sh homelab-a
#             (installs Tailscale inside the VM so nodes can talk across minis)
set -euo pipefail

VM="${1:-homelab-a}"
DISTRO="ubuntu"

if orb list 2>/dev/null | awk '{print $1}' | grep -qx "$VM"; then
  echo ">> OrbStack machine '$VM' already exists — skipping create."
else
  echo ">> creating OrbStack machine '$VM' ($DISTRO)"
  orb create "$DISTRO" "$VM"
fi

echo ">> installing base packages in '$VM'"
orb -m "$VM" sudo apt-get update -y
orb -m "$VM" sudo apt-get install -y curl ca-certificates

if [ -n "${TS_AUTHKEY:-}" ]; then
  echo ">> installing Tailscale in '$VM' and joining the tailnet"
  orb -m "$VM" bash -lc 'curl -fsSL https://tailscale.com/install.sh | sudo sh'
  orb -m "$VM" sudo tailscale up --authkey "$TS_AUTHKEY" --hostname "$VM" --ssh
  echo ">> '$VM' tailnet IP: $(orb -m "$VM" tailscale ip -4 | head -1)"
else
  echo "NOTE: TS_AUTHKEY not set — skipped Tailscale."
  echo "      That's fine for a single-node mini A. For the mini B agent join,"
  echo "      re-run with TS_AUTHKEY so both VMs share the tailnet."
fi

echo ">> '$VM' ready. Next: scripts/install-server.sh $VM   (or install-agent.sh on mini B)"
