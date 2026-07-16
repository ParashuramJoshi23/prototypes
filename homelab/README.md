# Homelab — shared infrastructure for the prototypes

A 2× Mac Mini **k3s** cluster running **one shared instance** of each backing
store (Postgres, Redis, Kafka, LocalStack/S3; Elasticsearch later). Every
prototype in this repo stays a **self-contained folder with no dependency on any
other** — it just points its connection env vars at the shared stores. See
[`../Homelab.md`](../Homelab.md) for the design rationale.

```
 mini A (server)                         mini B (agent, when online)
 ┌─────────────────────────┐            ┌─────────────────────────┐
 │ OrbStack Ubuntu VM      │  tailnet   │ OrbStack Ubuntu VM      │
 │ ┌─────────────────────┐ │◀──────────▶│ ┌─────────────────────┐ │
 │ │ k3s server          │ │            │ │ k3s agent           │ │
 │ │ ns: platform        │ │            │ │ (ES lands here)     │ │
 │ │  postgres redis     │ │            │ └─────────────────────┘ │
 │ │  kafka  localstack  │ │            └─────────────────────────┘
 │ │ ns: <project> ...   │ │
 │ └─────────────────────┘ │   apps reach stores by DNS:
 └─────────────────────────┘   <store>.platform.svc.cluster.local
```

## The model

| Store         | Shared unit   | Per-project isolation         |
|---------------|---------------|-------------------------------|
| PostgreSQL    | one server    | database + role per project   |
| Redis         | one instance  | logical db index (0–15)       |
| Kafka         | one cluster   | topic prefix `<project>.`     |
| LocalStack/S3 | one endpoint  | bucket per project            |
| k8s           | one cluster   | namespace per project         |

Logical assignments live in [`registry.md`](registry.md). The link between a
prototype and the platform is **only a connection string** — prototype source is
never edited and the `homelab/` tree never imports prototype code.

## Layout

```
platform/    shared stores (the `platform` namespace) — apply with kubectl -k
projects/    per-project app wiring (_template + filled examples)
scripts/     bring-up + onboarding scripts (run from the Mac host, drive the VM via orb)
registry.md  tenant assignment table
```

## Bring-up — mini A (single node)

```bash
cd homelab
scripts/create-vm.sh homelab-a            # OrbStack Ubuntu VM
scripts/install-server.sh homelab-a       # k3s server inside it
scripts/fetch-kubeconfig.sh homelab-a     # host kubectl -> cluster
export KUBECONFIG=$HOME/.kube/homelab.yaml

scripts/label-nodes.sh homelab-a a        # node name = VM name; tenant a
kubectl apply -k platform                 # bring up the shared stores
kubectl get pods -n platform -w           # wait for Running/Ready
```

## Onboard a prototype (example: g2-reviews)

```bash
# 1. carve out its slice of the shared stores (db + role + redis idx + ns + secret)
scripts/bootstrap-project.sh g2-reviews 1

# 2. load the project's own schema into its (empty) database
kubectl exec -i -n platform statefulset/postgres -- \
  psql "$(kubectl get secret g2-reviews-secrets -n g2-reviews \
          -o jsonpath='{.data.DATABASE_URL}' | base64 -d)" \
  < ../g2-reviews/migrations/init.sql

# 3. build the prototype image into the VM's containerd (no registry needed)
docker build -t g2-reviews:homelab ../g2-reviews
docker save g2-reviews:homelab | orb -m homelab-a sudo k3s ctr images import -

# 4. deploy + reach it
kubectl apply -k projects/g2-reviews
scripts/forward.sh g2-reviews 8002      # exports KUBECONFIG + tunnel + port-forward
curl localhost:8002/healthz
```

`forward.sh <project> [local-port]` is the one-command way to reach any deployed
project from the Mac — it sets `KUBECONFIG`, re-opens the API tunnel if needed,
and port-forwards the project's Service. Leave it running; Ctrl-C to stop.
(Default local port = the Service port. If you see "address already in use", a
stale forward is lingering: `pkill -f "kubectl port-forward"`.)

To onboard another prototype: `cp -r projects/_template projects/<name>`, replace
`PROJECT` throughout, pick a free Redis index, add a row to `registry.md`, then
run `bootstrap-project.sh <name> <idx>`.

## Onboard a store-less prototype (example: sse-logs)

Some prototypes use no backing stores at all, so they skip the whole
bootstrap/Secret/ConfigMap dance — just build, deploy, and (optionally) publish:

```bash
docker build -t sse-logs:homelab ../sse-logs
docker save sse-logs:homelab | orb -m homelab-a sudo k3s ctr images import -
kubectl apply -k projects/sse-logs
scripts/forward.sh sse-logs 8000        # private check → http://localhost:8000
```

`projects/sse-logs` has no `configmap.yaml`/Secret (contrast with `_template`).

## Public exposure — the `edge` tunnel

`forward.sh` is private (port-forward to your Mac). To make a prototype
**publicly reachable** — e.g. embed a live demo in a blog — publish it through
the shared Cloudflare Tunnel in [`edge/`](edge/README.md). cloudflared runs in
the cluster and dials out to Cloudflare, so nothing is exposed on the home
network. One-time:

```bash
scripts/setup-tunnel.sh                       # creates tunnel + routes DNS
kubectl apply -k edge
```

Then `sse.parashuramjoshi.in` is live. Add one ingress rule + DNS route per
published project (see `edge/README.md`).

## Add mini B later (when online)

```bash
TS_AUTHKEY=tskey-...  scripts/create-vm.sh   homelab-b   # both VMs on the tailnet
TS_AUTHKEY=tskey-...  # (mini A VM also needs Tailscale — re-run create-vm.sh on A)
scripts/install-agent.sh   homelab-b
scripts/label-nodes.sh     homelab-b b
```

Then enable Elasticsearch: uncomment `elasticsearch.yaml` in
`platform/kustomization.yaml` and `kubectl apply -k platform`. ES pins to
tenant `b`, keeping the two JVM tenants (Kafka + ES) on separate minis.

## Notes

- k3s runs **inside an OrbStack Ubuntu VM** (k3s is Linux-only); this is *not*
  OrbStack's built-in Kubernetes — we want real multi-node k3s.
- traefik + servicelb are disabled to save RAM; reach apps via `port-forward`.
- Each prototype's own `docker-compose.yml` still works for standalone local dev;
  the homelab is the *shared* path, not a replacement.
