.PHONY: up down flood kill-a revive-a kill-b revive-b metrics

up:
	docker compose up --build -d
	@echo "Ready. Try: make metrics"

down:
	docker compose down

# Trigger rate limiting at the gateway layer
flood:
	@echo "==> Flooding gateway (50 parallel, 500 requests)..."
	@seq 1 500 | xargs -P 50 -I{} curl -sf http://localhost:8080/ -o /dev/null -w "%{http_code}\n" | sort | uniq -c
	@echo ""
	@echo "==> gateway_requests_total should show 429s:"
	@curl -sf http://localhost:9100/metrics | grep "^gateway_requests_total"

# Inject LB-layer failure: take down one backend
kill-a:
	@echo "==> Stopping backend-a..."
	docker compose stop backend-a
	@echo "==> Wait ~5s for LB health check, then: make metrics"
	@echo "==> Look for: lb_upstream_healthy{backend=\"backend-a\"} 0"

revive-a:
	docker compose start backend-a

kill-b:
	docker compose stop backend-b

revive-b:
	docker compose start backend-b

# Show metrics from each layer separately — the key output of this prototype
metrics:
	@printf "\n\033[1;33m=== API GATEWAY — rate limiting, request totals ===\033[0m\n"
	@curl -sf http://localhost:9100/metrics | grep -E "^gateway_" || echo "(no data yet)"
	@printf "\n\033[1;33m=== LOAD BALANCER — upstream health + distribution ===\033[0m\n"
	@curl -sf http://localhost:9101/metrics | grep -E "^lb_" || echo "(no data yet)"
	@printf "\n\033[1;33m=== BACKEND-A ===\033[0m\n"
	@curl -sf http://localhost:9102/metrics | grep -E "^backend_" 2>/dev/null || echo "(down)"
	@printf "\n\033[1;33m=== BACKEND-B ===\033[0m\n"
	@curl -sf http://localhost:9103/metrics | grep -E "^backend_" 2>/dev/null || echo "(down)"
	@printf "\n\033[1;32mPrometheus UI: http://localhost:9090\033[0m\n"
