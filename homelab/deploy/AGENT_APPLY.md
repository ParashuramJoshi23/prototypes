# Apply task card — sse-logs on the homelab (+ public edge tunnel)

**For:** an agent (or human) with `kubectl` access to the homelab k3s cluster.
**Goal:** deploy the `sse-logs` demo and, if Cloudflare credentials are available,
publish it through the shared tunnel.
**Bundle:** [`sse-logs.apply.yaml`](sse-logs.apply.yaml) — all 6 objects, no Secrets.

This is designed so the **app deploys and fully verifies with kube access alone**.
The public tunnel needs one Cloudflare-authenticated step; if you can't do it,
finish Phase 1 and escalate — do **not** fabricate credentials or DNS.

---

## Preconditions

| Need | Check | If missing |
|------|-------|-----------|
| Cluster reachable | `kubectl get nodes` shows Ready | fix `KUBECONFIG` (`$HOME/.kube/homelab.yaml`), re-run `scripts/fetch-kubeconfig.sh homelab-a` |
| Image `sse-logs:homelab` in the node's containerd | see **Step 2** (apply, watch for `ErrImageNeverPull`) | **escalate** — needs host `docker`+`orb`, not kube (see box below) |
| Tunnel Secret `cloudflared-credentials` (Phase 2 only) | `kubectl get secret cloudflared-credentials -n edge` | **escalate** — needs Cloudflare login (Phase 2 box) |

---

## Phase 1 — deploy the app (pure kube, fully verifiable)

```bash
export KUBECONFIG="${KUBECONFIG:-$HOME/.kube/homelab.yaml}"

# 1. context sanity
kubectl get nodes
kubectl config current-context

# 2. apply just the app objects from the bundle (namespaces + Deployment + Service)
#    (applying the whole file is fine too — cloudflared will simply wait for its
#     Secret; see Phase 2. If you want app-only, this label selector is exact.)
kubectl apply -f sse-logs.apply.yaml

# 3. wait for rollout
kubectl -n sse-logs rollout status deploy/sse-logs --timeout=120s
kubectl -n sse-logs get pods -o wide
```

**Image-not-present signal:** if the pod shows `ErrImageNeverPull` /
`ImagePullBackOff`, the `sse-logs:homelab` image was never built+imported into
the cluster. `imagePullPolicy: IfNotPresent` + no registry means k3s expects it
already in containerd. **This step needs host access, not kube** — escalate or
run on the Mac host:

```bash
docker build -t sse-logs:homelab ../../sse-logs
docker save sse-logs:homelab | orb -m homelab-a sudo k3s ctr images import -
kubectl -n sse-logs rollout restart deploy/sse-logs
```

### Verify Phase 1 (smoke test via port-forward)

```bash
kubectl -n sse-logs port-forward svc/sse-logs 8000:8000 >/tmp/pf.log 2>&1 &
PF=$!; sleep 2

curl -s -o /dev/null -w "index: http %{http_code}\n" http://127.0.0.1:8000/
ID=$(curl -s -X POST http://127.0.0.1:8000/deployments | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "deployment id: $ID"
curl -s -N --max-time 5 "http://127.0.0.1:8000/deployments/$ID/stream" | head -4

kill $PF
```

**Pass =** index returns `http 200`, POST returns an id, and the stream emits
`data: ... [INFO] ...` lines. At this point the app is healthy in-cluster.

---

## Phase 2 — publish it publicly (needs Cloudflare credentials)

> ⚠️ **Cannot be done with kube access alone.** Creating the tunnel requires a
> `cloudflared tunnel login` against the owner's Cloudflare account and a domain.
> If you don't have that, stop here and report Phase 1 done — ask the owner to
> run `scripts/setup-tunnel.sh` (it mints the Secret + routes DNS).

Once the Secret `cloudflared-credentials` exists in namespace `edge`:

```bash
# the bundle already includes the edge ConfigMap + Deployment
kubectl apply -f sse-logs.apply.yaml
kubectl -n edge rollout status deploy/cloudflared --timeout=120s
kubectl -n edge get pods
```

If `cloudflared` is `CrashLoopBackOff`, the Secret is missing — that's expected
until Phase 2's prerequisites are met, **not** a bug in Phase 1.

### Verify Phase 2

```bash
curl -s -o /dev/null -w "public: http %{http_code}\n" https://sse.parashuramjoshi.in/
```

---

## Rollback

```bash
kubectl delete -f sse-logs.apply.yaml   # removes app + edge objects (Secrets untouched)
# or just the app:
kubectl delete namespace sse-logs
```

---

## Expected end state

| Namespace | Object | State |
|-----------|--------|-------|
| `sse-logs` | deploy/sse-logs (1/1), svc/sse-logs:8000 | Ready — always achievable with kube access |
| `edge` | deploy/cloudflared (2/2), configmap/cloudflared-config | Ready **only** after the Cloudflare Secret + DNS exist (Phase 2) |

## What to escalate, never guess

- Building/importing `sse-logs:homelab` (needs host `docker` + `orb`).
- `cloudflared tunnel login`, DNS routing for `sse.parashuramjoshi.in`, the credentials Secret.
- Any change to the ingress hostnames — these map to a real domain the owner controls.
