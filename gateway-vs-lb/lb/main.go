package main

import (
	"fmt"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"sync/atomic"
	"time"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
)

var (
	lbUpstreamHealthy = prometheus.NewGaugeVec(prometheus.GaugeOpts{
		Name: "lb_upstream_healthy",
		Help: "1 if backend is passing health checks, 0 if down.",
	}, []string{"backend"})

	lbRequests = prometheus.NewCounterVec(prometheus.CounterOpts{
		Name: "lb_requests_total",
		Help: "Requests forwarded by the load balancer, by backend and outcome.",
	}, []string{"backend", "outcome"})
)

func init() { prometheus.MustRegister(lbUpstreamHealthy, lbRequests) }

type upstream struct {
	name   string
	rawURL string
	proxy  *httputil.ReverseProxy
	up     atomic.Bool
}

func (u *upstream) healthCheck(client *http.Client) {
	resp, err := client.Get(u.rawURL + "/health")
	healthy := err == nil && resp.StatusCode == 200
	prev := u.up.Swap(healthy)
	if healthy != prev {
		v := 0.0
		if healthy {
			v = 1.0
		}
		lbUpstreamHealthy.WithLabelValues(u.name).Set(v)
		fmt.Printf("[lb] %s → healthy=%v\n", u.name, healthy)
	}
}

func main() {
	addrs := strings.Split(envOr("BACKENDS", "http://backend-a:8082,http://backend-b:8082"), ",")

	ups := make([]*upstream, len(addrs))
	for i, addr := range addrs {
		u, _ := url.Parse(strings.TrimSpace(addr))
		up := &upstream{name: u.Hostname(), rawURL: strings.TrimSpace(addr)}
		up.up.Store(true)
		lbUpstreamHealthy.WithLabelValues(up.name).Set(1)

		captured := up
		rp := httputil.NewSingleHostReverseProxy(u)
		rp.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
			lbRequests.WithLabelValues(captured.name, "error").Inc()
			http.Error(w, "upstream error", http.StatusBadGateway)
		}
		up.proxy = rp
		ups[i] = up
	}

	client := &http.Client{Timeout: 2 * time.Second}
	go func() {
		for range time.Tick(3 * time.Second) {
			for _, up := range ups {
				up.healthCheck(client)
			}
		}
	}()

	var counter atomic.Uint64
	n := uint64(len(ups))

	mux := http.NewServeMux()
	mux.HandleFunc("/health", func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(200)
	})
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		for range ups {
			idx := counter.Add(1) % n
			up := ups[idx]
			if !up.up.Load() {
				continue
			}
			up.proxy.ServeHTTP(w, r)
			lbRequests.WithLabelValues(up.name, "ok").Inc()
			return
		}
		lbRequests.WithLabelValues("none", "no_healthy_upstream").Inc()
		http.Error(w, "no healthy upstream", http.StatusServiceUnavailable)
	})

	go func() {
		fmt.Println("lb metrics :9101")
		metricsMux := http.NewServeMux()
		metricsMux.Handle("/metrics", promhttp.Handler())
		http.ListenAndServe(":9101", metricsMux)
	}()

	fmt.Printf("lb :8081, backends: %v\n", addrs)
	http.ListenAndServe(":8081", mux)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
