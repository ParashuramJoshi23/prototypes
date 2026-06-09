package main

import (
	"fmt"
	"net"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"sync"

	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promhttp"
	"golang.org/x/time/rate"
)

var gwRequests = prometheus.NewCounterVec(prometheus.CounterOpts{
	Name: "gateway_requests_total",
	Help: "Requests handled by the API gateway, by status code class.",
}, []string{"status"})

func init() { prometheus.MustRegister(gwRequests) }

func main() {
	target := envOr("LB_URL", "http://lb:8081")

	// per-IP token bucket: 20 req/s, burst 10
	var mu sync.Mutex
	limiters := map[string]*rate.Limiter{}
	limiter := func(ip string) *rate.Limiter {
		mu.Lock()
		defer mu.Unlock()
		if l, ok := limiters[ip]; ok {
			return l
		}
		l := rate.NewLimiter(20, 10)
		limiters[ip] = l
		return l
	}

	u, _ := url.Parse(target)
	proxy := httputil.NewSingleHostReverseProxy(u)

	mux := http.NewServeMux()
	mux.HandleFunc("/", func(w http.ResponseWriter, r *http.Request) {
		ip, _, _ := net.SplitHostPort(r.RemoteAddr)
		if !limiter(ip).Allow() {
			gwRequests.WithLabelValues("429").Inc()
			http.Error(w, "rate limited", http.StatusTooManyRequests)
			return
		}
		gwRequests.WithLabelValues("2xx").Inc()
		proxy.ServeHTTP(w, r)
	})

	go func() {
		fmt.Println("gateway metrics :9100")
		metricsMux := http.NewServeMux()
		metricsMux.Handle("/metrics", promhttp.Handler())
		http.ListenAndServe(":9100", metricsMux)
	}()

	fmt.Printf("gateway :8080 → %s\n", target)
	http.ListenAndServe(":8080", mux)
}

func envOr(key, def string) string {
	if v := os.Getenv(key); v != "" {
		return v
	}
	return def
}
