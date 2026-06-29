package main

import "testing"

func TestAddToCartAccumulatesQuantity(t *testing.T) {
	s := newStore()
	if _, err := s.addToCart("u1", "i_fries", 1); err != nil {
		t.Fatalf("add: %v", err)
	}
	cart, err := s.addToCart("u1", "i_fries", 2)
	if err != nil {
		t.Fatalf("add again: %v", err)
	}
	if len(cart.Lines) != 1 {
		t.Fatalf("want 1 line, got %d", len(cart.Lines))
	}
	if cart.Lines[0].Quantity != 3 {
		t.Fatalf("want qty 3, got %d", cart.Lines[0].Quantity)
	}
}

func TestAddToCartRejectsMixedVendors(t *testing.T) {
	s := newStore()
	if _, err := s.addToCart("u1", "i_fries", 1); err != nil { // Truffles
		t.Fatalf("add: %v", err)
	}
	if _, err := s.addToCart("u1", "i_milk", 1); err != errVendorMismatch { // Instamart
		t.Fatalf("want errVendorMismatch, got %v", err)
	}
}

func TestSubtotal(t *testing.T) {
	s := newStore()
	s.addToCart("u1", "i_veg_biryani", 2) // 269 each
	s.addToCart("u1", "i_chilli_ckn", 1)  // 309
	cart := s.getCart("u1")
	if got := cart.subtotal(); got != 269*2+309 {
		t.Fatalf("want %v, got %v", 269*2+309, got)
	}
}

func TestSearchScopedByKind(t *testing.T) {
	if got := searchVendors("biryani", "restaurant"); len(got) != 1 {
		t.Fatalf("want 1 restaurant, got %d", len(got))
	}
	if got := searchVendors("biryani", "grocery"); len(got) != 0 {
		t.Fatalf("want 0 groceries, got %d", len(got))
	}
}

func TestMandateCanCover(t *testing.T) {
	m := &Mandate{Status: "ACTIVE", MaxPerOrder: 500, TotalBudget: 2000, Spent: 1800}

	if ok, _ := m.canCover(150); !ok {
		t.Fatal("₹150 should be coverable (under per-order cap and remaining ₹200)")
	}
	if ok, reason := m.canCover(600); ok {
		t.Fatalf("₹600 exceeds per-order cap, want skip; reason=%q", reason)
	}
	if ok, reason := m.canCover(300); ok {
		t.Fatalf("₹300 exceeds remaining ₹200 budget, want skip; reason=%q", reason)
	}

	m.Status = "PENDING_AUTH"
	if ok, _ := m.canCover(100); ok {
		t.Fatal("inactive mandate should never cover")
	}
}

func TestRecordSpendExhaustsMandate(t *testing.T) {
	s := newStore()
	s.setMandate("u1", &Mandate{Status: "ACTIVE", MaxPerOrder: 500, TotalBudget: 500})
	s.recordSpend("u1", 500)
	if got := s.getMandate("u1").Status; got != "EXHAUSTED" {
		t.Fatalf("want EXHAUSTED after spending full budget, got %s", got)
	}
}

func TestSetupAutopayNeedsRazorpayKeys(t *testing.T) {
	t.Setenv("RAZORPAY_KEY_ID", "")
	t.Setenv("RAZORPAY_KEY_SECRET", "")
	if _, _, _, err := createAutopayRegistration(&Mandate{ID: "mdt_1", MaxPerOrder: 500}); err == nil {
		t.Fatal("expected error when keys are missing")
	}
}

func TestCheckoutNeedsRazorpayKeys(t *testing.T) {
	t.Setenv("RAZORPAY_KEY_ID", "")
	t.Setenv("RAZORPAY_KEY_SECRET", "")
	if _, _, err := createPaymentLink("ord_1", "test", 100); err == nil {
		t.Fatal("expected error when keys are missing")
	}
}
