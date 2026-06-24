# temporal-ecommerce-workflow (homelab deployment)

Runs the [`temporal-ecommerce-workflow`](../../../temporal-ecommerce-workflow)
prototype on the k3s cluster.

## How this one differs from the other homelab projects

Most prototypes here are stateless apps that point at the **shared** platform
stores (Postgres/Redis/Kafka/S3). This one is different:

- It uses **no shared platform store**. Temporal needs its own server, so this
  project runs a **self-contained Temporal dev server** (`temporalio/temporal
  server start-dev`, sqlite-backed) inside its own namespace — mirroring the
  prototype's `docker-compose.yml`.
- Therefore there is **no `bootstrap-project.sh` step**, no Postgres db/role, no
  Secret, and **no `registry.md` row** (it claims no shared-store slice).
- The app tier is a **worker** (polls the task queue; no HTTP Service) plus a
  one-shot **starter Job** (fires the demo), not a web service on `:8000`.

> Future option: if a second project ever needs Temporal, promote it to a shared
> `platform/temporal.yaml` store (one server, namespace-per-project isolation)
> exactly like Postgres/Kafka — same "share the instance, never the data" rule.
> Not worth it for a single prototype.

## Components

| Manifest | What it runs |
|---|---|
| `temporal.yaml` | Temporal dev server (gRPC `:7233`, Web UI `:8233`) + PVC for durable history |
| `worker.yaml` | The worker Deployment (runs workflow + activity code) |
| `starter.yaml` | One-shot Job that submits the sample order (applied separately) |
| `configmap.yaml` | `TEMPORAL_ADDRESS=temporal:7233` (the only wiring needed) |

## Deploy

From the Mac host, with the cluster up (`export KUBECONFIG=$HOME/.kube/homelab.yaml`):

```bash
cd homelab

# 1. build the prototype image into the VM's containerd (no registry needed)
docker build -t temporal-ecommerce-workflow:homelab ../temporal-ecommerce-workflow
docker save temporal-ecommerce-workflow:homelab | orb -m homelab-a sudo k3s ctr images import -

# 2. bring up Temporal + the worker
kubectl apply -k projects/temporal-ecommerce-workflow
kubectl get pods -n temporal-ecommerce-workflow -w   # wait for temporal + worker Running

# 3. fire the demo order
kubectl apply -f projects/temporal-ecommerce-workflow/starter.yaml
kubectl wait --for=condition=complete job/order-starter \
  -n temporal-ecommerce-workflow --timeout=120s

# 4. see the structured result
kubectl logs -n temporal-ecommerce-workflow job/order-starter
```

Expected tail of the starter logs:

```json
{
  "order_id": "ORD-1001",
  "inventory_status": "reserved",
  "payment_status": "paid",
  "payment_attempts": 2,
  "confirmation_status": "sent",
  "workflow_status": "COMPLETED",
  "summary": "Order ORD-1001 fulfilled: ... payment paid in 2 attempt(s) (payment recovered after a transient failure) ..."
}
```

`payment_attempts: 2` is the proof Temporal retried the failed payment and recovered.

## Watch it in the Temporal Web UI

`forward.sh` assumes `svc == project name`, which doesn't fit here (the Service
is `temporal`), so port-forward the UI directly:

```bash
kubectl port-forward -n temporal-ecommerce-workflow svc/temporal 8233:8233
# open http://localhost:8233  -> Workflows -> order-ORD-1001
```

In the workflow's event history you can see `ProcessPayment` fail on attempt 1
(`PaymentServiceError`) and succeed on the retry.

## Observe recovery (optional)

The worker is durable: kill it mid-run and Temporal replays from history on the
restarted pod.

```bash
# re-run the demo and immediately bounce the worker
kubectl delete job order-starter -n temporal-ecommerce-workflow --ignore-not-found
kubectl apply -f projects/temporal-ecommerce-workflow/starter.yaml
kubectl delete pod -n temporal-ecommerce-workflow -l app=worker   # force a restart
```

The workflow still completes with `workflow_status: COMPLETED` — no work is lost,
because state lives in Temporal (persisted to the PVC), not in the worker pod.

## Re-run the demo

A Job's pod template is immutable, so delete before re-applying:

```bash
kubectl delete job order-starter -n temporal-ecommerce-workflow --ignore-not-found
kubectl apply -f projects/temporal-ecommerce-workflow/starter.yaml
```

## Tear down

```bash
kubectl delete -k projects/temporal-ecommerce-workflow
kubectl delete -f projects/temporal-ecommerce-workflow/starter.yaml --ignore-not-found
# the PVC is retained by default; remove it to wipe Temporal history:
kubectl delete pvc temporal-data -n temporal-ecommerce-workflow
```
