# Orders & Checkout — API Reference

Envelope, as established in the previous phase:
```json
{ "status": "success", "message": "...", "data": {} }
{ "status": "error",   "message": "...", "errors": {} }
```
Authentication: `Authorization: Bearer <token>` (user) or `X-Guest-Token: <session_key>` (guest) — same contract as cart/coupons.

---

## POST /api/checkout/validate/

No body required. Validates the caller's current cart without changing anything.

```json
{
  "status": "success",
  "message": "Checkout validation successful.",
  "data": {
    "is_valid": true,
    "items": [
      {
        "cart_item_id": "9a2c...",
        "product_id": "3fa8...",
        "variant_id": "5cb2...",
        "name": "Lavender Body Wash (500ml)",
        "quantity": 2,
        "available_stock": 42,
        "price_when_added": "499.00",
        "current_price": "499.00",
        "price_changed": false,
        "problems": []
      }
    ],
    "subtotal": "998.00",
    "discount": "99.80",
    "shipping": "0.00",
    "tax": "0.00",
    "total": "898.20"
  }
}
```
If a price changed or stock is short, that item's `problems` list is
populated and `is_valid` is `false` — the message becomes "Checkout
validation failed." (still a `200`, since this is a report, not an error).

---

## POST /api/checkout/quote/

```json
{ "coupon_code": "SUMMER10" }
```
or with no body — quotes the cart's current state as-is (including
whatever coupon is already applied). The server **always** recalculates
every figure; nothing from the request body is trusted as a final amount.

```json
{
  "status": "success",
  "message": "Quote calculated successfully.",
  "data": {
    "subtotal": "998.00",
    "discount": "99.80",
    "shipping_amount": "0.00",
    "tax_amount": "0.00",
    "grand_total": "898.20",
    "total_quantity": 2,
    "item_count": 1
  }
}
```

---

## POST /api/checkout/create-order/

### Authenticated user, using a saved address
```json
{ "shipping_address_id": "b7e1...", "notes": "Leave at the door." }
```
(billing defaults to the same address if `billing_address_id`/`billing_address` is omitted)

### Guest, with new address data
```json
{
  "guest_email": "guest@example.com",
  "guest_phone": "+919876543210",
  "shipping_address": {
    "full_name": "Asha Rao",
    "phone": "+919876543210",
    "line1": "221B Residency Road",
    "city": "Kochi",
    "state": "Kerala",
    "postal_code": "682001",
    "country": "India"
  }
}
```

### Success (201)
```json
{
  "status": "success",
  "message": "Order created successfully.",
  "data": {
    "id": "c4d9...",
    "order_number": "ORD-20260722-9F3C1A",
    "customer_email": "guest@example.com",
    "customer_phone": "+919876543210",
    "billing_address_snapshot": { "full_name": "Asha Rao", "...": "..." },
    "shipping_address_snapshot": { "full_name": "Asha Rao", "...": "..." },
    "subtotal": "998.00", "discount_amount": "99.80", "shipping_amount": "0.00",
    "tax_amount": "0.00", "total_amount": "898.20", "currency": "INR",
    "coupon_code": "SUMMER10",
    "status": "pending", "payment_status": "pending", "fulfillment_status": "unfulfilled",
    "is_cancellable": true,
    "notes": "",
    "items": [
      {
        "id": "...", "product": "3fa8...", "variant": "5cb2...",
        "product_name": "Lavender Body Wash", "variant_name": "500ml", "sku": "LBW-001-500",
        "unit_price": "499.00", "quantity": 2, "total_price": "998.00"
      }
    ],
    "status_history": [
      { "status_type": "order", "old_status": "", "new_status": "pending", "changed_by_email": null, "reason": "Order created from checkout.", "created_at": "..." }
    ],
    "created_at": "...", "updated_at": "..."
  }
}
```

### Validation error (400)
```json
{
  "status": "error",
  "message": "Validation failed.",
  "errors": { "shipping_address": ["Provide either shipping_address_id or shipping_address."] }
}
```

### Stock conflict (409) — e.g. two customers race for the last unit
```json
{ "status": "error", "message": "Only 0 unit(s) of 'Lavender Body Wash (500ml)' available." }
```
The whole transaction rolls back: no order, no partial stock reduction, cart untouched.

### Duplicate submission (409)
```json
{ "status": "error", "message": "An order has already been created from this cart." }
```

---

## GET /api/orders/
Paginated list of the caller's own orders (lightweight — no items/history).

## GET /api/orders/\<uuid:id\>/
Full order detail. Returns `404` — not `403` — if the order belongs to
someone else, so existence of another user's order is never leaked.

## POST /api/orders/\<uuid:id\>/cancel/
```json
{ "reason": "Changed my mind." }
```
Success (200) returns the updated order with `status: "cancelled"` and
restored stock. Failure (409) if the order is already past a cancellable
stage:
```json
{ "status": "error", "message": "Orders in 'shipped' status can no longer be cancelled." }
```

---

## Admin endpoints

All require `IsManagerOrAdmin` (Manager or Admin role — reused from `users/permissions.py`, whose own docstring names "viewing all orders" as an intended use of this exact class).

### GET /api/admin/orders/?status=pending&payment_status=paid&date_from=2026-07-01&date_to=2026-07-31&customer=guest@example.com&order_number=ORD-2026
Filters combine with AND. `customer` matches either `customer_email` or the linked user's email.

### PATCH /api/admin/orders/\<uuid:id\>/status/
```json
{ "status": "confirmed", "reason": "Payment verified manually." }
```
Invalid transition (409):
```json
{ "status": "error", "message": "Cannot move an order from 'delivered' to 'pending'." }
```

### PATCH /api/admin/orders/\<uuid:id\>/payment-status/
```json
{ "payment_status": "paid" }
```

### PATCH /api/admin/orders/\<uuid:id\>/fulfillment-status/
```json
{ "fulfillment_status": "packed" }
```

### POST /api/admin/orders/\<uuid:id\>/cancel/
Same behavior as the customer cancel endpoint, but usable by staff regardless of who placed the order, and logs `changed_by` as the admin.

Every one of these four calls writes an `OrderStatusHistory` row (`status_type` = `order` / `payment` / `fulfillment`) — one history table covers all three status dimensions rather than three separate tables.

---

## Complete checkout flow

1. **Shopping** — customer uses the cart/coupon endpoints from the previous phase as normal.
2. **`POST /api/checkout/validate/`** (optional but recommended) — frontend calls this right before showing the final checkout page, to surface stale prices or stock shortfalls *before* asking for payment details.
3. **`POST /api/checkout/quote/`** (optional) — used for "what if I applied this coupon" previews without committing to anything.
4. **`POST /api/checkout/create-order/`** — the only endpoint that actually commits. Inside one `transaction.atomic()` block:
   - Cart row is locked (`select_for_update`) → rejects a second concurrent submission of the same cart (`DuplicateOrderCreation`).
   - Every relevant `ProductVariant` row is locked, in a stable order, before anything is validated — this is what makes the "only one of two simultaneous buyers gets the last unit" guarantee hold: the second transaction blocks on the row lock until the first commits or rolls back, then re-reads the now-updated `stock_quantity` and correctly fails.
   - Product/variant active-state and stock are re-validated against the **locked** rows (never the cart's stale snapshot).
   - `cart.pricing.calculate_cart_totals()` recomputes every money figure from scratch.
   - The coupon (if any) is re-validated via `coupons.services.validate_coupon()` — closes the race where two people apply the last use of a limited coupon at nearly the same moment.
   - `Order` + `OrderItem` rows are created with full snapshots (address, product/variant name, SKU, price) so the historical record never changes even if the catalog or the customer's saved address changes later.
   - Stock is deducted on the same locked variant rows.
   - Coupon usage is confirmed (`coupons.services.confirm_coupon_usage`), which is the hand-off point promised in the previous phase's docs — this is where `Coupon.used_count` finally increments and the `CouponUsage` row flips to `confirmed=True`.
   - The cart is cleared **only after all of the above succeeds** — if anything raises, the whole transaction rolls back and the customer's cart is untouched, ready to retry.
5. **Post-order** — customer tracks the order via `GET /api/orders/<id>/`; staff manage it via the `/api/admin/orders/` endpoints, with every status change written to `OrderStatusHistory`.
6. **Cancellation** — allowed only from `PENDING`/`CONFIRMED`. Cancelling re-locks the same `ProductVariant` rows and restores `stock_quantity`, so a cancelled order's stock is available for the next buyer immediately.

Razorpay (payment capture) and Shiprocket (fulfillment/shipping) are
intentionally **not** wired in this phase — `payment_status` and
`fulfillment_status` exist as fields with full transition validation
and are ready to be driven by webhooks/API calls from those integrations
in the next phase, without any schema changes.
