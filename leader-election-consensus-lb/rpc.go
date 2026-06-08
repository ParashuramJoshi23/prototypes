package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"log"
	"net/http"
	"strings"
	"time"
)

var errNotLeader = errors.New("not the leader")

// -- Wire types for Raft RPCs --

type VoteRequest struct {
	Term         int    `json:"term"`
	CandidateID  string `json:"candidate_id"`
	LastLogIndex int    `json:"last_log_index"`
	LastLogTerm  int    `json:"last_log_term"`
}

type VoteResponse struct {
	Term        int  `json:"term"`
	VoteGranted bool `json:"vote_granted"`
}

type AppendRequest struct {
	Term         int        `json:"term"`
	LeaderID     string     `json:"leader_id"`
	PrevLogIndex int        `json:"prev_log_index"`
	PrevLogTerm  int        `json:"prev_log_term"`
	Entries      []LogEntry `json:"entries"`
	LeaderCommit int        `json:"leader_commit"`
}

type AppendResponse struct {
	Term    int  `json:"term"`
	Success bool `json:"success"`
}

// -- HTTP handlers (receiver side) --

// handleRequestVote processes an incoming RequestVote RPC.
func (n *Node) handleRequestVote(w http.ResponseWriter, r *http.Request) {
	var req VoteRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	n.mu.Lock()
	defer n.mu.Unlock()

	resp := VoteResponse{Term: n.currentTerm, VoteGranted: false}

	if req.Term < n.currentTerm {
		writeJSON(w, resp)
		return
	}

	if req.Term > n.currentTerm {
		n.currentTerm = req.Term
		n.votedFor = ""
		n.setRole(Follower)
	}

	resp.Term = n.currentTerm

	// Grant vote if we haven't voted yet (or already voted for this candidate)
	// and candidate's log is at least as up-to-date as ours.
	canVote := n.votedFor == "" || n.votedFor == req.CandidateID
	logOK := req.LastLogTerm > n.lastLogTerm() ||
		(req.LastLogTerm == n.lastLogTerm() && req.LastLogIndex >= n.lastLogIndex())

	if canVote && logOK {
		n.votedFor = req.CandidateID
		n.lastContact = time.Now()
		resp.VoteGranted = true
		log.Printf("[%s] granted vote to %s for term %d", n.id, req.CandidateID, req.Term)
	}

	writeJSON(w, resp)
}

// handleAppendEntries processes an incoming AppendEntries RPC (heartbeat or replication).
func (n *Node) handleAppendEntries(w http.ResponseWriter, r *http.Request) {
	var req AppendRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	n.mu.Lock()
	defer n.mu.Unlock()

	resp := AppendResponse{Term: n.currentTerm, Success: false}

	if req.Term < n.currentTerm {
		writeJSON(w, resp)
		return
	}

	// Valid leader — reset our election clock.
	n.lastContact = time.Now()
	n.leaderID = req.LeaderID

	if req.Term > n.currentTerm {
		n.currentTerm = req.Term
		n.votedFor = ""
	}
	if n.getRole() != Follower {
		n.setRole(Follower)
		n.lb.setLeader(false)
	}

	resp.Term = n.currentTerm

	// Check log consistency: our log must contain an entry at PrevLogIndex with PrevLogTerm.
	if req.PrevLogIndex > 0 {
		if req.PrevLogIndex > len(n.log) || n.log[req.PrevLogIndex-1].Term != req.PrevLogTerm {
			writeJSON(w, resp) // consistency check failed
			return
		}
	}

	// Append any new entries, replacing conflicting ones.
	for i, entry := range req.Entries {
		idx := req.PrevLogIndex + i + 1
		if idx <= len(n.log) {
			if n.log[idx-1].Term != entry.Term {
				// Conflict: truncate and append.
				n.log = n.log[:idx-1]
				n.log = append(n.log, entry)
			}
			// else: same entry already present, skip
		} else {
			n.log = append(n.log, entry)
		}
	}

	// Advance commit index.
	if req.LeaderCommit > n.commitIndex {
		newCommit := req.LeaderCommit
		if len(n.log) < newCommit {
			newCommit = len(n.log)
		}
		n.commitIndex = newCommit
		go n.applyCommitted()
	}

	resp.Success = true
	writeJSON(w, resp)
}

// -- HTTP senders (initiator side) --

var rpcClient = &http.Client{Timeout: 200 * time.Millisecond}

func sendVoteRequest(peerURL string, req VoteRequest) (VoteResponse, error) {
	var resp VoteResponse
	err := postJSON(peerURL+"/raft/vote", req, &resp)
	return resp, err
}

func sendAppendEntries(peerURL string, req AppendRequest) (AppendResponse, error) {
	var resp AppendResponse
	err := postJSON(peerURL+"/raft/append", req, &resp)
	return resp, err
}

func postJSON(url string, body, out any) error {
	data, err := json.Marshal(body)
	if err != nil {
		return err
	}
	httpResp, err := rpcClient.Post(url, "application/json", bytes.NewReader(data))
	if err != nil {
		return err
	}
	defer httpResp.Body.Close()
	raw, _ := io.ReadAll(httpResp.Body)
	return json.Unmarshal(raw, out)
}

// -- Admin / status HTTP handlers --

func (n *Node) handleStatus(w http.ResponseWriter, _ *http.Request) {
	n.mu.Lock()
	defer n.mu.Unlock()
	writeJSON(w, map[string]any{
		"node":         n.id,
		"role":         n.getRole().String(),
		"term":         n.currentTerm,
		"leader":       n.leaderID,
		"commit_index": n.commitIndex,
		"log_length":   len(n.log),
		"backends":     n.lb.backendList(),
	})
}

// handlePropose accepts a plain-text command (add:<addr> / remove:<addr>) and
// proposes it through Raft consensus. Followers redirect to the leader.
func (n *Node) handlePropose(w http.ResponseWriter, r *http.Request) {
	body, err := io.ReadAll(r.Body)
	if err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}
	cmd := strings.TrimSpace(string(body))
	if err := n.propose(cmd); err != nil {
		if errors.Is(err, errNotLeader) {
			n.mu.Lock()
			leader := n.leaderID
			n.mu.Unlock()
			if leader != "" {
				http.Error(w, fmt.Sprintf("not leader; redirect to %s", leader), http.StatusTemporaryRedirect)
				return
			}
			http.Error(w, "no leader elected yet", http.StatusServiceUnavailable)
			return
		}
		http.Error(w, err.Error(), http.StatusInternalServerError)
		return
	}
	fmt.Fprintf(w, "proposed: %s\n", cmd)
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(v)
}
