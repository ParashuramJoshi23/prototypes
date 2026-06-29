package main

import (
	"fmt"
	"sync/atomic"
	"time"
)

// Mandate is a UPI Autopay authorization: the human approves it once (one UPI
// PIN), which lets the agent auto-charge recurring debits up to a cap without
// asking again. This is the actual primitive behind "agentic" spending —
// pre-authorized, bounded autonomy.
//
//   - MaxPerOrder caps a single auto-charge.
//   - TotalBudget caps cumulative auto-spend over the mandate's life.
//
// Anything outside those bounds falls back to the human-approved payment link.
type Mandate struct {
	ID          string  `json:"id"`
	CustomerID  string  `json:"customer_id"`
	AuthOrderID string  `json:"auth_order_id"`
	TokenID     string  `json:"token_id,omitempty"`
	AuthURL     string  `json:"auth_url,omitempty"`
	Name        string  `json:"-"`
	Email       string  `json:"-"`
	Contact     string  `json:"-"`
	MaxPerOrder float64 `json:"max_per_order"`
	TotalBudget float64 `json:"total_budget"`
	Spent       float64 `json:"spent"`
	Status      string  `json:"status"` // PENDING_AUTH | ACTIVE | EXHAUSTED
}

// upiAutopayAFACap is NPCI's per-transaction additional-factor-of-auth
// threshold for UPI Autopay: debits at or below this run without the user's PIN
// once the mandate is set up; above it, each charge needs the PIN again. We
// don't hard-block above it (it varies by category), but we warn.
const upiAutopayAFACap = 15000.0

func (m *Mandate) remaining() float64 { return m.TotalBudget - m.Spent }

// canCover reports whether an order total can be auto-charged on this mandate,
// and if not, a human-readable reason for the fallback.
func (m *Mandate) canCover(total float64) (bool, string) {
	if m.Status != "ACTIVE" {
		return false, fmt.Sprintf("mandate is %s, not ACTIVE", m.Status)
	}
	if total > m.MaxPerOrder {
		return false, fmt.Sprintf("order ₹%.2f exceeds per-order cap ₹%.2f", total, m.MaxPerOrder)
	}
	if total > m.remaining() {
		return false, fmt.Sprintf("order ₹%.2f exceeds remaining budget ₹%.2f", total, m.remaining())
	}
	return true, ""
}

var mandateSeq int64

func genMandateID() string {
	n := atomic.AddInt64(&mandateSeq, 1)
	return fmt.Sprintf("mdt_%d%03d", time.Now().Unix(), n)
}

func (s *store) setMandate(session string, m *Mandate) {
	s.mu.Lock()
	defer s.mu.Unlock()
	s.mandates[session] = m
}

func (s *store) getMandate(session string) *Mandate {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.mandates[session]
}

// recordSpend deducts an auto-charge from the mandate's budget and marks it
// EXHAUSTED once it can no longer cover even a token order.
func (s *store) recordSpend(session string, amount float64) {
	s.mu.Lock()
	defer s.mu.Unlock()
	m := s.mandates[session]
	if m == nil {
		return
	}
	m.Spent += amount
	if m.remaining() <= 0 {
		m.Status = "EXHAUSTED"
	}
}
