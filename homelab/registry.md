# Platform tenant registry

The shared stores are one instance each; projects are isolated *logically*.
This table is the source of truth for those logical assignments — keep it
collision-free (especially Redis DB indices: only 0–15 exist).

> Rule: **share the instance, never the data.** A project never reads another
> project's database / index / topic-prefix / bucket.

| Project      | PG database  | PG role           | Redis db | Kafka prefix | S3 bucket          | Notes |
|--------------|--------------|-------------------|----------|--------------|--------------------|-------|
| _platform_   | postgres     | postgres (super)  | —        | —            | —                  | admin only; used by bootstrap |
| g2-reviews   | g2_reviews   | g2_reviews_user   | 1        | —            | —                  | PG + Redis only |
| n8n          | n8n          | n8n_user          | 5*       | —            | n8n-media*         | regular mode (PG only); *redis/bucket reserved, unused until queue/S3 mode. Has its own `N8N_ENCRYPTION_KEY` in `n8n-secrets`. |
| sse-logs     | —            | —                 | —        | —            | —                  | store-less Flask/SSE demo — no `bootstrap-project.sh` run, no Secret. Published publicly at `sse.parashuramjoshi.in` via the `edge` tunnel. |

<!-- Add a row per onboarded project. Suggested next assignments:
| auth-service     | auth_service     | auth_service_user     | 2 | —              | —                    |
| hashtag-service  | hashtag_service  | hashtag_service_user  | 3 | hashtag.       | hashtag-service-media |
| video-processing | video_processing | video_processing_user | 4 | video.         | video-processing-media |
-->

## Public exposure

Most projects are reached privately via `scripts/forward.sh` (port-forward).
Projects meant to be **publicly embeddable** (e.g. live blog demos) are published
through the shared Cloudflare Tunnel in [`edge/`](edge/README.md) — one hostname
per project, mapped to its ClusterIP Service. `sse-logs` is the first; add an
ingress rule + DNS route per project as documented there.

## Notes / exceptions

- **Redis eviction policy:** the shared Redis runs `noeviction`. g2-reviews'
  standalone compose used `allkeys-lru`. They behave the same until Redis fills;
  if a cache-heavy project needs LRU eviction, that's the design doc's documented
  reason to split it onto its own Redis instance (eviction policy is instance-wide).
- **Schema loading:** `bootstrap-project.sh` creates an *empty* database. Each
  project still owns its schema/migrations — load them into the project DB after
  bootstrap (e.g. g2-reviews: `migrations/init.sql`; auth-service: Alembic).
