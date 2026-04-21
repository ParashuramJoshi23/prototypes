#!/usr/bin/env bash
# Run all 6 programs and print a comparison table.
# Usage: bash benchmark.sh

set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

run() {
  local label="$1" dir="$2" cmd="$3"
  local out
  out=$(cd "$dir" && eval "$cmd" 2>/dev/null)
  local duration booked failed
  duration=$(echo "$out" | grep "Duration:" | awk '{print $2}')
  booked=$(  echo "$out" | grep "Booked:"   | awk '{print $2}')
  failed=$(  echo "$out" | grep "Failed:"   | awk '{print $2}')
  failed="${failed:-0}"
  printf "│ %-26s │ %8s │ %10s │ %6s │\n" "$label" "$duration" "$booked" "$failed"
}

echo
echo "Running benchmarks (120 passengers per run)..."
echo
echo "┌────────────────────────────┬──────────┬────────────┬────────┐"
echo "│ Approach                   │ Duration │ Booked/120 │ Failed │"
echo "├────────────────────────────┼──────────┼────────────┼────────┤"

run "No Lock       (Python)" "$ROOT/approach1/python" ".venv/bin/python3 main.py"
run "No Lock       (Go)"     "$ROOT/approach1/go"     "go run ."
run "FOR UPDATE    (Python)" "$ROOT/approach2/python" ".venv/bin/python3 main.py"
run "FOR UPDATE    (Go)"     "$ROOT/approach2/go"     "go run ."
run "SKIP LOCKED   (Python)" "$ROOT/approach3/python" ".venv/bin/python3 main.py"
run "SKIP LOCKED   (Go)"     "$ROOT/approach3/go"     "go run ."

echo "└────────────────────────────┴──────────┴────────────┴────────┘"
echo
