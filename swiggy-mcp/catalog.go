package main

import "strings"

// Item is a single orderable thing — a dish or a grocery SKU. Price is in
// rupees (we convert to paise only when we hand it to Razorpay).
type Item struct {
	ID    string  `json:"id"`
	Name  string  `json:"name"`
	Price float64 `json:"price"`
	Veg   bool    `json:"veg"`
}

// Vendor is a restaurant or a grocery store. Kind keeps the two namespaces
// separate so "search groceries" and "search restaurants" don't bleed.
type Vendor struct {
	ID       string `json:"id"`
	Name     string `json:"name"`
	Kind     string `json:"kind"` // "restaurant" | "grocery"
	Cuisine  string `json:"cuisine"`
	ETA      string `json:"eta"`
	Rating   float64
	MenuList []Item `json:"menu"`
}

// catalog is the in-memory stand-in for what would be Swiggy's backend. It is
// deliberately static seed data: the point of this POC is the agent → MCP →
// payment loop, not a real (and non-existent) Swiggy ordering API.
var catalog = []Vendor{
	{
		ID: "r_truffles", Name: "Truffles", Kind: "restaurant", Cuisine: "American", ETA: "32 min", Rating: 4.4,
		MenuList: []Item{
			{ID: "i_ckn_burger", Name: "Grilled Chicken Burger", Price: 289, Veg: false},
			{ID: "i_veg_burger", Name: "Paneer Burger", Price: 249, Veg: true},
			{ID: "i_fries", Name: "Masala Fries", Price: 149, Veg: true},
			{ID: "i_choco_shake", Name: "Chocolate Shake", Price: 179, Veg: true},
		},
	},
	{
		ID: "r_meghana", Name: "Meghana Foods", Kind: "restaurant", Cuisine: "Biryani", ETA: "41 min", Rating: 4.5,
		MenuList: []Item{
			{ID: "i_ckn_biryani", Name: "Chicken Boneless Biryani", Price: 339, Veg: false},
			{ID: "i_veg_biryani", Name: "Veg Dum Biryani", Price: 269, Veg: true},
			{ID: "i_chilli_ckn", Name: "Chilli Chicken", Price: 309, Veg: false},
		},
	},
	{
		ID: "g_instamart", Name: "Instamart", Kind: "grocery", Cuisine: "", ETA: "15 min", Rating: 4.2,
		MenuList: []Item{
			{ID: "i_milk", Name: "Amul Milk 1L", Price: 68, Veg: true},
			{ID: "i_eggs", Name: "Eggs (6 pack)", Price: 72, Veg: false},
			{ID: "i_bread", Name: "Brown Bread", Price: 55, Veg: true},
			{ID: "i_bananas", Name: "Bananas (1 dozen)", Price: 60, Veg: true},
			{ID: "i_coffee", Name: "Filter Coffee 200g", Price: 245, Veg: true},
		},
	},
}

func findVendor(id string) (*Vendor, bool) {
	for i := range catalog {
		if catalog[i].ID == id {
			return &catalog[i], true
		}
	}
	return nil, false
}

func findItem(itemID string) (*Item, *Vendor, bool) {
	for i := range catalog {
		for j := range catalog[i].MenuList {
			if catalog[i].MenuList[j].ID == itemID {
				return &catalog[i].MenuList[j], &catalog[i], true
			}
		}
	}
	return nil, nil, false
}

// searchVendors does a dumb case-insensitive substring match over vendor name
// and cuisine, scoped to a kind ("restaurant" or "grocery").
func searchVendors(query, kind string) []Vendor {
	q := strings.ToLower(strings.TrimSpace(query))
	var out []Vendor
	for _, v := range catalog {
		if v.Kind != kind {
			continue
		}
		if q == "" || strings.Contains(strings.ToLower(v.Name), q) || strings.Contains(strings.ToLower(v.Cuisine), q) {
			out = append(out, v)
		}
	}
	return out
}
