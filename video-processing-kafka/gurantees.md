# Guarantees (Video Processing Kafka)

This document describes the delivery, ordering, and dead-letter handling behavior in
the current `video-processing-kafka` codebase.

## Delivery guarantees

- Kafka consumption uses `enable_auto_commit=True`, so offsets are committed automatically
  as messages are polled. There is no explicit "process then commit" logic.
- Task execution is done by Celery (`apply_async`), with retries enabled.
- Result: the system behaves as **at-least-once** for tasks (retries) and can be
  **at-most-once** for Kafka consumption in the crash window between poll and handler
  completion.

## Ordering guarantees

- Kafka ordering is per partition. There is no cross-partition ordering.
- The upload topic is consumed by a single consumer group (`video-upload`) in one thread,
  so ordering is whatever Kafka provides per partition.
- The transcript topic fans out to three different consumer groups
  (`video-summary`, `video-bullets`, `video-action-items`), so there is no ordering
  across those groups; tasks run in parallel and can complete in any order.

## Dead-letter handling

- Failed Celery tasks are retried up to 3 times with exponential backoff.
- After retries are exhausted, `BaseTask.on_failure` publishes a message to the
  `video.dlq` Kafka topic with `task_id`, `task_name`, `error`, and `trace_id`.
- There is no consumer for `video.dlq` in this repo; it is a sink unless you add one.
