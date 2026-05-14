package main

import (
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"strings"
	"sync"
	"time"
)

// LoadBalancer is a TCP (layer 4) reverse proxy. It accepts client
// connections on Listen, asks the Strategy to pick a backend, dials the
// backend, and splices bytes both ways with io.Copy.
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
	log.Printf("L4 LB listening on %s -> %d backends", lb.Listen, len(lb.Backends))

	for {
		client, err := ln.Accept()
		if err != nil {
			return fmt.Errorf("accept: %w", err)
		}
		go lb.handle(client)
	}
}

func (lb *LoadBalancer) handle(client net.Conn) {
	defer client.Close()

	backend := lb.Strategy.Select(lb.Backends)
	backend.Inc()
	defer func() {
		backend.Dec()
		lb.Strategy.Release(backend)
	}()

	upstream, err := net.DialTimeout("tcp", backend.Addr, lb.DialTO)
	if err != nil {
		log.Printf("dial %s: %v", backend.Addr, err)
		return
	}
	defer upstream.Close()

	log.Printf("%s <-> %s (active=%d)", client.RemoteAddr(), backend.Addr, backend.Active())

	// Splice client <-> upstream in both directions concurrently.
	// When either side closes, half-close the other so io.Copy returns.
	var wg sync.WaitGroup
	wg.Add(2)
	go pipe(&wg, upstream, client) // client -> upstream
	go pipe(&wg, client, upstream) // upstream -> client
	wg.Wait()
}

func pipe(wg *sync.WaitGroup, dst, src net.Conn) {
	defer wg.Done()
	io.Copy(dst, src)
	if c, ok := dst.(interface{ CloseWrite() error }); ok {
		c.CloseWrite()
	}
}

// startEchoServers spins up N trivial TCP echo servers and returns their
// addresses. Useful for smoke-testing the LB without external dependencies.
func startEchoServers(n int) ([]string, error) {
	addrs := make([]string, 0, n)
	for i := 0; i < n; i++ {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			return nil, err
		}
		id := i + 1
		go func() {
			for {
				c, err := ln.Accept()
				if err != nil {
					return
				}
				go func(conn net.Conn) {
					defer conn.Close()
					fmt.Fprintf(conn, "[server-%d] hello\n", id)
					io.Copy(conn, conn) // echo
				}(c)
			}
		}()
		addrs = append(addrs, ln.Addr().String())
	}
	return addrs, nil
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
	backendsFlag := flag.String("backends", "", "comma-separated host:port list; empty = spawn 3 local echo servers")
	strategyName := flag.String("strategy", "rr", "selection strategy: rr | random | lc")
	dialTO := flag.Duration("dial-timeout", 2*time.Second, "upstream dial timeout")
	flag.Parse()

	var addrs []string
	if *backendsFlag == "" {
		var err error
		addrs, err = startEchoServers(3)
		if err != nil {
			log.Fatalf("start echo servers: %v", err)
		}
		log.Printf("spawned local echo backends: %v", addrs)
	} else {
		addrs = strings.Split(*backendsFlag, ",")
	}

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
