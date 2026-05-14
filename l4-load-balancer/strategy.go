package main

import (
	"math/rand"
	"sync"
	"sync/atomic"
)

// Strategy picks one backend for each new client connection. Implementations
// must be safe for concurrent use because Select is called from many
// goroutines at once.
type Strategy interface {
	Select(backends []*Backend) *Backend
}

// Backend represents an upstream server. The active counter is incremented
// by the load balancer when a connection starts and decremented when it
// ends, so LeastConnections can read it without locking.
type Backend struct {
	Addr   string
	active int64
}

func (b *Backend) Active() int64 { return atomic.LoadInt64(&b.active) }
func (b *Backend) Inc()           { atomic.AddInt64(&b.active, 1) }
func (b *Backend) Dec()           { atomic.AddInt64(&b.active, -1) }

// RoundRobin distributes connections in order across the backends.
type RoundRobin struct{ next uint64 }

func (r *RoundRobin) Select(backends []*Backend) *Backend {
	i := atomic.AddUint64(&r.next, 1) - 1
	return backends[i%uint64(len(backends))]
}

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

// LeastConnections picks the backend with the fewest in-flight connections.
// Ties are broken by index order.
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
