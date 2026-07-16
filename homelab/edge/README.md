# edge — public exposure via Cloudflare Tunnel

The one place the homelab reaches the public internet. Everything else stays
ClusterIP-private; this layer publishes selected prototypes (e.g. to embed as
live demos in a blog) through a single Cloudflare Tunnel.

```
   visitor's browser                Cloudflare edge              your cluster (edge ns)
 ┌──────────────────┐   HTTPS    ┌────────────────┐   tunnel   ┌────────────────────┐
 │ blog <iframe>    │──────────▶ │ parashuramjoshi│◀──────────▶│ cloudflared (×2)   │
 │ sse.parashuram.. │            │  .in (TLS, WAF,│  outbound  │  ingress map ──▶   │
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

Prerequisite: the **`parashuramjoshi.in` zone must be on Cloudflare** (its
nameservers pointed at Cloudflare) so a DNS record for `sse.` can be created.
The main site can keep living wherever it does — only the `sse` record becomes a
tunnel CNAME; other records are untouched.

```bash
# prereqs on the Mac host
brew install cloudflared
cloudflared tunnel login            # authorize your Cloudflare account + the zone

# create the tunnel, mint the in-cluster Secret, route DNS for sse.parashuramjoshi.in
cd homelab
scripts/setup-tunnel.sh

# bring cloudflared up (ingress hostnames are already set to sse.parashuramjoshi.in)
export KUBECONFIG=$HOME/.kube/homelab.yaml
kubectl apply -k edge
kubectl -n edge rollout status deploy/cloudflared
```

`https://sse.parashuramjoshi.in` is now live.

## Publishing another prototype

1. Deploy it (`kubectl apply -k projects/<name>`) so its Service exists.
2. Add an ingress block to `edge/cloudflared.yaml`:
   ```yaml
   - hostname: <name>.parashuramjoshi.in
     service: http://<name>.<name>.svc.cluster.local:8000
   ```
   (keep the `http_status:404` catch-all last).
3. Add the hostname to the `PUBLISHED_HOSTS` array in `scripts/setup-tunnel.sh`
   and re-run it (routes the DNS), or route it manually:
   `cloudflared tunnel route dns homelab-demos <name>.parashuramjoshi.in`.
4. `kubectl apply -k edge && kubectl -n edge rollout restart deploy/cloudflared`.

## Embedding in a blog

The demos are plain web apps, so an `<iframe>` is all you need:

```html
<iframe
  src="https://sse.parashuramjoshi.in"
  title="Live deployment logs over Server-Sent Events"
  width="100%" height="560"
  style="border:1px solid #e5e7eb; border-radius:8px;"
  loading="lazy"
  sandbox="allow-scripts allow-same-origin">
</iframe>
```

To allow framing, the app must not send `X-Frame-Options: DENY`; sse-logs sends
no such header, so it frames fine. If you later add one, use a Cloudflare
Transform Rule to set `Content-Security-Policy: frame-ancestors https://parashuramjoshi.in`
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

## Operations: launch first, observe, then rate-limit

The origin here is a Mac Mini at home, so the "cost" of abuse is CPU/heat, not a
cloud bill. The plan is deliberately **launch without a rate limit, watch real
traffic, and only add the limit if volume warrants it** — adding it later is
dashboard config with zero downtime (no redeploy, no pod restart).

### Why launching un-limited is safe

- `sse-logs` serves **fake, read-only** data (Faker-generated logs) — no DB, no
  user data. Worst case is wasted CPU, not a breach.
- The container has a **hard concurrency ceiling**: gunicorn `2 workers × 16
  threads = 32` simultaneous streams. Beyond that, requests queue — the pod
  degrades, it doesn't melt.
- Cloudflare already fronts every request (baseline DDoS protection, TLS, bot
  filtering) even with no rate-limit rule, and the home IP stays hidden.

### Watch these signals

Cloudflare side (no setup, free):
- **Analytics & Logs → Traffic**, filtered to hostname `sse.parashuramjoshi.in`
  — requests over time.
- **Security → Events** — anything Cloudflare already flagged.

Cluster side:
```bash
kubectl -n sse-logs top pod            # live CPU/memory (needs metrics-server)
kubectl -n sse-logs get pod -w         # watch for restarts = it's being hammered
kubectl -n sse-logs logs deploy/sse-logs --tail=50
```

### Add the rate limit when ANY of these is true

- Sustained requests from a **single IP** looping the endpoint (bots/scrapers).
- Pod **CPU pinned at its limit**, or the pod restarting under load.
- You're about to embed it somewhere high-traffic and want a cap *before* the spike.

### The rule to add (Cloudflare dashboard, free plan includes one)

`parashuramjoshi.in` zone → **Security → Rate limiting rules → Create rule**:

| Field | Value |
|-------|-------|
| If incoming requests match | `Hostname equals sse.parashuramjoshi.in` |
| Rate | **30 requests per 10 seconds** |
| Counting characteristic | **Client IP** |
| Then | **Block** for 1 minute (or *Managed Challenge* for a softer response) |

A blog reader makes a handful of requests; a loop trips it instantly. This is
zone/account config — it is **not** in this repo and cannot be applied with
`kubectl`. A kube-access agent should surface the need (from the signals above)
and hand it to the owner, not attempt it.

> ⚠️ These prototypes hold no real data, so exposure risk is low — keep it that
> way: never route a store-backed or admin endpoint through this tunnel without
> authentication in front of it.
