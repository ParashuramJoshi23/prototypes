# Remote Locks — Redis EVAL + Lua

A distributed mutex on top of Redis. Acquire is `SET key token NX PX ttl`.
Release is a Lua script run via `EVAL` that checks the holder token before deleting.

## Why Lua for release

The naive release is two round-trips:

```
GET key                  → "abc"          # is it still mine?
DEL key                                    # yes — drop it
```

Between those two calls the lock can expire and be re-acquired by someone else,
and the original caller would then `DEL` the new owner's lock. The fix is to do
the check-and-delete atomically inside Redis:

```lua
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
```

`EVAL` runs the script atomically — no other command can interleave. Same trick
for `Extend` (renew TTL only if we still hold it).

Acquire doesn't need Lua because `SET ... NX PX` is already a single atomic command.

## Setup

```bash
docker run --rm -p 6379:6379 redis:7-alpine
```

## Run

```bash
go run .
```

## What the demos show

1. **Mutual exclusion** — 10 goroutines race for the same key; only one holds at any time.
2. **TTL expiry** — holder "crashes" without releasing; lock auto-frees so a new holder can claim it.
3. **Stale release rejected** — A's TTL expires and B acquires the lock; A's later
   `Release()` must *not* delete B's lock. The Lua token check is what enforces this.

## Caveats

This is a **single-node** lock — fine for fencing in-process work, not safe across
Redis failover. For multi-node correctness see Redlock, or use a system designed
for it (etcd, ZooKeeper, Postgres advisory locks).
