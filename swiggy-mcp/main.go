// Command swiggy-mcp is a prototype MCP server that models the Swiggy ordering
// flow — search a vendor, build a cart, check out — and settles payment through
// Razorpay (test mode): either a one-off payment link the human pays, or a UPI
// Autopay mandate the agent charges autonomously within pre-approved limits.
//
// It does NOT talk to Swiggy. Swiggy publishes no public ordering or payment
// API, and Indian payment rails require the human to authorize every charge
// (UPI PIN / card OTP) — except under a UPI Autopay mandate the human approves
// once, which is the actual primitive behind bounded agentic spending. So the
// catalog is seed data and the only real external calls are to Razorpay.
package main

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync/atomic"
	"time"

	"github.com/mark3labs/mcp-go/mcp"
	"github.com/mark3labs/mcp-go/server"
)

var db = newStore()

var orderSeq int64

func genOrderID() string {
	n := atomic.AddInt64(&orderSeq, 1)
	return fmt.Sprintf("ord_%d%03d", time.Now().Unix(), n)
}

// jsonResult marshals v and wraps it as a tool text result.
func jsonResult(v any) *mcp.CallToolResult {
	b, err := json.MarshalIndent(v, "", "  ")
	if err != nil {
		return mcp.NewToolResultError("encode result: " + err.Error())
	}
	return mcp.NewToolResultText(string(b))
}

func session(req mcp.CallToolRequest) string {
	return req.GetString("session", "default")
}

func main() {
	s := server.NewMCPServer("swiggy-mcp", "0.1.0",
		server.WithToolCapabilities(true),
		server.WithInstructions(
			"Order food or groceries. Flow: search_restaurants/search_groceries → get_menu "+
				"→ add_to_cart → view_cart → checkout. checkout returns a Razorpay payment "+
				"link the HUMAN must open and pay (test-mode card). Then poll check_payment_status "+
				"until it reports PAID. The agent never completes the payment itself."),
	)

	s.AddTool(mcp.NewTool("search_restaurants",
		mcp.WithDescription("Search restaurants by name or cuisine. Empty query lists all."),
		mcp.WithString("query", mcp.Description("Name or cuisine, e.g. 'biryani'")),
	), handleSearchRestaurants)

	s.AddTool(mcp.NewTool("search_groceries",
		mcp.WithDescription("Search grocery stores by name. Empty query lists all."),
		mcp.WithString("query", mcp.Description("Store name, e.g. 'instamart'")),
	), handleSearchGroceries)

	s.AddTool(mcp.NewTool("get_menu",
		mcp.WithDescription("List the items (with ids and prices) for a vendor."),
		mcp.WithString("vendor_id", mcp.Required(), mcp.Description("Vendor id from a search result")),
	), handleGetMenu)

	s.AddTool(mcp.NewTool("add_to_cart",
		mcp.WithDescription("Add an item to the cart. A cart is pinned to one vendor."),
		mcp.WithString("item_id", mcp.Required(), mcp.Description("Item id from get_menu")),
		mcp.WithNumber("quantity", mcp.Description("Quantity (default 1)")),
		mcp.WithString("session", mcp.Description("Cart session id (default 'default')")),
	), handleAddToCart)

	s.AddTool(mcp.NewTool("view_cart",
		mcp.WithDescription("Show the current cart and subtotal."),
		mcp.WithString("session", mcp.Description("Cart session id (default 'default')")),
	), handleViewCart)

	s.AddTool(mcp.NewTool("clear_cart",
		mcp.WithDescription("Empty the cart (e.g. to switch vendors)."),
		mcp.WithString("session", mcp.Description("Cart session id (default 'default')")),
	), handleClearCart)

	s.AddTool(mcp.NewTool("checkout",
		mcp.WithDescription("Place the order: creates a Razorpay test-mode payment link. "+
			"Returns a URL the human must open and pay. Does NOT charge automatically."),
		mcp.WithString("session", mcp.Description("Cart session id (default 'default')")),
	), handleCheckout)

	s.AddTool(mcp.NewTool("check_payment_status",
		mcp.WithDescription("Poll Razorpay for an order's payment status. Returns PENDING_PAYMENT or PAID."),
		mcp.WithString("order_id", mcp.Required(), mcp.Description("Order id from checkout")),
	), handleCheckPaymentStatus)

	s.AddTool(mcp.NewTool("setup_autopay",
		mcp.WithDescription("Set up a UPI Autopay mandate so future orders within the limits "+
			"are charged automatically with no per-order approval. Returns a link the HUMAN "+
			"opens ONCE to approve the mandate (one UPI PIN). Then call check_autopay."),
		mcp.WithNumber("max_per_order", mcp.Required(), mcp.Description("Max rupees auto-charged for a single order")),
		mcp.WithNumber("total_budget", mcp.Required(), mcp.Description("Max cumulative rupees this mandate may auto-spend")),
		mcp.WithString("name", mcp.Required(), mcp.Description("Customer name")),
		mcp.WithString("email", mcp.Required(), mcp.Description("Customer email")),
		mcp.WithString("contact", mcp.Required(), mcp.Description("Customer phone, e.g. +919876543210")),
		mcp.WithString("session", mcp.Description("Cart session id (default 'default')")),
	), handleSetupAutopay)

	s.AddTool(mcp.NewTool("check_autopay",
		mcp.WithDescription("Check the UPI Autopay mandate: PENDING_AUTH, ACTIVE, or EXHAUSTED, "+
			"plus remaining budget. Marks it ACTIVE once the human has approved it."),
		mcp.WithString("session", mcp.Description("Cart session id (default 'default')")),
	), handleCheckAutopay)

	if err := server.ServeStdio(s); err != nil {
		log.Fatalf("swiggy-mcp server error: %v", err)
	}
}

func handleSearchRestaurants(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	return jsonResult(searchVendors(req.GetString("query", ""), "restaurant")), nil
}

func handleSearchGroceries(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	return jsonResult(searchVendors(req.GetString("query", ""), "grocery")), nil
}

func handleGetMenu(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	id, err := req.RequireString("vendor_id")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	v, ok := findVendor(id)
	if !ok {
		return mcp.NewToolResultError("unknown vendor id: " + id), nil
	}
	return jsonResult(v), nil
}

func handleAddToCart(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	itemID, err := req.RequireString("item_id")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	cart, err := db.addToCart(session(req), itemID, req.GetInt("quantity", 1))
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	return jsonResult(cart), nil
}

func handleViewCart(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	cart := db.getCart(session(req))
	if cart == nil || len(cart.Lines) == 0 {
		return mcp.NewToolResultText("Cart is empty."), nil
	}
	return jsonResult(map[string]any{"cart": cart, "subtotal": cart.subtotal()}), nil
}

func handleClearCart(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	db.clearCart(session(req))
	return mcp.NewToolResultText("Cart cleared."), nil
}

const deliveryFee = 35.0

func handleCheckout(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	sess := session(req)
	cart := db.getCart(sess)
	if cart == nil || len(cart.Lines) == 0 {
		return mcp.NewToolResultError("cart is empty — nothing to check out"), nil
	}

	subtotal := cart.subtotal()
	total := subtotal + deliveryFee
	orderID := genOrderID()
	desc := fmt.Sprintf("Swiggy MCP order from %s", cart.VendorName)

	order := &Order{
		ID:          orderID,
		VendorName:  cart.VendorName,
		Lines:       cart.Lines,
		Subtotal:    subtotal,
		DeliveryFee: deliveryFee,
		Total:       total,
	}

	// If an Autopay mandate can cover this order, charge it automatically —
	// no human step. This is the agentic path: bounded, pre-authorized spend.
	if m := db.getMandate(sess); m != nil {
		if ok, _ := m.canCover(total); ok {
			payID, status, err := chargeRecurring(m, total, desc, orderID)
			if err != nil {
				return mcp.NewToolResultError("autopay charge failed: " + err.Error()), nil
			}
			db.recordSpend(sess, total)
			order.Status = "PAID"
			order.PaymentID = payID
			order.PaidVia = "upi_autopay"
			storeOrder(order)
			db.clearCart(sess)
			return jsonResult(map[string]any{
				"order":              order,
				"paid_automatically": true,
				"razorpay_status":    status,
				"remaining_budget":   m.remaining(),
				"note":               "Charged on UPI Autopay mandate — no approval needed.",
			}), nil
		}
	}

	// Fallback: human-approved payment link.
	linkID, url, err := createPaymentLink(orderID, desc, total)
	if err != nil {
		return mcp.NewToolResultError("could not create payment link: " + err.Error()), nil
	}
	order.PaymentLinkID = linkID
	order.PaymentURL = url
	order.Status = "PENDING_PAYMENT"
	order.PaidVia = "payment_link"
	storeOrder(order)
	db.clearCart(sess)

	resp := map[string]any{
		"order":           order,
		"action_required": "Open payment_url and pay with a Razorpay test card, then call check_payment_status.",
		"test_card":       "4111 1111 1111 1111, any future expiry, any CVV, OTP 1234 (Razorpay test mode)",
	}
	// Explain why we didn't use autopay, if a mandate exists but couldn't cover it.
	if m := db.getMandate(sess); m != nil {
		if ok, reason := m.canCover(total); !ok {
			resp["autopay_skipped"] = reason
		}
	}
	return jsonResult(resp), nil
}

func storeOrder(o *Order) {
	db.mu.Lock()
	db.orders[o.ID] = o
	db.mu.Unlock()
}

func handleSetupAutopay(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	maxPerOrder := req.GetFloat("max_per_order", 0)
	totalBudget := req.GetFloat("total_budget", 0)
	if maxPerOrder <= 0 || totalBudget <= 0 {
		return mcp.NewToolResultError("max_per_order and total_budget must be positive"), nil
	}
	name, err := req.RequireString("name")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	email, err := req.RequireString("email")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}
	contact, err := req.RequireString("contact")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}

	m := &Mandate{
		ID:          genMandateID(),
		Name:        name,
		Email:       email,
		Contact:     contact,
		MaxPerOrder: maxPerOrder,
		TotalBudget: totalBudget,
		Status:      "PENDING_AUTH",
	}
	custID, orderID, authURL, err := createAutopayRegistration(m)
	if err != nil {
		return mcp.NewToolResultError("could not create autopay mandate: " + err.Error()), nil
	}
	m.CustomerID = custID
	m.AuthOrderID = orderID
	m.AuthURL = authURL
	db.setMandate(session(req), m)

	resp := map[string]any{
		"mandate":         m,
		"action_required": "Open auth_url ONCE and approve the UPI Autopay mandate, then call check_autopay.",
	}
	if maxPerOrder > upiAutopayAFACap {
		resp["warning"] = fmt.Sprintf(
			"max_per_order ₹%.0f is above NPCI's ₹%.0f no-PIN threshold; debits above it may still need a PIN per charge.",
			maxPerOrder, upiAutopayAFACap)
	}
	return jsonResult(resp), nil
}

func handleCheckAutopay(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	sess := session(req)
	m := db.getMandate(sess)
	if m == nil {
		return mcp.NewToolResultError("no autopay mandate for this session — call setup_autopay first"), nil
	}

	if m.Status == "PENDING_AUTH" {
		tokenID, status, err := fetchMandateToken(m.CustomerID)
		if err != nil {
			return mcp.NewToolResultError("could not check mandate: " + err.Error()), nil
		}
		if status == "confirmed" {
			m.TokenID = tokenID
			m.Status = "ACTIVE"
		}
	}

	return jsonResult(map[string]any{
		"mandate":          m,
		"remaining_budget": m.remaining(),
	}), nil
}

func handleCheckPaymentStatus(_ context.Context, req mcp.CallToolRequest) (*mcp.CallToolResult, error) {
	orderID, err := req.RequireString("order_id")
	if err != nil {
		return mcp.NewToolResultError(err.Error()), nil
	}

	db.mu.Lock()
	order := db.orders[orderID]
	db.mu.Unlock()
	if order == nil {
		return mcp.NewToolResultError("unknown order id: " + orderID), nil
	}

	status, err := fetchPaymentStatus(order.PaymentLinkID)
	if err != nil {
		return mcp.NewToolResultError("could not fetch payment status: " + err.Error()), nil
	}
	if status == "paid" {
		order.Status = "PAID"
	}

	return jsonResult(map[string]any{
		"order_id":        order.ID,
		"razorpay_status": status,
		"status":          order.Status,
	}), nil
}
