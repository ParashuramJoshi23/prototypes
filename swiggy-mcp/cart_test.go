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

func TestCheckoutNeedsRazorpayKeys(t *testing.T) {
	t.Setenv("RAZORPAY_KEY_ID", "")
	t.Setenv("RAZORPAY_KEY_SECRET", "")
	if _, _, err := createPaymentLink("ord_1", "test", 100); err == nil {
		t.Fatal("expected error when keys are missing")
	}
}
