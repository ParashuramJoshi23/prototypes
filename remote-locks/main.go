// Redis distributed lock — acquire with SET NX PX, release/extend via EVAL+Lua.
//
// Why Lua for release:
//   A naive "if GET == token then DEL" done in two round-trips has a TOCTOU bug —
//   the lock can expire and a different holder can claim it between GET and DEL,
//   and the original caller would then delete the new owner's lock.
//   EVAL runs the script atomically inside Redis, so the check-and-delete is one step.
//
// Run a Redis first:  docker run --rm -p 6379:6379 redis:7-alpine
package main

import (
	"context"
	"crypto/rand"
	"encoding/hex"
	"errors"
	"fmt"
	"sync"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"
)

// ─────────────────────────────────────────────────────────────
// Lock implementation
// ─────────────────────────────────────────────────────────────

const releaseScript = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
else
    return 0
end
`

const extendScript = `
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("PEXPIRE", KEYS[1], ARGV[2])
else
    return 0
end
`

var (
	releaseLua = redis.NewScript(releaseScript)
	extendLua  = redis.NewScript(extendScript)
)

var ErrNotHeld = errors.New("lock not held by this caller")

type Lock struct {
	rdb   *redis.Client
	key   string
	token string
	ttl   time.Duration
}

// Acquire tries once. Returns (nil, nil) if someone else currently holds the key.
// The TTL is the safety net: if the holder dies, the lock auto-frees after this duration.
func Acquire(ctx context.Context, rdb *redis.Client, key string, ttl time.Duration) (*Lock, error) {
	token := newToken()
	ok, err := rdb.SetNX(ctx, key, token, ttl).Result()
	if err != nil {
		return nil, err
	}
	if !ok {
		return nil, nil
	}
	return &Lock{rdb: rdb, key: key, token: token, ttl: ttl}, nil
}

// Release runs the Lua script via EVAL: deletes the key only if the value
// still matches our token. Returns ErrNotHeld if the lock was already taken
// by someone else (e.g. our TTL expired).
func (l *Lock) Release(ctx context.Context) error {
	res, err := releaseLua.Run(ctx, l.rdb, []string{l.key}, l.token).Int64()
	if err != nil {
		return err
	}
	if res == 0 {
		return ErrNotHeld
	}
	return nil
}

// Extend pushes the TTL out by another `l.ttl`, but only if we still own the key.
func (l *Lock) Extend(ctx context.Context) error {
	res, err := extendLua.Run(ctx, l.rdb, []string{l.key}, l.token, l.ttl.Milliseconds()).Int64()
	if err != nil {
		return err
	}
	if res == 0 {
		return ErrNotHeld
	}
	return nil
}

func (l *Lock) Token() string { return l.token }

func newToken() string {
	b := make([]byte, 16)
	_, _ = rand.Read(b)
	return hex.EncodeToString(b)
}

// ─────────────────────────────────────────────────────────────
// Demo
// ─────────────────────────────────────────────────────────────

const (
	addr     = "localhost:6379"
	lockKey  = "demo:lock"
	lockTTL  = 2 * time.Second
	workers  = 10
	workTime = 200 * time.Millisecond
)

func main() {
	rdb := redis.NewClient(&redis.Options{Addr: addr})
	defer rdb.Close()

	ctx := context.Background()
	if err := rdb.Ping(ctx).Err(); err != nil {
		fmt.Printf("Redis at %s not reachable: %v\n", addr, err)
		fmt.Println("Start one with:  docker run --rm -p 6379:6379 redis:7-alpine")
		return
	}
	rdb.Del(ctx, lockKey)

	demoMutualExclusion(ctx, rdb)
	demoExpiry(ctx, rdb)
	demoStaleRelease(ctx, rdb)
}

// 1. Mutual exclusion — N goroutines fight for the same key, only one inside at a time.
func demoMutualExclusion(ctx context.Context, rdb *redis.Client) {
	fmt.Println("\n=== 1. Mutual exclusion ===")
	fmt.Printf("%d goroutines spin trying to grab the same lock; only one holds at a time.\n", workers)

	var wg sync.WaitGroup
	var inCritical, maxConcurrent int32

	start := time.Now()
	for i := range workers {
		wg.Add(1)
		go func(id int) {
			defer wg.Done()
			for {
				lock, err := Acquire(ctx, rdb, lockKey, lockTTL)
				if err != nil {
					fmt.Printf("  W%02d: acquire error: %v\n", id, err)
					return
				}
				if lock == nil {
					time.Sleep(20 * time.Millisecond) // someone else holds it; back off
					continue
				}

				cur := atomic.AddInt32(&inCritical, 1)
				for {
					m := atomic.LoadInt32(&maxConcurrent)
					if cur <= m || atomic.CompareAndSwapInt32(&maxConcurrent, m, cur) {
						break
					}
				}
				fmt.Printf("  W%02d: held lock\n", id)
				time.Sleep(workTime)
				atomic.AddInt32(&inCritical, -1)

				if err := lock.Release(ctx); err != nil {
					fmt.Printf("  W%02d: release error: %v\n", id, err)
				}
				return
			}
		}(i)
	}
	wg.Wait()

	fmt.Printf("Done in %s; max concurrent holders observed: %d (expect 1)\n",
		time.Since(start).Round(time.Millisecond), maxConcurrent)
}

// 2. TTL expiry — holder "crashes"; lock auto-frees so a new holder can claim it.
func demoExpiry(ctx context.Context, rdb *redis.Client) {
	fmt.Println("\n=== 2. TTL expiry ===")
	fmt.Println("Holder 'crashes' without releasing; lock auto-frees after TTL.")

	rdb.Del(ctx, lockKey)
	lock, _ := Acquire(ctx, rdb, lockKey, 500*time.Millisecond)
	if lock == nil {
		fmt.Println("  unexpected: could not grab fresh lock")
		return
	}
	fmt.Println("  W1: acquired (TTL 500ms), then 'crashed' (no release)")

	for i := range 8 {
		l, _ := Acquire(ctx, rdb, lockKey, 500*time.Millisecond)
		if l != nil {
			fmt.Printf("  W2: acquired after ~%dms (TTL kicked in)\n", (i+1)*100)
			_ = l.Release(ctx)
			return
		}
		time.Sleep(100 * time.Millisecond)
	}
	fmt.Println("  W2: never got the lock")
}

// 3. Stale release — A's TTL expires and B grabs the lock. A's Release() must NOT
//    delete B's lock — the Lua token check is what enforces this.
func demoStaleRelease(ctx context.Context, rdb *redis.Client) {
	fmt.Println("\n=== 3. Stale release rejected ===")
	fmt.Println("A's TTL expires → B acquires → A.Release() must NOT delete B's lock.")

	rdb.Del(ctx, lockKey)
	lockA, _ := Acquire(ctx, rdb, lockKey, 200*time.Millisecond)
	fmt.Println("  A: acquired (TTL 200ms)")

	time.Sleep(300 * time.Millisecond)
	lockB, _ := Acquire(ctx, rdb, lockKey, 2*time.Second)
	if lockB == nil {
		fmt.Println("  B: unexpected — A's lock should have expired")
		return
	}
	fmt.Println("  B: acquired (A's TTL had expired)")

	switch err := lockA.Release(ctx); err {
	case ErrNotHeld:
		fmt.Println("  A.Release(): refused — token mismatch caught by Lua, B's lock survives")
	case nil:
		fmt.Println("  A.Release(): WRONG — A just nuked B's lock")
	default:
		fmt.Printf("  A.Release(): %v\n", err)
	}

	val, _ := rdb.Get(ctx, lockKey).Result()
	fmt.Printf("  Key still holds B's token: %v\n", val == lockB.Token())
	_ = lockB.Release(ctx)
}
