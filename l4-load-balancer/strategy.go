package main

import (
	"math/rand"
	"sync"
	"sync/atomic"
)

// Strategy picks one backend address from the pool for each new client
// connection. Implementations must be safe for concurrent use because the
// load balancer calls Select from many goroutines at once.
type Strategy interface {
	Select(backends []*Backend) *Backend
	Release(b *Backend) // called when a connection ends; only meaningful for stateful strategies
}

// Backend represents an upstream server. The active counter is updated
// atomically by the load balancer (and by LeastConnections) to enable
// connection-aware strategies without taking a lock on the hot path.
type Backend struct {
	Addr   string
	active int64
}

func (b *Backend) Active() int64 { return atomic.LoadInt64(&b.active) }
func (b *Backend) Inc()           { atomic.AddInt64(&b.active, 1) }
func (b *Backend) Dec()           { atomic.AddInt64(&b.active, -1) }

// RoundRobin distributes connections in order across the backends.
type RoundRobin struct {
	next uint64
}

func (r *RoundRobin) Select(backends []*Backend) *Backend {
	i := atomic.AddUint64(&r.next, 1) - 1
	return backends[i%uint64(len(backends))]
}

func (r *RoundRobin) Release(_ *Backend) {}

// Random picks a uniformly random backend on every call.
type Random struct {
	mu  sync.Mutex
	rng *rand.Rand
}

func NewRandom(seed int64) *Random {
	return &Random{rng: rand.New(rand.NewSource(seed))}
}

func (r *Random) Select(backends []*Backend) *Backend {
	r.mu.Lock()
	i := r.rng.Intn(len(backends))
	r.mu.Unlock()
	return backends[i]
}

func (r *Random) Release(_ *Backend) {}

// LeastConnections picks the backend with the fewest in-flight connections.
// Ties are broken by index order. The caller is responsible for incrementing
// the backend's active counter before use and calling Release when done.
type LeastConnections struct{}

func (LeastConnections) Select(backends []*Backend) *Backend {
	best := backends[0]
	bestN := best.Active()
	for _, b := range backends[1:] {
		if n := b.Active(); n < bestN {
			best, bestN = b, n
		}
	}
	return best
}

func (LeastConnections) Release(_ *Backend) {}
