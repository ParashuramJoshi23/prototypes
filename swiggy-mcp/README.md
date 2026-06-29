# swiggy-mcp

A prototype **MCP server** (Go) that models the Swiggy food/grocery ordering
flow — search → menu → cart → checkout — and settles payment through a **real
Razorpay payment link** in test mode.

## What this is (and what it isn't)

This explores the concept of an **LLM agent driving a transactional flow over
MCP**, with a real payment leg. It is **not** a Swiggy client.

Why not? Two hard walls, neither of which is a missing integration:

1. **Swiggy has no public ordering or payment API.** The only endpoints are
   the app's private ones; using them means reverse-engineering a private API
   (ToS violation, account-ban risk, breaks whenever Swiggy changes anything).
2. **Payment is human-gated by regulation.** UPI requires your PIN in your UPI
   app; cards require 3DS/OTP (RBI's additional-factor-of-auth mandate). There
   is no programmatic "complete this payment" — by design. And Razorpay can't
   pay Swiggy anyway: a Razorpay account *collects* money *into you*; it can't
   drive someone else's checkout.

So the catalog here is seed data, and the one real external call is to
Razorpay — where **the agent assembles the order and a human authorizes the
money**. That human-in-the-loop payment step isn't a shortcut; it's how
agentic commerce actually works.

```
LLM agent ──(MCP tools)──► swiggy-mcp ──► in-memory catalog / cart
                               │
              checkout ────────┴────► Razorpay API (test mode)
                                        creates a Payment Link
                                        │
        human opens link, pays ◄────────┘  (Razorpay test card)
        with real 3DS/OTP sim
                                        │
   check_payment_status (poll) ◄──────── Razorpay reports "paid"
                                        │
              order marked PAID ◄────────┘
```

## Tools

| Tool | Purpose |
|------|---------|
| `search_restaurants` | Find restaurants by name/cuisine |
| `search_groceries`   | Find grocery stores |
| `get_menu`           | List a vendor's items (ids + prices) |
| `add_to_cart`        | Add an item (cart is pinned to one vendor) |
| `view_cart`          | Show cart + subtotal |
| `clear_cart`         | Empty the cart |
| `checkout`           | Place the order — auto-charges via Autopay if a mandate covers it, else a payment link |
| `check_payment_status` | Poll Razorpay until the order is `PAID` |
| `setup_autopay`      | Create a UPI Autopay mandate (approve once, then auto-charge within limits) |
| `check_autopay`      | Check mandate status (`PENDING_AUTH`/`ACTIVE`/`EXHAUSTED`) + remaining budget |

## UPI Autopay — bounded autonomous payment

By default every order needs a human to pay the link. **UPI Autopay** flips
that: the human approves a *mandate* **once** (one UPI PIN), authorizing
recurring debits up to a cap — after which the agent charges within that cap
**with no per-order approval**. This is the real primitive behind "agentic"
spending: pre-authorized, bounded autonomy, not magic.

Two limits enforce the bound:

- **`max_per_order`** — the biggest single order the agent may auto-charge.
- **`total_budget`** — cumulative auto-spend before the mandate is `EXHAUSTED`.

Anything outside the bounds (too big, or budget used up) automatically falls
back to the human-approved payment link, with an `autopay_skipped` reason.

```
setup_autopay(max_per_order, total_budget) ──► Razorpay registration link
                                                 │
        human approves mandate ONCE ◄────────────┘  (one UPI PIN, test mode)
                                                 │
        check_autopay ──► mandate ACTIVE ◄───────┘
                                                 │
        checkout (within limits) ──► chargeRecurring ──► PAID, no human step
        checkout (over a limit)  ──► payment link (human pays), autopay_skipped
```

Under the hood this uses Razorpay's recurring API:
`subscription_registration/auth_links` to set up the mandate, then
`payments/create/recurring` to debit the saved token server-to-server. Note
NPCI's **₹15,000** per-debit threshold: at/below it Autopay charges without a
PIN; above it each charge may still need one (`setup_autopay` warns you).

> The mandate *authorization* leg (the one-time approval) is a hosted Razorpay
> flow that needs a browser/UPI-app step — that's the human-in-the-loop part by
> design. Once authorized, the recurring charges are fully server-side.

## Setup

Needs Razorpay **test-mode** keys (free, no business verification):

```bash
cp .env.example .env   # then fill in rzp_test_... keys
go build -o swiggy-mcp .
```

## Run it from an MCP client

The server speaks MCP over stdio. Register it with any MCP client. For Claude
Code:

```bash
claude mcp add swiggy -- env RAZORPAY_KEY_ID=rzp_test_xxx RAZORPAY_KEY_SECRET=xxx /abs/path/to/swiggy-mcp/swiggy-mcp
```

Or in a client's JSON config:

```json
{
  "mcpServers": {
    "swiggy": {
      "command": "/abs/path/to/swiggy-mcp/swiggy-mcp",
      "env": {
        "RAZORPAY_KEY_ID": "rzp_test_xxx",
        "RAZORPAY_KEY_SECRET": "xxx"
      }
    }
  }
}
```

Then ask the agent: *"order a chicken biryani."* It will search, open the menu,
add to cart, check out, and hand you a Razorpay link. Pay it with a test card —
`4111 1111 1111 1111`, any future expiry, any CVV, OTP `1234` — then the agent
polls `check_payment_status` until the order reads `PAID`.

## Test

```bash
go test ./...
```

Tests cover the cart/catalog logic, the spend-limit enforcement, and the
"no keys → clear error" payment path. `harness_test.go` adds an **end-to-end
test against an `httptest` mock of the Razorpay recurring endpoints** — it
drives the whole Autopay lifecycle (mandate setup → pending → authorize →
active → auto-charge within limits → over-limit fallback to a payment link →
link paid) with no live keys and no browser, so the autonomous charge path is
fully assertable in CI.
