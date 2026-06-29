package main

import (
	"errors"
	"sync"
)

// CartLine is one item plus quantity in the cart.
type CartLine struct {
	ItemID   string  `json:"item_id"`
	Name     string  `json:"name"`
	Price    float64 `json:"price"`
	Quantity int     `json:"quantity"`
}

// Cart is a single in-progress order. A cart is pinned to one vendor — you
// can't mix a biryani place and a grocery store in one Swiggy order, so we
// enforce that here too.
type Cart struct {
	VendorID   string     `json:"vendor_id"`
	VendorName string     `json:"vendor_name"`
	Lines      []CartLine `json:"lines"`
}

func (c *Cart) subtotal() float64 {
	var t float64
	for _, l := range c.Lines {
		t += l.Price * float64(l.Quantity)
	}
	return t
}

// store holds carts and placed orders in memory, keyed by session. This is a
// prototype: restart = clean slate. A real service would back this with Redis
// or Postgres.
type store struct {
	mu     sync.Mutex
	carts  map[string]*Cart
	orders map[string]*Order
}

func newStore() *store {
	return &store{carts: map[string]*Cart{}, orders: map[string]*Order{}}
}

var errVendorMismatch = errors.New("cart already has items from a different vendor; clear it first")

func (s *store) addToCart(session, itemID string, qty int) (*Cart, error) {
	if qty < 1 {
		qty = 1
	}
	item, vendor, ok := findItem(itemID)
	if !ok {
		return nil, errors.New("unknown item id: " + itemID)
	}

	s.mu.Lock()
	defer s.mu.Unlock()

	cart := s.carts[session]
	if cart == nil {
		cart = &Cart{VendorID: vendor.ID, VendorName: vendor.Name}
		s.carts[session] = cart
	}
	if cart.VendorID != vendor.ID {
		return nil, errVendorMismatch
	}

	for i := range cart.Lines {
		if cart.Lines[i].ItemID == itemID {
			cart.Lines[i].Quantity += qty
			return cart, nil
		}
	}
	cart.Lines = append(cart.Lines, CartLine{ItemID: item.ID, Name: item.Name, Price: item.Price, Quantity: qty})
	return cart, nil
}

func (s *store) getCart(session string) *Cart {
	s.mu.Lock()
	defer s.mu.Unlock()
	return s.carts[session]
}

func (s *store) clearCart(session string) {
	s.mu.Lock()
	defer s.mu.Unlock()
	delete(s.carts, session)
}
