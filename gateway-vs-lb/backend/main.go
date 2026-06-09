package main

import (
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"sync/atomic"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var backendRequests = prometheus.NewCounterVec(prometheus.CounterOpts{
	Name: "backend_requests_total",
	Help: "Total requests handled by this backend instance.",
}, []string{"name"})

func init() { prometheus.MustRegister(backendRequests) }

func main() {
	name := envOr("BACKEND_NAME", "backend")
	var count atomic.Int64

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(200)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		n := count.Add(1)
		backendRequests.WithLabelValues(name).Inc()
		w.Header().Set("Content-Type", "application/json")
		json.NewEncoder(w).Encode(map[string]any{
			"backend": name,
			"count":   n,
			"path":    r.URL.Path,
		})
	})

	go func() {
		fmt.Printf("backend %s metrics :9102\n", name)
		metricsMux := http.NewServeMux()
		metricsMux.Handle("/metrics", promhttp.Handler())
		http.ListenAndServe(":9102", metricsMux)
	}()

	fmt.Printf("backend %s :8082\n", name)
	http.ListenAndServe(":8082", mux)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
