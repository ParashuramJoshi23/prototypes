// Package main implements a distributed load balancer cluster using the Raft
// consensus algorithm for leader election and configuration replication.
//
// Each node exposes two ports:
//   - Raft / Admin HTTP port  (--raft-addr)   e.g. :9001
//   - TCP load-balancer port  (--lb-addr)     e.g. :7001
//
// Only the elected leader's LB port accepts connections; all other nodes
// silently drop inbound TCP until they become leader.
//
// Run a 3-node cluster:
//
//	go run . --id node1 --raft-addr :9001 --lb-addr :7001 \
//	          --peers http://localhost:9002,http://localhost:9003 \
//	          --backends 127.0.0.1:8001,127.0.0.1:8002,127.0.0.1:8003
//
//	go run . --id node2 --raft-addr :9002 --lb-addr :7002 \
//	          --peers http://localhost:9001,http://localhost:9003 \
//	          --backends 127.0.0.1:8001,127.0.0.1:8002,127.0.0.1:8003
//
//	go run . --id node3 --raft-addr :9003 --lb-addr :7003 \
//	          --peers http://localhost:9001,http://localhost:9002 \
//	          --backends 127.0.0.1:8001,127.0.0.1:8002,127.0.0.1:8003
//
// Check status:   curl http://localhost:9001/status
// Add backend:    curl -X POST http://localhost:9001/propose -d "add:127.0.0.1:8004"
// Remove backend: curl -X POST http://localhost:9001/propose -d "remove:127.0.0.1:8001"
package main

import (
	"flag"
	"log"
	"net/http"
	"strings"
)

func main() {
	id := flag.String("id", "node1", "unique node identifier")
	raftAddr := flag.String("raft-addr", ":9001", "Raft/admin HTTP listen address")
	lbAddr := flag.String("lb-addr", ":7001", "TCP load-balancer listen address")
	peersFlag := flag.String("peers", "", "comma-separated HTTP base URLs of peer nodes")
	backendsFlag := flag.String("backends", "127.0.0.1:8001,127.0.0.1:8002", "comma-separated backend addresses")
	flag.Parse()

	var peers []string
	for _, p := range strings.Split(*peersFlag, ",") {
		if p = strings.TrimSpace(p); p != "" {
			peers = append(peers, p)
		}
	}

	var backends []string
	for _, b := range strings.Split(*backendsFlag, ",") {
		if b = strings.TrimSpace(b); b != "" {
			backends = append(backends, b)
		}
	}

	node := newNode(*id, peers, backends)

	// Register Raft RPC handlers.
	mux := http.NewServeMux()
	mux.HandleFunc("/raft/vote", node.handleRequestVote)
	mux.HandleFunc("/raft/append", node.handleAppendEntries)

	// Admin API.
	mux.HandleFunc("/status", node.handleStatus)
	mux.HandleFunc("/propose", node.handlePropose)

	// Start Raft loop.
	go node.run()

	// Start TCP LB listener.
	go func() {
		if err := node.lb.listenAndServe(*lbAddr); err != nil {
			log.Fatalf("lb listener: %v", err)
		}
	}()

	log.Printf("[%s] Raft HTTP on %s | LB TCP on %s | peers=%v | backends=%v",
		*id, *raftAddr, *lbAddr, peers, backends)

	if err := http.ListenAndServe(*raftAddr, mux); err != nil {
		log.Fatal(err)
	}
}
