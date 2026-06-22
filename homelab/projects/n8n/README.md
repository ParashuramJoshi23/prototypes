# n8n

Workflow automation, running in **regular mode** on the homelab k3s cluster,
backed by shared Postgres (db `n8n`). Deployed from the public `n8nio/n8n` image
(no local build).

## Access

**Tailnet URL (stable, HTTPS, any device): https://homelab-a.tailbe4cd1.ts.net**

First visit prompts you to create the owner account. Reachable from any device on
the tailnet (incl. phone). Local fallback: `../../scripts/forward.sh n8n 5678`.

## How the tailnet exposure is wired

```
device on tailnet ──HTTPS──▶ tailscale serve (in homelab-a VM)
                                   │ proxies to
                                   ▼
                          NodePort 30678 (k3s) ──▶ n8n pod :5678
```

- The Service is `type: NodePort` (port **30678**) so the VM host can reach n8n.
- Tailscale runs **inside the VM**; `tailscale serve` terminates TLS and proxies
  to `http://127.0.0.1:30678`. n8n speaks plain http on 5678 in-pod.
- `N8N_PROTOCOL/N8N_HOST/WEBHOOK_URL` point at the tailnet hostname;
  `N8N_SECURE_COOKIE=true` (safe now that it's real HTTPS).

### Re-establish after a VM rebuild
The `tailscale up` auth and `serve` config live in the VM's tailscaled state, not
in git. If the VM is ever recreated:

```bash
orb -m homelab-a sudo tailscale up --hostname=homelab-a --accept-dns=false
orb -m homelab-a sudo tailscale serve --bg http://127.0.0.1:30678
```

To stop exposing it: `orb -m homelab-a sudo tailscale serve --https=443 off`.

### macOS DNS note (this Mac)
The Mac host runs the **headless Homebrew tailscaled** (system daemon, for
unattended boot). That variant lacks the GUI app's NetworkExtension, so **MagicDNS
doesn't resolve `*.ts.net` on this Mac**. Worked around with an `/etc/hosts` line:

```
100.91.12.31  homelab-a.tailbe4cd1.ts.net
```

`100.91.12.31` is homelab-a's tailnet IP — stable across reboots. **Only** update
it if the VM's Tailscale node is deleted/recreated (a fresh `tailscale up` =>
new IP). Phones/other devices using the Tailscale app resolve the name natively
(no hosts entry needed).

## Data & secrets

- Workflows/credentials/executions live in shared Postgres (db `n8n`, ~108 tables).
- Credentials are encrypted with `N8N_ENCRYPTION_KEY` (in Secret `n8n-secrets`,
  alongside `DB_POSTGRESDB_PASSWORD`). Keep this key — losing it orphans all saved
  credentials. The `.n8n` dir is an ephemeral emptyDir; core data is in Postgres.

## Scaling later (queue mode)
Regular mode = single pod, no Redis. For concurrency, switch to queue mode:
`EXECUTIONS_MODE=queue` + shared Redis (db index 5, reserved in `registry.md`) +
a separate worker Deployment. External webhooks need `tailscale funnel` (public)
instead of `serve` (tailnet-only).
