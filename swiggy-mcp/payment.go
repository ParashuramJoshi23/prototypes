package main

import (
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"time"
)

// Order is a checked-out cart with a Razorpay payment link attached. The
// human pays the link; we poll Razorpay for the status. This mirrors the real
// world: the agent assembles the order, a human authorizes the money.
type Order struct {
	ID            string     `json:"id"`
	VendorName    string     `json:"vendor_name"`
	Lines         []CartLine `json:"lines"`
	Subtotal      float64    `json:"subtotal"`
	DeliveryFee   float64    `json:"delivery_fee"`
	Total         float64    `json:"total"`
	PaymentLinkID string     `json:"payment_link_id,omitempty"`
	PaymentURL    string     `json:"payment_url,omitempty"`
	PaymentID     string     `json:"payment_id,omitempty"`
	PaidVia       string     `json:"paid_via,omitempty"` // payment_link | upi_autopay
	Status        string     `json:"status"`             // PENDING_PAYMENT | PAID
}

// razorpayBase is overridable so the flow can be exercised without live keys.
var razorpayBase = "https://api.razorpay.com/v1"

func razorpayCreds() (string, string, error) {
	id := os.Getenv("RAZORPAY_KEY_ID")
	secret := os.Getenv("RAZORPAY_KEY_SECRET")
	if id == "" || secret == "" {
		return "", "", errors.New("RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set — use test-mode keys (rzp_test_...) from the Razorpay dashboard")
	}
	return id, secret, nil
}

var httpClient = &http.Client{Timeout: 15 * time.Second}

// createPaymentLink calls Razorpay's Payment Links API. With test-mode keys
// this returns a real hosted checkout URL payable with Razorpay test cards —
// real objects, real 3DS/OTP simulation, play money.
func createPaymentLink(orderID, description string, amountRupees float64) (id, url string, err error) {
	keyID, secret, err := razorpayCreds()
	if err != nil {
		return "", "", err
	}

	body := map[string]any{
		"amount":          int(amountRupees * 100), // paise
		"currency":        "INR",
		"accept_partial":  false,
		"description":     description,
		"reference_id":    orderID,
		"reminder_enable": false,
		"notify":          map[string]bool{"sms": false, "email": false},
		"notes":           map[string]string{"order_id": orderID, "source": "swiggy-mcp-poc"},
	}
	raw, _ := json.Marshal(body)

	req, _ := http.NewRequest(http.MethodPost, razorpayBase+"/payment_links", bytes.NewReader(raw))
	req.SetBasicAuth(keyID, secret)
	req.Header.Set("Content-Type", "application/json")

	resp, err := httpClient.Do(req)
	if err != nil {
		return "", "", fmt.Errorf("razorpay request failed: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 300 {
		return "", "", fmt.Errorf("razorpay error (%d): %s", resp.StatusCode, string(data))
	}

	var out struct {
		ID       string `json:"id"`
		ShortURL string `json:"short_url"`
	}
	if err := json.Unmarshal(data, &out); err != nil {
		return "", "", fmt.Errorf("decode razorpay response: %w", err)
	}
	return out.ID, out.ShortURL, nil
}

// fetchPaymentStatus returns Razorpay's status for a payment link: "created"
// (unpaid) or "paid".
func fetchPaymentStatus(linkID string) (string, error) {
	keyID, secret, err := razorpayCreds()
	if err != nil {
		return "", err
	}

	req, _ := http.NewRequest(http.MethodGet, razorpayBase+"/payment_links/"+linkID, nil)
	req.SetBasicAuth(keyID, secret)

	resp, err := httpClient.Do(req)
	if err != nil {
		return "", fmt.Errorf("razorpay request failed: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)

	if resp.StatusCode >= 300 {
		return "", fmt.Errorf("razorpay error (%d): %s", resp.StatusCode, string(data))
	}

	var out struct {
		Status string `json:"status"`
	}
	if err := json.Unmarshal(data, &out); err != nil {
		return "", fmt.Errorf("decode razorpay response: %w", err)
	}
	return out.Status, nil
}
