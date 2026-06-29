package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/mark3labs/mcp-go/mcp"
)

// mockRazorpay stands in for Razorpay's API so the full auto-charge path can be
// exercised without live keys or the browser-based mandate authorization. Flip
// tokenConfirmed to simulate the human approving the mandate, and
// paymentLinkPaid to simulate them paying a fallback link.
type mockRazorpay struct {
	tokenConfirmed  bool
	paymentLinkPaid bool
}

func (m *mockRazorpay) handler() http.Handler {
	mux := http.NewServeMux()

	// UPI Autopay mandate registration.
	mux.HandleFunc("/subscription_registration/auth_links", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{
			"customer_id": "cust_test",
			"order_id":    "order_auth_test",
			"short_url":   "https://rzp.test/i/mandate",
		})
	})

	// Saved tokens — confirmed only after the human authorizes.
	mux.HandleFunc("/customers/", func(w http.ResponseWriter, _ *http.Request) {
		items := []any{}
		if m.tokenConfirmed {
			items = append(items, map[string]any{
				"id":                "token_test",
				"method":            "upi",
				"recurring":         true,
				"recurring_details": map[string]any{"status": "confirmed"},
			})
		}
		writeJSON(w, map[string]any{"items": items})
	})

	// Recurring charge: order then server-to-server debit.
	mux.HandleFunc("/orders", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{"id": "order_recur_test"})
	})
	mux.HandleFunc("/payments/create/recurring", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{"razorpay_payment_id": "pay_test", "status": "captured"})
	})

	// One-off payment link (the fallback path).
	mux.HandleFunc("/payment_links", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, map[string]any{"id": "plink_test", "short_url": "https://rzp.test/i/link"})
	})
	mux.HandleFunc("/payment_links/", func(w http.ResponseWriter, _ *http.Request) {
		status := "created"
		if m.paymentLinkPaid {
			status = "paid"
		}
		writeJSON(w, map[string]any{"status": status})
	})

	return mux
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	_ = json.NewEncoder(w).Encode(v)
}

// --- test helpers ---

func newReq(args map[string]any) mcp.CallToolRequest {
	var r mcp.CallToolRequest
	r.Params.Arguments = args
	return r
}

func resultText(t *testing.T, res *mcp.CallToolResult) string {
	t.Helper()
	for _, c := range res.Content {
		if tc, ok := c.(mcp.TextContent); ok {
			return tc.Text
		}
	}
	t.Fatalf("result had no text content")
	return ""
}

func resultJSON(t *testing.T, res *mcp.CallToolResult) map[string]any {
	t.Helper()
	if res.IsError {
		t.Fatalf("tool returned error: %s", resultText(t, res))
	}
	var m map[string]any
	if err := json.Unmarshal([]byte(resultText(t, res)), &m); err != nil {
		t.Fatalf("result was not JSON: %v\n%s", err, resultText(t, res))
	}
	return m
}

// TestAutopayEndToEnd walks the entire mandate lifecycle against the mock:
// setup -> pending -> authorize -> active -> auto-charge within limits ->
// over-limit fallback to a payment link -> link paid.
func TestAutopayEndToEnd(t *testing.T) {
	mock := &mockRazorpay{}
	ts := httptest.NewServer(mock.handler())
	defer ts.Close()

	oldBase := razorpayBase
	razorpayBase = ts.URL
	defer func() { razorpayBase = oldBase }()
	t.Setenv("RAZORPAY_KEY_ID", "rzp_test_x")
	t.Setenv("RAZORPAY_KEY_SECRET", "secret")

	db = newStore()
	defer func() { db = newStore() }()
	ctx := context.Background()

	// 1. Set up the mandate: max ₹500/order, ₹1000 total.
	res, _ := handleSetupAutopay(ctx, newReq(map[string]any{
		"max_per_order": 500.0, "total_budget": 1000.0,
		"name": "Test", "email": "t@example.com", "contact": "+919876543210",
	}))
	out := resultJSON(t, res)
	if got := out["mandate"].(map[string]any)["status"]; got != "PENDING_AUTH" {
		t.Fatalf("want PENDING_AUTH, got %v", got)
	}

	// 2. Before the human approves, the mandate stays pending.
	res, _ = handleCheckAutopay(ctx, newReq(nil))
	if got := resultJSON(t, res)["mandate"].(map[string]any)["status"]; got != "PENDING_AUTH" {
		t.Fatalf("want still PENDING_AUTH, got %v", got)
	}

	// 3. Human approves -> token confirmed -> mandate goes ACTIVE.
	mock.tokenConfirmed = true
	res, _ = handleCheckAutopay(ctx, newReq(nil))
	if got := resultJSON(t, res)["mandate"].(map[string]any)["status"]; got != "ACTIVE" {
		t.Fatalf("want ACTIVE after auth, got %v", got)
	}

	// 4. Order within limits (₹269 + ₹35 = ₹304) auto-charges, no human step.
	if _, err := db.addToCart("default", "i_veg_biryani", 1); err != nil {
		t.Fatalf("add: %v", err)
	}
	res, _ = handleCheckout(ctx, newReq(nil))
	out = resultJSON(t, res)
	if out["paid_automatically"] != true {
		t.Fatalf("want paid_automatically=true, got %v", out["paid_automatically"])
	}
	order := out["order"].(map[string]any)
	if order["status"] != "PAID" || order["paid_via"] != "upi_autopay" {
		t.Fatalf("want PAID via upi_autopay, got %v / %v", order["status"], order["paid_via"])
	}
	if got := out["remaining_budget"].(float64); got != 1000-304 {
		t.Fatalf("want remaining 696, got %v", got)
	}

	// 5. Order over the per-order cap (₹339*2 + ₹35 = ₹713) falls back to a link.
	if _, err := db.addToCart("default", "i_ckn_biryani", 2); err != nil {
		t.Fatalf("add: %v", err)
	}
	res, _ = handleCheckout(ctx, newReq(nil))
	out = resultJSON(t, res)
	order = out["order"].(map[string]any)
	if order["status"] != "PENDING_PAYMENT" || order["paid_via"] != "payment_link" {
		t.Fatalf("want PENDING_PAYMENT via payment_link, got %v / %v", order["status"], order["paid_via"])
	}
	skipped, _ := out["autopay_skipped"].(string)
	if !strings.Contains(skipped, "per-order cap") {
		t.Fatalf("want autopay_skipped to cite per-order cap, got %q", skipped)
	}
	orderID := order["id"].(string)

	// 6. Human pays the fallback link -> status flips to PAID.
	mock.paymentLinkPaid = true
	res, _ = handleCheckPaymentStatus(ctx, newReq(map[string]any{"order_id": orderID}))
	if got := resultJSON(t, res)["status"]; got != "PAID" {
		t.Fatalf("want PAID after link paid, got %v", got)
	}
}
