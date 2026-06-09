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

<!-- Add a row per onboarded project. Suggested next assignments:
| auth-service     | auth_service     | auth_service_user     | 2 | —              | —                    |
| hashtag-service  | hashtag_service  | hashtag_service_user  | 3 | hashtag.       | hashtag-service-media |
| video-processing | video_processing | video_processing_user | 4 | video.         | video-processing-media |
-->

## Notes / exceptions

- **Redis eviction policy:** the shared Redis runs `noeviction`. g2-reviews'
  standalone compose used `allkeys-lru`. They behave the same until Redis fills;
  if a cache-heavy project needs LRU eviction, that's the design doc's documented
  reason to split it onto its own Redis instance (eviction policy is instance-wide).
- **Schema loading:** `bootstrap-project.sh` creates an *empty* database. Each
  project still owns its schema/migrations — load them into the project DB after
  bootstrap (e.g. g2-reviews: `migrations/init.sql`; auth-service: Alembic).
