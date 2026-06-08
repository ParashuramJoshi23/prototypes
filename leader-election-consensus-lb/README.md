# Leader Election & Consensus for Load Balancer

A distributed load balancer cluster where multiple nodes elect a leader via
**Raft consensus**. Only the elected leader routes TCP traffic. Backend
configuration changes are replicated to all nodes through the Raft log so the
cluster always converges to a consistent backend set.

## How it works

```
All nodes start as FOLLOWERS with random 150–300 ms timers
           │
           │  timer fires (no heartbeat received)
           ▼
       CANDIDATE  ── RequestVote ──► peers
           │
           │  majority votes received
           ▼
         LEADER  ── AppendEntries heartbeat every 50 ms ──► followers
                    (resets their timers; they stay followers)
```

**Leader election**
- Each node draws a random election timeout (150–300 ms). The first to expire
  becomes a candidate, increments its term, and asks peers for votes.
- A peer grants a vote if it hasn't voted in that term yet and the candidate's
  log is at least as up-to-date as its own.
- First candidate to collect a majority (`n/2 + 1`) becomes leader.

**Consensus / log replication**
- Config changes (`add`/`remove` backend) are sent to the leader as proposals.
- The leader appends the entry to its log and broadcasts `AppendEntries` to followers.
- Once a majority acknowledges, the leader advances `commitIndex`; all nodes
  apply committed entries to their backend list.

**Failover**
- If the leader crashes, followers stop receiving heartbeats and time out.
- A new election starts within 150–300 ms. The new leader resumes routing traffic.

## Running a 3-node cluster

```bash
cd leader-election-consensus-lb

# Terminal 1 — node1
go run . \
  --id node1 \
  --raft-addr :9001 \
  --lb-addr   :7001 \
  --peers     http://localhost:9002,http://localhost:9003 \
  --backends  127.0.0.1:8001,127.0.0.1:8002

# Terminal 2 — node2
go run . \
  --id node2 \
  --raft-addr :9002 \
  --lb-addr   :7002 \
  --peers     http://localhost:9001,http://localhost:9003 \
  --backends  127.0.0.1:8001,127.0.0.1:8002

# Terminal 3 — node3
go run . \
  --id node3 \
  --raft-addr :9003 \
  --lb-addr   :7003 \
  --peers     http://localhost:9001,http://localhost:9002 \
  --backends  127.0.0.1:8001,127.0.0.1:8002
```

Within ~300 ms one node wins the election and its `:700x` port starts routing traffic.

## Admin API

All nodes expose an HTTP admin port (`--raft-addr`).

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/status` | GET | Node role, term, leader, log length, backend list |
| `/propose` | POST | Propose a backend change (leader only) |
| `/raft/vote` | POST | Internal — RequestVote RPC |
| `/raft/append` | POST | Internal — AppendEntries RPC |

```bash
# Check cluster state
curl http://localhost:9001/status

# Add a backend (through Raft consensus — all nodes get it)
curl -X POST http://localhost:9002/propose -d "add:127.0.0.1:8003"

# Remove a backend
curl -X POST http://localhost:9002/propose -d "remove:127.0.0.1:8001"
```

Posting to a follower returns `307 Temporary Redirect` with the leader's address.

## Simulating failover

```bash
# Find and kill the current leader
curl -s http://localhost:9001/status | grep leader

# Kill that node's process (e.g. node2 listens on :9002)
kill $(lsof -ti:9002)

# Within ~300 ms a new leader is elected
curl http://localhost:9001/status   # role: leader or follower, leader: nodeX
```

## Running tests

```bash
go test ./...                      # all tests (~3 s)
go test -v ./...                   # verbose (shows election logs)
go test -run TestLeaderFailover    # single test
go test -race ./...                # with race detector
```

### Test coverage

| Test | What it verifies |
|------|-----------------|
| `TestVoteGranted` | Vote-granting rules (deny same-term second candidate, deny stale log) |
| `TestLogHelpers` | 1-based log index/term helpers |
| `TestLBApply` | add/remove commands, duplicate/missing no-ops |
| `TestLBRoundRobin` | Round-robin pick distributes evenly |
| `TestSingleNodeElectsSelf` | Lone node elects itself leader |
| `TestThreeNodeElection` | Exactly one leader, no split-brain |
| `TestLeaderSendsHeartbeats` | Leader stable over 4× max timeout |
| `TestLogReplication` | Proposed entry committed and applied on all nodes |
| `TestMultipleCommands` | 4 sequential commands all converge correctly |
| `TestLeaderFailover` | New leader elected after old one is stopped |
| `TestFollowerRejectsPropose` | Follower returns `not the leader` error |
| `TestConcurrentProposals` | 5 concurrent goroutines propose; cluster converges |

## Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--id` | `node1` | Unique node identifier |
| `--raft-addr` | `:9001` | Raft RPC + admin HTTP listen address |
| `--lb-addr` | `:7001` | TCP load-balancer listen address |
| `--peers` | *(empty)* | Comma-separated HTTP base URLs of other nodes |
| `--backends` | `127.0.0.1:8001,...` | Initial backend addresses |

## File structure

```
main.go        CLI entry point, HTTP mux wiring
node.go        Raft state machine — election, heartbeat, log, commit
rpc.go         RequestVote + AppendEntries HTTP handlers and senders
lb.go          L4 TCP proxy; only routes when isLeader=1
raft_test.go   Unit + integration test suite
```
