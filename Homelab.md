# Homelab k3s Cluster — Design Doc

> Context handoff for Claude Code. This captures architecture decisions for a
> personal k3s cluster used to run prototypes and side projects. Goal is a
> homelab that doubles as hands-on k8s practice transferable to production work.

## Hardware

- 2× Mac Mini, 16GB RAM each
- OrbStack for containers (dynamic VM memory allocation — idle containers release RAM)
- Both machines on the same Tailscale tailnet (flat network, address each other by tailnet IP)

## Core decision: shared infrastructure, logical separation

Run **one shared instance** of each backing store across the cluster, with
**logical isolation per project** — NOT a dedicated instance per project.

Rationale: JVM-based stores (Kafka, Elasticsearch) pay a fixed ~1GB+ heap cost
the moment they start, idle or not. Per-project instances would multiply that
fixed tax and exhaust 2×16GB fast. Sharing amortizes the overhead; pay the
Kafka/ES tax once.

The hard rule: **share the instance, never share the data.** Sharing a server
process across projects is healthy multi-tenancy. Sharing a *schema/tables*
across projects is the distributed-monolith antipattern. Avoid the latter.

### Per-technology isolation strategy

| Store         | Shared unit      | Per-project isolation        | Production norm this mirrors |
|---------------|------------------|------------------------------|------------------------------|
| PostgreSQL    | one server       | database-per-project + role  | RDS hosting many DBs         |
| Kafka         | one cluster      | topic naming (`projA.orders`)| MSK topic multitenancy       |
| Elasticsearch | one cluster      | index-per-project            | shared cluster, many indices |
| Redis         | one instance     | logical DB (0–15) or prefix  | shared cache, key namespacing|

Redis exception: split into a dedicated instance only if a project needs a
**different eviction policy** (e.g. `allkeys-lru` cache vs. durable store) —
those conflict at the instance level.

### Explicitly NOT doing now

- Per-application dedicated DB/Kafka/ES/Redis instances — too heavy for the RAM budget.
- Blast-radius isolation / per-service-database StatefulSet exercise — not a
  requirement for prototypes. May revisit if a project gets real users.

## PostgreSQL setup

Single shared instance. Separate each project by **database + dedicated role**
(not just schema). Cheap boundary that prevents an 11pm mishap on project B from
clobbering project A. Per project, on spin-up:

```sql
CREATE DATABASE projecta;
CREATE USER projecta_user WITH PASSWORD '...';
GRANT ALL PRIVILEGES ON DATABASE projecta TO projecta_user;
```

All projects point at the same host (`postgres.platform.svc.cluster.local:5432`);
only dbname + credentials in the connection string change per project.

## Orchestration: k3s (chosen over Docker Swarm)

Why k3s over Swarm: Swarm pools the machines faster with fewer new concepts, but
it's in maintenance mode. k3s is full Kubernetes (lightweight Rancher repackage,
~512MB–1GB control-plane overhead, viable on a 16GB mini) and gives real
`kubectl`/Deployments/StatefulSets/Helm — the exact model asked about in senior
backend interviews and used in production. The k3s **operational layer** is the
transferable skill; the sharing topology is environment-specific.

### Cluster topology (2 nodes)

- Node count is below Raft quorum comfort (Raft wants odd: 1 or 3, not 2).
  Run a **single server/manager node**; second mini joins as agent. No control-plane
  HA — acceptable for a homelab. (Same quorum/split-brain logic as Redis Cluster / KRaft.)

### Namespace layout

- `platform` namespace — shared backing stores (Postgres, Kafka, ES, Redis).
- One namespace **per project** — app pods + sidecars.
- Cross-namespace DNS for wiring: `postgres.platform.svc.cluster.local:5432`,
  `kafka.platform.svc.cluster.local:9092`, etc.
- Namespace = tenant boundary → gives per-project RBAC + resource quotas cheaply,
  and maps onto how real k8s shops separate teams/environments.

### Stateful vs. stateless placement

The hard part of any orchestrator is stateful workloads — data on disk is tied
to a machine, and there's no shared SAN in a 2-mini homelab.

- **StatefulSets, pinned to a node via local volumes / node affinity:** Postgres,
  Kafka, Elasticsearch, Redis. (Pinning the data layer is effectively manual
  placement — that's expected and correct here.)
- **Deployments, scheduler places freely:** all stateless app pods + sidecars.

So pooling buys the most for the app tier and the least for the data tier.

### Memory-placement guidance (the bin-packing problem)

Keep the two ~1GB+ JVM tenants (**Kafka and Elasticsearch**) on **separate
minis** — biggest single win, since they're the ones that misbehave under
pressure. Rough idle footprints to budget against (~11–12GB usable per mini
after macOS):

- Postgres ~500MB–1GB · Kafka (JVM) ~1GB+ · Elasticsearch ~1GB+ heap · Redis ~100MB

### ES gotcha

Elasticsearch autosizes heap to a fraction of *detected* RAM and may detect the
full 16GB inside OrbStack and over-grab. Pin it explicitly:

```
ES_JAVA_OPTS=-Xms1g -Xmx1g
```

## Suggested next steps for Claude Code

1. Install k3s: server on Mini A, agent join on Mini B (over tailnet IP).
2. Create `platform` namespace + the four backing-store manifests
   (Postgres/Kafka/ES/Redis as StatefulSets, pinned, with PVCs on local-path).
3. Add a per-project namespace template + the bootstrap SQL above.
4. Wire a sample app pod to Postgres via cross-namespace DNS to validate.
5. Set `--memory`-equivalent resource requests/limits so no tenant starves the rest.
