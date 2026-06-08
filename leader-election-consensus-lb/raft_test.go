package main

import (
	"fmt"
	"net"
	"net/http"
	"strings"
	"sync"
	"testing"
	"time"
)

// cluster spins up n in-process nodes connected to each other over real HTTP.
// Each node gets a free OS port for its Raft listener; no LB port is opened.
type cluster struct {
	nodes   []*Node
	servers []*http.Server
	addrs   []string // "http://127.0.0.1:<port>"
	t       *testing.T
}

func newCluster(t *testing.T, n int, backends []string) *cluster {
	t.Helper()

	// Allocate ports first so we can wire peer lists.
	listeners := make([]net.Listener, n)
	addrs := make([]string, n)
	for i := range listeners {
		ln, err := net.Listen("tcp", "127.0.0.1:0")
		if err != nil {
			t.Fatalf("listen: %v", err)
		}
		listeners[i] = ln
		addrs[i] = "http://" + ln.Addr().String()
	}

	c := &cluster{t: t, addrs: addrs}

	for i := 0; i < n; i++ {
		peers := make([]string, 0, n-1)
		for j, a := range addrs {
			if j != i {
				peers = append(peers, a)
			}
		}
		node := newNode(fmt.Sprintf("node%d", i+1), peers, backends)
		c.nodes = append(c.nodes, node)

		mux := http.NewServeMux()
		mux.HandleFunc("/raft/vote", node.handleRequestVote)
		mux.HandleFunc("/raft/append", node.handleAppendEntries)
		mux.HandleFunc("/status", node.handleStatus)
		mux.HandleFunc("/propose", node.handlePropose)

		srv := &http.Server{Handler: mux}
		c.servers = append(c.servers, srv)

		go srv.Serve(listeners[i])
		go node.run()
	}

	t.Cleanup(c.shutdown)
	return c
}

func (c *cluster) shutdown() {
	for _, node := range c.nodes {
		close(node.stopCh)
	}
	for _, srv := range c.servers {
		srv.Close()
	}
}

// waitLeader blocks until exactly one leader exists and returns it.
func (c *cluster) waitLeader(timeout time.Duration) *Node {
	c.t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		var leaders []*Node
		for _, n := range c.nodes {
			if n.getRole() == Leader {
				leaders = append(leaders, n)
			}
		}
		if len(leaders) == 1 {
			return leaders[0]
		}
		time.Sleep(10 * time.Millisecond)
	}
	c.t.Fatalf("no single leader elected within %s", timeout)
	return nil
}

// waitCommit blocks until all nodes have commitIndex >= idx.
func (c *cluster) waitCommit(idx int, timeout time.Duration) {
	c.t.Helper()
	deadline := time.Now().Add(timeout)
	for time.Now().Before(deadline) {
		all := true
		for _, n := range c.nodes {
			n.mu.Lock()
			ci := n.commitIndex
			n.mu.Unlock()
			if ci < idx {
				all = false
				break
			}
		}
		if all {
			return
		}
		time.Sleep(10 * time.Millisecond)
	}
	c.t.Fatalf("nodes did not commit index %d within %s", idx, timeout)
}

// ── Unit tests ────────────────────────────────────────────────────────────────

// TestVoteGranted verifies the three vote-granting rules independently.
func TestVoteGranted(t *testing.T) {
	n := newNode("n1", nil, nil)
	n.mu.Lock()

	// Rule 1: vote for first candidate when votedFor is empty.
	req := VoteRequest{Term: 1, CandidateID: "n2", LastLogIndex: 0, LastLogTerm: 0}
	canVote := n.votedFor == "" || n.votedFor == req.CandidateID
	logOK := req.LastLogTerm > n.lastLogTerm() ||
		(req.LastLogTerm == n.lastLogTerm() && req.LastLogIndex >= n.lastLogIndex())
	if !canVote || !logOK {
		t.Fatal("should grant vote to first candidate")
	}

	// Rule 2: deny second candidate in same term.
	n.votedFor = "n2"
	req2 := VoteRequest{Term: 1, CandidateID: "n3"}
	canVote2 := n.votedFor == "" || n.votedFor == req2.CandidateID
	if canVote2 {
		t.Fatal("should deny vote to second candidate in same term")
	}

	// Rule 3: deny candidate with stale log.
	n.votedFor = ""
	n.log = []LogEntry{{Term: 2, Command: "add:x"}}
	req3 := VoteRequest{Term: 3, CandidateID: "n3", LastLogIndex: 0, LastLogTerm: 1}
	logOK3 := req3.LastLogTerm > n.lastLogTerm() ||
		(req3.LastLogTerm == n.lastLogTerm() && req3.LastLogIndex >= n.lastLogIndex())
	if logOK3 {
		t.Fatal("should deny vote when candidate log is behind")
	}

	n.mu.Unlock()
}

// TestLogHelpers checks 1-based index helpers.
func TestLogHelpers(t *testing.T) {
	n := newNode("n1", nil, nil)
	n.mu.Lock()
	defer n.mu.Unlock()

	if n.lastLogIndex() != 0 {
		t.Fatalf("empty log: want index 0, got %d", n.lastLogIndex())
	}
	n.log = append(n.log, LogEntry{Term: 1, Command: "add:x"})
	n.log = append(n.log, LogEntry{Term: 2, Command: "add:y"})

	if n.lastLogIndex() != 2 {
		t.Fatalf("want lastLogIndex=2, got %d", n.lastLogIndex())
	}
	if n.lastLogTerm() != 2 {
		t.Fatalf("want lastLogTerm=2, got %d", n.lastLogTerm())
	}
	if n.logTermAt(1) != 1 {
		t.Fatalf("want term at index 1 = 1, got %d", n.logTermAt(1))
	}
}

// TestLBApply verifies the LB state machine applies add/remove commands.
func TestLBApply(t *testing.T) {
	lb := newLB([]string{"10.0.0.1:80"})

	lb.apply("add:10.0.0.2:80")
	if len(lb.backends) != 2 {
		t.Fatalf("want 2 backends after add, got %d", len(lb.backends))
	}

	lb.apply("add:10.0.0.2:80") // duplicate — should be a no-op
	if len(lb.backends) != 2 {
		t.Fatalf("duplicate add should be ignored")
	}

	lb.apply("remove:10.0.0.1:80")
	if len(lb.backends) != 1 {
		t.Fatalf("want 1 backend after remove, got %d", len(lb.backends))
	}
	if lb.backends[0].addr != "10.0.0.2:80" {
		t.Fatalf("wrong backend remaining: %s", lb.backends[0].addr)
	}

	lb.apply("remove:10.0.0.1:80") // not present — should be a no-op
	if len(lb.backends) != 1 {
		t.Fatalf("remove of missing backend should be ignored")
	}
}

// TestLBRoundRobin checks that pick() cycles through backends.
func TestLBRoundRobin(t *testing.T) {
	lb := newLB([]string{"a:1", "b:2", "c:3"})

	seen := make([]string, 6)
	for i := range seen {
		seen[i] = lb.pick().addr
	}
	// Each backend must appear exactly twice in 6 picks (round-robin modulo 3).
	counts := map[string]int{}
	for _, s := range seen {
		counts[s]++
	}
	for _, addr := range []string{"a:1", "b:2", "c:3"} {
		if counts[addr] != 2 {
			t.Fatalf("backend %s appeared %d times, want 2", addr, counts[addr])
		}
	}
}

// ── Integration tests ─────────────────────────────────────────────────────────

// TestSingleNodeElectsSelf verifies a lone node becomes leader.
func TestSingleNodeElectsSelf(t *testing.T) {
	c := newCluster(t, 1, nil)
	leader := c.waitLeader(500 * time.Millisecond)
	if leader.id != "node1" {
		t.Fatalf("expected node1 to elect itself, got %s", leader.id)
	}
}

// TestThreeNodeElection verifies exactly one leader emerges from a 3-node cluster.
func TestThreeNodeElection(t *testing.T) {
	c := newCluster(t, 3, nil)
	leader := c.waitLeader(time.Second)
	t.Logf("elected leader: %s (term %d)", leader.id, leader.currentTerm)

	// Confirm no other node thinks it's a leader.
	for _, n := range c.nodes {
		if n != leader && n.getRole() == Leader {
			t.Fatalf("split-brain: both %s and %s claim to be leader", leader.id, n.id)
		}
	}
}

// TestLeaderSendsHeartbeats checks followers don't re-elect while leader is alive.
func TestLeaderSendsHeartbeats(t *testing.T) {
	c := newCluster(t, 3, nil)
	leader := c.waitLeader(time.Second)
	firstTerm := leader.currentTerm

	// Wait 4× the maximum election timeout and confirm same leader, same term.
	time.Sleep(4 * 300 * time.Millisecond)

	if leader.getRole() != Leader {
		t.Fatalf("%s lost leadership without any failure", leader.id)
	}
	leader.mu.Lock()
	term := leader.currentTerm
	leader.mu.Unlock()
	if term != firstTerm {
		t.Fatalf("term advanced from %d to %d without a failure", firstTerm, term)
	}
}

// TestLogReplication proposes a command on the leader and verifies all
// nodes commit and apply it.
func TestLogReplication(t *testing.T) {
	c := newCluster(t, 3, []string{"10.0.0.1:80", "10.0.0.2:80"})
	leader := c.waitLeader(time.Second)

	if err := leader.propose("add:10.0.0.3:80"); err != nil {
		t.Fatalf("propose: %v", err)
	}

	// All nodes must commit index 1 within 500 ms.
	c.waitCommit(1, 500*time.Millisecond)

	for _, n := range c.nodes {
		n.lb.mu.RLock()
		addrs := make([]string, len(n.lb.backends))
		for i, b := range n.lb.backends {
			addrs[i] = b.addr
		}
		n.lb.mu.RUnlock()

		found := false
		for _, a := range addrs {
			if a == "10.0.0.3:80" {
				found = true
				break
			}
		}
		if !found {
			t.Fatalf("node %s did not apply add:10.0.0.3:80 (backends=%v)", n.id, addrs)
		}
	}
}

// TestMultipleCommands proposes several commands and confirms all are applied
// in order on every node.
func TestMultipleCommands(t *testing.T) {
	c := newCluster(t, 3, nil)
	leader := c.waitLeader(time.Second)

	cmds := []string{
		"add:10.0.0.1:80",
		"add:10.0.0.2:80",
		"add:10.0.0.3:80",
		"remove:10.0.0.2:80",
	}
	for _, cmd := range cmds {
		if err := leader.propose(cmd); err != nil {
			t.Fatalf("propose %q: %v", cmd, err)
		}
	}

	c.waitCommit(len(cmds), time.Second)

	for _, n := range c.nodes {
		n.lb.mu.RLock()
		addrs := map[string]bool{}
		for _, b := range n.lb.backends {
			addrs[b.addr] = true
		}
		n.lb.mu.RUnlock()

		if addrs["10.0.0.2:80"] {
			t.Fatalf("node %s still has removed backend 10.0.0.2:80", n.id)
		}
		if !addrs["10.0.0.1:80"] || !addrs["10.0.0.3:80"] {
			t.Fatalf("node %s missing expected backends (got %v)", n.id, addrs)
		}
	}
}

// TestLeaderFailover shuts down the leader and verifies a new one emerges.
func TestLeaderFailover(t *testing.T) {
	c := newCluster(t, 3, nil)
	first := c.waitLeader(time.Second)
	firstID := first.id
	t.Logf("first leader: %s (term %d)", firstID, first.currentTerm)

	// Stop the leader's Raft loop and HTTP server.
	close(first.stopCh)
	for _, srv := range c.servers {
		// Close only the server for the first leader.
		srv.Close()
		break
	}

	// Remove the dead node from consideration.
	var remaining []*Node
	var remainingServers []*http.Server
	for i, n := range c.nodes {
		if n.id != firstID {
			remaining = append(remaining, n)
			remainingServers = append(remainingServers, c.servers[i])
		}
	}
	c.nodes = remaining
	c.servers = remainingServers

	second := c.waitLeader(2 * time.Second)
	if second.id == firstID {
		t.Fatalf("dead node %s should not win re-election", firstID)
	}
	if second.currentTerm <= 1 {
		t.Fatalf("new leader should have higher term after re-election, got %d", second.currentTerm)
	}
	t.Logf("new leader: %s (term %d)", second.id, second.currentTerm)
}

// TestFollowerRejectsPropose verifies a follower returns errNotLeader.
func TestFollowerRejectsPropose(t *testing.T) {
	c := newCluster(t, 3, nil)
	c.waitLeader(time.Second)

	for _, n := range c.nodes {
		if n.getRole() == Follower {
			err := n.propose("add:10.0.0.1:80")
			if err == nil {
				t.Fatalf("follower %s should reject propose", n.id)
			}
			if !strings.Contains(err.Error(), "not the leader") {
				t.Fatalf("unexpected error: %v", err)
			}
			return
		}
	}
	t.Fatal("no follower found in cluster")
}

// TestConcurrentProposals proposes commands from multiple goroutines and
// verifies the cluster converges to a consistent state.
func TestConcurrentProposals(t *testing.T) {
	c := newCluster(t, 3, nil)
	leader := c.waitLeader(time.Second)

	const n = 5
	var wg sync.WaitGroup
	for i := 0; i < n; i++ {
		wg.Add(1)
		go func(i int) {
			defer wg.Done()
			_ = leader.propose(fmt.Sprintf("add:10.0.0.%d:80", i))
		}(i)
	}
	wg.Wait()

	c.waitCommit(n, 2*time.Second)

	// All nodes should have the same log length and commit index.
	for _, node := range c.nodes {
		node.mu.Lock()
		ll := len(node.log)
		ci := node.commitIndex
		node.mu.Unlock()
		if ll != n {
			t.Errorf("node %s: log length %d, want %d", node.id, ll, n)
		}
		if ci != n {
			t.Errorf("node %s: commitIndex %d, want %d", node.id, ci, n)
		}
	}
}
