package main

import (
	"fmt"
	"io"
	"log"
	"net"
	"strings"
	"sync"
	"sync/atomic"
	"time"
)

// LB is the load balancer state machine. It only routes traffic when isLeader=1.
// Backend membership is mutated via apply(), which is driven by the Raft commit path.
type LB struct {
	mu       sync.RWMutex
	backends []*backend
	next     uint64   // round-robin counter
	isLeader int32    // 1 when this node is the Raft leader
	listener net.Listener
}

type backend struct {
	addr   string
	active int64
}

func (b *backend) inc() { atomic.AddInt64(&b.active, 1) }
func (b *backend) dec() { atomic.AddInt64(&b.active, -1) }

func newLB(addrs []string) *LB {
	lb := &LB{}
	for _, a := range addrs {
		lb.backends = append(lb.backends, &backend{addr: a})
	}
	return lb
}

// setLeader toggles whether this node actively accepts LB connections.
func (lb *LB) setLeader(v bool) {
	if v {
		atomic.StoreInt32(&lb.isLeader, 1)
	} else {
		atomic.StoreInt32(&lb.isLeader, 0)
	}
}

// apply executes a committed Raft log command against the LB state.
// Commands: "add:<addr>" or "remove:<addr>"
func (lb *LB) apply(cmd string) {
	parts := strings.SplitN(cmd, ":", 2)
	if len(parts) != 2 {
		log.Printf("[lb] unknown command: %q", cmd)
		return
	}
	op, addr := parts[0], parts[1]
	lb.mu.Lock()
	defer lb.mu.Unlock()
	switch op {
	case "add":
		for _, b := range lb.backends {
			if b.addr == addr {
				log.Printf("[lb] backend already present: %s", addr)
				return
			}
		}
		lb.backends = append(lb.backends, &backend{addr: addr})
		log.Printf("[lb] added backend: %s (total=%d)", addr, len(lb.backends))
	case "remove":
		for i, b := range lb.backends {
			if b.addr == addr {
				lb.backends = append(lb.backends[:i], lb.backends[i+1:]...)
				log.Printf("[lb] removed backend: %s (total=%d)", addr, len(lb.backends))
				return
			}
		}
		log.Printf("[lb] backend not found: %s", addr)
	default:
		log.Printf("[lb] unknown op: %q", op)
	}
}

// backendList returns a snapshot of current backend addresses (for status API).
func (lb *LB) backendList() []string {
	lb.mu.RLock()
	defer lb.mu.RUnlock()
	out := make([]string, len(lb.backends))
	for i, b := range lb.backends {
		out[i] = fmt.Sprintf("%s (active=%d)", b.addr, atomic.LoadInt64(&b.active))
	}
	return out
}

// pick returns the next backend using round-robin, or nil if none available.
func (lb *LB) pick() *backend {
	lb.mu.RLock()
	defer lb.mu.RUnlock()
	if len(lb.backends) == 0 {
		return nil
	}
	i := atomic.AddUint64(&lb.next, 1) - 1
	return lb.backends[i%uint64(len(lb.backends))]
}

// listenAndServe opens a TCP listener and handles connections.
// Connections are rejected (RST) if this node is not the current leader.
func (lb *LB) listenAndServe(addr string) error {
	ln, err := net.Listen("tcp", addr)
	if err != nil {
		return err
	}
	lb.listener = ln
	log.Printf("[lb] TCP listener on %s", addr)
	for {
		conn, err := ln.Accept()
		if err != nil {
			return err
		}
		if atomic.LoadInt32(&lb.isLeader) == 0 {
			// Not the leader — refuse connection immediately.
			conn.Close()
			continue
		}
		go lb.handle(conn)
	}
}

func (lb *LB) handle(client net.Conn) {
	defer client.Close()

	b := lb.pick()
	if b == nil {
		log.Printf("[lb] no backends available")
		return
	}
	b.inc()
	defer b.dec()

	upstream, err := net.DialTimeout("tcp", b.addr, 2*time.Second)
	if err != nil {
		log.Printf("[lb] dial %s: %v", b.addr, err)
		return
	}
	defer upstream.Close()

	log.Printf("[lb] %s <-> %s (active=%d)", client.RemoteAddr(), b.addr, atomic.LoadInt64(&b.active))

	done := make(chan struct{}, 2)
	halfClose := func(src, dst net.Conn) {
		io.Copy(dst, src)
		if tc, ok := dst.(*net.TCPConn); ok {
			tc.CloseWrite()
		}
		done <- struct{}{}
	}
	go halfClose(client, upstream)
	go halfClose(upstream, client)
	<-done
	<-done
}
