#!/usr/bin/env python3
"""Regenerate homelab/deploy/sse-logs.apply.yaml from the canonical manifests.

The bundle is a convenience single-file mirror of the kustomize sources, with
namespaces ordered first so `kubectl apply -f` works in one shot. The kustomize
dirs remain canonical — edit those, then re-run this to refresh the bundle.

    python3 homelab/deploy/build-bundle.py
"""
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[2]  # repo root
OUT = ROOT / "homelab/deploy/sse-logs.apply.yaml"

HEADER = """# ─────────────────────────────────────────────────────────────────────────────
# GENERATED BUNDLE — do not edit by hand.
# Concatenation of the canonical manifests (namespaces ordered first):
#   homelab/projects/sse-logs/namespace.yaml
#   homelab/edge/namespace.yaml
#   homelab/projects/sse-logs/deployment.yaml   (Deployment + Service)
#   homelab/edge/cloudflared.yaml               (ConfigMap + Deployment)
#
# Everything a `kubectl apply -f` needs EXCEPT the out-of-band Secret
# (cloudflared-credentials). See homelab/deploy/AGENT_APPLY.md for the full
# procedure, prerequisites, and verification.
#
# Regenerate:  python3 homelab/deploy/build-bundle.py
# ─────────────────────────────────────────────────────────────────────────────"""

SECTIONS = [
    ("# ns: sse-logs",                        "homelab/projects/sse-logs/namespace.yaml"),
    ("# ns: edge",                            "homelab/edge/namespace.yaml"),
    ("# sse-logs app (Deployment + Service)", "homelab/projects/sse-logs/deployment.yaml"),
    ("# edge tunnel (ConfigMap + Deployment)","homelab/edge/cloudflared.yaml"),
]


def main() -> None:
    parts = [HEADER]
    for label, rel in SECTIONS:
        parts.append(f"--- {label}")
        parts.append((ROOT / rel).read_text().strip("\n"))
    OUT.write_text("\n".join(parts) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
