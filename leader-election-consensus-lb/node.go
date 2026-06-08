package main

import (
	"log"
	"math/rand"
	"sync"
	"sync/atomic"
	"time"
)

// Role is the Raft node state.
type Role int32

const (
	Follower  Role = 0
	Candidate Role = 1
	Leader    Role = 2
)

func (r Role) String() string {
	switch r {
	case Follower:
		return "follower"
	case Candidate:
		return "candidate"
	case Leader:
		return "leader"
	}
	return "unknown"
}

// LogEntry is a single Raft log record. Commands encode backend mutations.
// Format: "add:<addr>" or "remove:<addr>"
type LogEntry struct {
	Term    int    `json:"term"`
	Command string `json:"command"`
}

// Node is a Raft participant that also drives the load balancer when elected leader.
type Node struct {
	id    string   // unique node identifier, e.g. "node1"
	peers []string // HTTP base URLs of all OTHER nodes

	// -- Raft persistent state (would be flushed to disk in production) --
	mu          sync.Mutex
	currentTerm int
	votedFor    string
	log         []LogEntry // index 0 = log[1] (1-based indexing via helpers)

	// -- Raft volatile state --
	commitIndex int // highest log index known to be committed
	lastApplied int // highest log index applied to state machine

	// -- Leader volatile state (reset on election) --
	nextIndex  map[string]int // for each peer: next log index to send
	matchIndex map[string]int // for each peer: highest replicated index

	// -- Role tracking --
	role     int32 // atomic, use Role(atomic.Load)
	leaderID string

	// -- Timers --
	lastContact time.Time // last time we heard from a valid leader or granted vote

	// -- Load balancer controlled by this node --
	lb *LB

	// -- Channels --
	heartbeatCh chan appendResult // leader uses to tally AppendEntries acks
	stopCh      chan struct{}
}

// appendResult carries a peer's response back to the leader loop.
type appendResult struct {
	peer    string
	term    int
	success bool
}

func newNode(id string, peers []string, backends []string) *Node {
	n := &Node{
		id:          id,
		peers:       peers,
		currentTerm: 0,
		votedFor:    "",
		log:         []LogEntry{},
		commitIndex: 0,
		lastApplied: 0,
		nextIndex:   make(map[string]int),
		matchIndex:  make(map[string]int),
		lb:          newLB(backends),
		heartbeatCh: make(chan appendResult, 64),
		stopCh:      make(chan struct{}),
	}
	n.setRole(Follower)
	n.lastContact = time.Now()
	return n
}

// -- Role helpers --

func (n *Node) setRole(r Role) { atomic.StoreInt32(&n.role, int32(r)) }
func (n *Node) getRole() Role  { return Role(atomic.LoadInt32(&n.role)) }

// -- Log helpers (1-based) --

func (n *Node) lastLogIndex() int { return len(n.log) }
func (n *Node) lastLogTerm() int {
	if len(n.log) == 0 {
		return 0
	}
	return n.log[len(n.log)-1].Term
}
func (n *Node) logTermAt(index int) int {
	if index <= 0 || index > len(n.log) {
		return 0
	}
	return n.log[index-1].Term
}

// -- Election timeout --

func electionTimeout() time.Duration {
	// 150–300 ms randomised per Raft paper.
	return time.Duration(150+rand.Intn(150)) * time.Millisecond
}

const heartbeatInterval = 50 * time.Millisecond

// -- Main Raft loop --

func (n *Node) run() {
	for {
		select {
		case <-n.stopCh:
			return
		default:
		}

		switch n.getRole() {
		case Follower:
			n.runFollower()
		case Candidate:
			n.runCandidate()
		case Leader:
			n.runLeader()
		}
	}
}

func (n *Node) runFollower() {
	timeout := electionTimeout()
	timer := time.NewTimer(timeout)
	defer timer.Stop()

	for {
		select {
		case <-n.stopCh:
			return
		case <-timer.C:
			n.mu.Lock()
			elapsed := time.Since(n.lastContact)
			n.mu.Unlock()
			if elapsed >= timeout {
				log.Printf("[%s] election timeout — starting election (term %d)", n.id, n.currentTerm+1)
				n.setRole(Candidate)
				return
			}
			timer.Reset(electionTimeout())
		}
	}
}

func (n *Node) runCandidate() {
	n.mu.Lock()
	n.currentTerm++
	term := n.currentTerm
	n.votedFor = n.id
	lastIdx := n.lastLogIndex()
	lastTerm := n.lastLogTerm()
	n.lastContact = time.Now() // reset so we don't immediately re-elect
	n.mu.Unlock()

	log.Printf("[%s] became candidate for term %d", n.id, term)

	votes := 1 // self-vote
	needed := (len(n.peers)+1)/2 + 1

	var wg sync.WaitGroup
	var mu sync.Mutex
	var maxTerm int

	for _, peer := range n.peers {
		wg.Add(1)
		go func(p string) {
			defer wg.Done()
			resp, err := sendVoteRequest(p, VoteRequest{
				Term:         term,
				CandidateID:  n.id,
				LastLogIndex: lastIdx,
				LastLogTerm:  lastTerm,
			})
			mu.Lock()
			defer mu.Unlock()
			if err != nil {
				return
			}
			if resp.Term > maxTerm {
				maxTerm = resp.Term
			}
			if resp.VoteGranted {
				votes++
			}
		}(peer)
	}

	// Wait with timeout equal to election timeout so we don't block forever.
	done := make(chan struct{})
	go func() { wg.Wait(); close(done) }()
	select {
	case <-done:
	case <-time.After(electionTimeout()):
	}

	n.mu.Lock()
	defer n.mu.Unlock()

	if maxTerm > n.currentTerm {
		log.Printf("[%s] saw higher term %d — reverting to follower", n.id, maxTerm)
		n.currentTerm = maxTerm
		n.votedFor = ""
		n.setRole(Follower)
		return
	}

	if votes >= needed {
		log.Printf("[%s] WON election for term %d (%d/%d votes)", n.id, term, votes, len(n.peers)+1)
		n.leaderID = n.id
		for _, p := range n.peers {
			n.nextIndex[p] = n.lastLogIndex() + 1
			n.matchIndex[p] = 0
		}
		n.setRole(Leader)
		n.lb.setLeader(true)
	} else {
		log.Printf("[%s] lost election (got %d/%d votes) — back to follower", n.id, votes, needed)
		n.setRole(Follower)
		n.lastContact = time.Now()
	}
}

func (n *Node) runLeader() {
	log.Printf("[%s] is now LEADER (term %d), serving traffic", n.id, n.currentTerm)
	ticker := time.NewTicker(heartbeatInterval)
	defer ticker.Stop()

	for {
		select {
		case <-n.stopCh:
			n.lb.setLeader(false)
			return
		case <-ticker.C:
			if n.getRole() != Leader {
				n.lb.setLeader(false)
				return
			}
			n.broadcastAppendEntries()
		case res := <-n.heartbeatCh:
			n.mu.Lock()
			if res.term > n.currentTerm {
				log.Printf("[%s] saw higher term %d from %s — stepping down", n.id, res.term, res.peer)
				n.currentTerm = res.term
				n.votedFor = ""
				n.mu.Unlock()
				n.setRole(Follower)
				n.lb.setLeader(false)
				return
			}
			if res.success {
				// advance matchIndex / nextIndex and check commit
				prev := n.nextIndex[res.peer] - 1
				if prev > n.matchIndex[res.peer] {
					n.matchIndex[res.peer] = prev
				}
				n.advanceCommitIndex()
			}
			n.mu.Unlock()
		}
	}
}

// broadcastAppendEntries sends heartbeats (and any pending log entries) to all peers.
func (n *Node) broadcastAppendEntries() {
	n.mu.Lock()
	term := n.currentTerm
	leaderCommit := n.commitIndex
	n.mu.Unlock()

	for _, peer := range n.peers {
		go func(p string) {
			n.mu.Lock()
			prevIdx := n.nextIndex[p] - 1
			prevTerm := n.logTermAt(prevIdx)
			entries := append([]LogEntry{}, n.log[prevIdx:]...)
			n.mu.Unlock()

			resp, err := sendAppendEntries(p, AppendRequest{
				Term:         term,
				LeaderID:     n.id,
				PrevLogIndex: prevIdx,
				PrevLogTerm:  prevTerm,
				Entries:      entries,
				LeaderCommit: leaderCommit,
			})
			if err != nil {
				return
			}

			if resp.Success {
				n.mu.Lock()
				newMatch := prevIdx + len(entries)
				if newMatch > n.matchIndex[p] {
					n.matchIndex[p] = newMatch
					n.nextIndex[p] = newMatch + 1
				}
				n.mu.Unlock()
			} else if !resp.Success && resp.Term <= term {
				// Log inconsistency: back up nextIndex by 1 and retry next heartbeat.
				n.mu.Lock()
				if n.nextIndex[p] > 1 {
					n.nextIndex[p]--
				}
				n.mu.Unlock()
			}

			n.heartbeatCh <- appendResult{peer: p, term: resp.Term, success: resp.Success}
		}(peer)
	}
}

// advanceCommitIndex checks if a new log index has been replicated to a majority
// and advances commitIndex, triggering state machine application. Must hold mu.
func (n *Node) advanceCommitIndex() {
	for idx := len(n.log); idx > n.commitIndex; idx-- {
		if n.log[idx-1].Term != n.currentTerm {
			break // only commit entries from current term (Raft §5.4.2)
		}
		count := 1 // self
		for _, p := range n.peers {
			if n.matchIndex[p] >= idx {
				count++
			}
		}
		if count >= (len(n.peers)+1)/2+1 {
			n.commitIndex = idx
			log.Printf("[%s] committed log up to index %d", n.id, idx)
			go n.applyCommitted()
			break
		}
	}
}

// applyCommitted applies newly committed log entries to the LB state machine.
func (n *Node) applyCommitted() {
	n.mu.Lock()
	entries := append([]LogEntry{}, n.log[n.lastApplied:n.commitIndex]...)
	n.lastApplied = n.commitIndex
	n.mu.Unlock()

	for _, e := range entries {
		n.lb.apply(e.Command)
	}
}

// propose appends a command to the leader's log and triggers replication.
// Returns an error if this node is not the leader.
func (n *Node) propose(command string) error {
	n.mu.Lock()
	if n.getRole() != Leader {
		n.mu.Unlock()
		return errNotLeader
	}
	entry := LogEntry{Term: n.currentTerm, Command: command}
	n.log = append(n.log, entry)
	idx := len(n.log)
	log.Printf("[%s] proposed entry %d: %q", n.id, idx, command)
	n.mu.Unlock()

	// Immediately broadcast so followers pick it up on the next heartbeat.
	n.broadcastAppendEntries()
	return nil
}
