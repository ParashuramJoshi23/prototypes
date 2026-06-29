package main

import (
	"bytes"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"time"
)

// razorpayPost / razorpayGet centralize auth + error handling for the recurring
// endpoints (the one-shot Payment Links calls in payment.go predate these).
func razorpayPost(path string, body any, out any) error {
	keyID, secret, err := razorpayCreds()
	if err != nil {
		return err
	}
	raw, _ := json.Marshal(body)
	req, _ := http.NewRequest(http.MethodPost, razorpayBase+path, bytes.NewReader(raw))
	req.SetBasicAuth(keyID, secret)
	req.Header.Set("Content-Type", "application/json")
	return razorpayDo(req, out)
}

func razorpayGet(path string, out any) error {
	keyID, secret, err := razorpayCreds()
	if err != nil {
		return err
	}
	req, _ := http.NewRequest(http.MethodGet, razorpayBase+path, nil)
	req.SetBasicAuth(keyID, secret)
	return razorpayDo(req, out)
}

func razorpayDo(req *http.Request, out any) error {
	resp, err := httpClient.Do(req)
	if err != nil {
		return fmt.Errorf("razorpay request failed: %w", err)
	}
	defer resp.Body.Close()
	data, _ := io.ReadAll(resp.Body)
	if resp.StatusCode >= 300 {
		return fmt.Errorf("razorpay error (%d): %s", resp.StatusCode, string(data))
	}
	if out != nil {
		if err := json.Unmarshal(data, out); err != nil {
			return fmt.Errorf("decode razorpay response: %w", err)
		}
	}
	return nil
}

// createAutopayRegistration creates a UPI Autopay authorization link via
// Razorpay's recurring registration API. The human opens the returned URL once
// and approves the mandate in their UPI app (test mode in the sandbox). It
// yields a customer_id and an auth order_id; the recurring token appears after
// the human authorizes (fetch it with fetchMandateToken).
func createAutopayRegistration(m *Mandate) (customerID, orderID, authURL string, err error) {
	body := map[string]any{
		"customer": map[string]string{
			"name":    m.Name,
			"email":   m.Email,
			"contact": m.Contact,
		},
		"type":        "link",
		"amount":      0, // ₹0 authorization — no first charge, just set up the mandate
		"currency":    "INR",
		"description": "swiggy-mcp UPI Autopay mandate",
		"subscription_registration": map[string]any{
			"method":     "upi",
			"max_amount": int(m.MaxPerOrder * 100), // paise, per-debit cap
			"expire_at":  time.Now().AddDate(1, 0, 0).Unix(),
			"frequency":  "as_presented", // variable amounts, charged on demand
		},
		"receipt":      m.ID,
		"email_notify": 0,
		"sms_notify":   0,
		"notes":        map[string]string{"source": "swiggy-mcp-poc", "mandate_id": m.ID},
	}

	var out struct {
		CustomerID string `json:"customer_id"`
		OrderID    string `json:"order_id"`
		ShortURL   string `json:"short_url"`
	}
	if err := razorpayPost("/subscription_registration/auth_links", body, &out); err != nil {
		return "", "", "", err
	}
	return out.CustomerID, out.OrderID, out.ShortURL, nil
}

// fetchMandateToken looks for a confirmed recurring UPI token on the customer.
// Until the human authorizes, no confirmed token exists and status is "pending".
func fetchMandateToken(customerID string) (tokenID, status string, err error) {
	var out struct {
		Items []struct {
			ID              string `json:"id"`
			Method          string `json:"method"`
			Recurring       bool   `json:"recurring"`
			RecurringDetail struct {
				Status string `json:"status"`
			} `json:"recurring_details"`
		} `json:"items"`
	}
	if err := razorpayGet("/customers/"+customerID+"/tokens", &out); err != nil {
		return "", "", err
	}
	for _, t := range out.Items {
		if t.Recurring && t.RecurringDetail.Status == "confirmed" {
			return t.ID, "confirmed", nil
		}
	}
	return "", "pending", nil
}

// chargeRecurring debits the mandate server-to-server — no human interaction.
// It creates an auto-captured order, then a recurring payment against the saved
// token. This is the step that makes the agent autonomous within its cap.
func chargeRecurring(m *Mandate, amountRupees float64, desc, refID string) (paymentID, status string, err error) {
	var order struct {
		ID string `json:"id"`
	}
	orderBody := map[string]any{
		"amount":          int(amountRupees * 100),
		"currency":        "INR",
		"receipt":         refID,
		"payment_capture": true,
		"notes":           map[string]string{"source": "swiggy-mcp-poc", "mandate_id": m.ID},
	}
	if err := razorpayPost("/orders", orderBody, &order); err != nil {
		return "", "", fmt.Errorf("create recurring order: %w", err)
	}

	var pay struct {
		PaymentID string `json:"razorpay_payment_id"`
		Status    string `json:"status"`
	}
	payBody := map[string]any{
		"email":       m.Email,
		"contact":     m.Contact,
		"amount":      int(amountRupees * 100),
		"currency":    "INR",
		"order_id":    order.ID,
		"customer_id": m.CustomerID,
		"token":       m.TokenID,
		"recurring":   "1",
		"description": desc,
	}
	if err := razorpayPost("/payments/create/recurring", payBody, &pay); err != nil {
		return "", "", fmt.Errorf("create recurring payment: %w", err)
	}
	return pay.PaymentID, pay.Status, nil
}
