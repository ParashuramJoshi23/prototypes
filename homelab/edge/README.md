# edge — public exposure via Cloudflare Tunnel

The one place the homelab reaches the public internet. Everything else stays
ClusterIP-private; this layer publishes selected prototypes (e.g. to embed as
live demos in a blog) through a single Cloudflare Tunnel.

```
   visitor's browser                Cloudflare edge              your cluster (edge ns)
 ┌──────────────────┐   HTTPS    ┌────────────────┐   tunnel   ┌────────────────────┐
 │ blog <iframe>    │──────────▶ │  demos.<you>   │◀──────────▶│ cloudflared (×2)   │
 │ sse-logs.demos.. │            │  (TLS, WAF,    │  outbound  │  ingress map ──▶   │
 └──────────────────┘            │   rate limit)  │   only     │  svc/sse-logs:8000 │
                                 └────────────────┘            └────────────────────┘
```

**Why a tunnel, not an Ingress.** This cluster runs with traefik + servicelb
disabled, behind a home router with no public IP. `cloudflared` runs *inside*
the cluster and dials *out* to Cloudflare, so no ports are opened, no home IP is
exposed, and TLS + rate limiting are handled at Cloudflare's edge. Each public
hostname maps to a cluster Service by its in-cluster DNS name.

## Files

| File | What it is |
|------|-----------|
| `namespace.yaml` | the `edge` tenant |
| `cloudflared.yaml` | ingress map (ConfigMap) + the cloudflared Deployment |
| `credentials.example.yaml` | shape of the tunnel Secret (the real one is created by the script, never committed) |
| `../scripts/setup-tunnel.sh` | creates the tunnel, mints the Secret, routes DNS |

> **Handing this to another agent?** [`../deploy/AGENT_APPLY.md`](../deploy/AGENT_APPLY.md)
> is a self-contained apply runbook + single-file bundle
> ([`../deploy/sse-logs.apply.yaml`](../deploy/sse-logs.apply.yaml)) that a
> kube-access agent can run top-to-bottom.

## One-time setup

```bash
# prereqs on the Mac host
brew install cloudflared
cloudflared tunnel login            # authorize your Cloudflare account + zone

# create the tunnel, mint the in-cluster Secret, route DNS for sse-logs
cd homelab
scripts/setup-tunnel.sh demos.example.com     # use your own domain

# point the ingress rules at your domain, then bring cloudflared up
#   (edit edge/cloudflared.yaml: replace demos.example.com)
export KUBECONFIG=$HOME/.kube/homelab.yaml
kubectl apply -k edge
kubectl -n edge rollout status deploy/cloudflared
```

`https://sse-logs.demos.example.com` is now live.

## Publishing another prototype

1. Deploy it (`kubectl apply -k projects/<name>`) so its Service exists.
2. Add an ingress block to `edge/cloudflared.yaml`:
   ```yaml
   - hostname: <name>.demos.example.com
     service: http://<name>.<name>.svc.cluster.local:8000
   ```
   (keep the `http_status:404` catch-all last).
3. Add the hostname to the `for host in ...` loop in `scripts/setup-tunnel.sh`
   and re-run it (routes the DNS), or route it manually:
   `cloudflared tunnel route dns homelab-demos <name>.demos.example.com`.
4. `kubectl apply -k edge && kubectl -n edge rollout restart deploy/cloudflared`.

## Embedding in a blog

The demos are plain web apps, so an `<iframe>` is all you need:

```html
<iframe
  src="https://sse-logs.demos.example.com"
  title="Live deployment logs over Server-Sent Events"
  width="100%" height="560"
  style="border:1px solid #e5e7eb; border-radius:8px;"
  loading="lazy"
  sandbox="allow-scripts allow-same-origin">
</iframe>
```

To allow framing, the app must not send `X-Frame-Options: DENY`; sse-logs sends
no such header, so it frames fine. If you later add one, use a Cloudflare
Transform Rule to set `Content-Security-Policy: frame-ancestors https://<your-blog>`
instead of a blanket deny.

## Notes on SSE through the tunnel

- Server-Sent Events are long-lived streaming responses. cloudflared streams
  them without buffering; the app already sends `Cache-Control: no-cache` and
  `X-Accel-Buffering: no`, and the container runs gunicorn with `--timeout 0`
  so the worker isn't recycled mid-stream.
- **sse-logs is single-replica on purpose.** A deployment's log file is written
  by the pod that received `POST /deployments`; the follow-up `GET /stream` must
  reach the same pod. Scaling to >1 replica would route some streams to a pod
  with no file. If you need HA, add a Cloudflare session-affinity / sticky rule,
  or move the log store to the shared Redis — but for a demo, one replica is right.

## Cost / safety

- Cloudflare Tunnel + a hobby domain: free tier is plenty for demo traffic.
- Put a **Cloudflare Rate Limiting rule** on `*.demos.example.com` (e.g. 30 req/10s
  per IP) so an embedded demo can't be hammered into running up your home power.
- These prototypes hold no real data (sse-logs generates fake logs), so exposure
  risk is low — but keep it that way: never route a store-backed admin endpoint
  through this tunnel without auth in front.
