package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"strings"
	"time"
)

// LoadBalancer is a layer-4 TCP reverse proxy. Because it only shuffles
// raw bytes between the client socket and the chosen upstream socket, it
// is protocol-agnostic: plain TCP, HTTP/1.1 (including keep-alive),
// HTTP/2 over cleartext, and WebSocket (which is just a long-lived TCP
// stream after the HTTP upgrade) all work without any code changes.
type LoadBalancer struct {
	Listen   string
	Backends []*Backend
	Strategy Strategy
	DialTO   time.Duration
}

func (lb *LoadBalancer) Run() error {
	ln, err := net.Listen("tcp", lb.Listen)
	if err != nil {
		return fmt.Errorf("listen %s: %w", lb.Listen, err)
	}
	log.Printf("L4 LB listening on %s -> %v", lb.Listen, backendAddrs(lb.Backends))

	for {
		client, err := ln.Accept()
		if err != nil {
			return fmt.Errorf("accept: %w", err)
		}
		go lb.handle(client) // one goroutine per connection
	}
}

func (lb *LoadBalancer) handle(client net.Conn) {
	defer client.Close()

	backend := lb.Strategy.Select(lb.Backends)
	backend.Inc()
	defer backend.Dec()

	upstream, err := net.DialTimeout("tcp", backend.Addr, lb.DialTO)
	if err != nil {
		log.Printf("dial %s: %v", backend.Addr, err)
		return
	}
	defer upstream.Close()

	log.Printf("%s <-> %s (active=%d)", client.RemoteAddr(), backend.Addr, backend.Active())

	// Splice bytes in both directions with io.Copy. When one direction
	// hits EOF we half-close the other side's write so the peer sees the
	// FIN (needed for clients like curl/nc that close-after-send and wait
	// for the response). Both goroutines must finish before we close the
	// sockets, otherwise we'd cut off an in-flight response. This single
	// primitive handles request/response (HTTP) and long-lived
	// bidirectional streams (WebSocket, raw TCP) identically.
	done := make(chan struct{}, 2)
	go func() {
		io.Copy(upstream, client)
		if u, ok := upstream.(*net.TCPConn); ok {
			u.CloseWrite()
		}
		done <- struct{}{}
	}()
	go func() {
		io.Copy(client, upstream)
		if c, ok := client.(*net.TCPConn); ok {
			c.CloseWrite()
		}
		done <- struct{}{}
	}()
	<-done
	<-done
}

func backendAddrs(bs []*Backend) []string {
	out := make([]string, len(bs))
	for i, b := range bs {
		out[i] = b.Addr
	}
	return out
}

func pickStrategy(name string) Strategy {
	switch strings.ToLower(name) {
	case "rr", "round-robin", "roundrobin":
		return &RoundRobin{}
	case "random", "rand":
		return NewRandom(time.Now().UnixNano())
	case "lc", "least", "least-connections", "leastconnections":
		return LeastConnections{}
	default:
		log.Fatalf("unknown strategy %q (use rr|random|lc)", name)
		return nil
	}
}

func main() {
	listen := flag.String("listen", "127.0.0.1:7000", "address to listen on")
	backendsFlag := flag.String("backends", "127.0.0.1:8001,127.0.0.1:8002,127.0.0.1:8003",
		"comma-separated host:port list of upstream backends")
	strategyName := flag.String("strategy", "rr", "selection strategy: rr | random | lc")
	dialTO := flag.Duration("dial-timeout", 2*time.Second, "upstream dial timeout")
	flag.Parse()

	addrs := strings.Split(*backendsFlag, ",")
	backends := make([]*Backend, len(addrs))
	for i, a := range addrs {
		backends[i] = &Backend{Addr: strings.TrimSpace(a)}
	}

	lb := &LoadBalancer{
		Listen:   *listen,
		Backends: backends,
		Strategy: pickStrategy(*strategyName),
		DialTO:   *dialTO,
	}
	if err := lb.Run(); err != nil {
		log.Fatal(err)
	}
}
