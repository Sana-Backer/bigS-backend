# Cart, Coupons & Wishlist — API Reference & Examples

All responses use the project's existing envelope (from
`catalog.exceptions.custom_exception_handler` + `common/responses.py`):

```json
{ "status": "success", "message": "...", "data": {} }
{ "status": "error",   "message": "...", "errors": {} }
```

Authentication: send `Authorization: Bearer <access_token>` for
logged-in users, **or** `X-Guest-Token: <session_key>` (from
`POST /api/auth/guest/session/`) for guests. Cart and coupon endpoints
accept either; wishlist requires a logged-in user.

---

## Cart

### Get current cart
`GET /api/cart/`

```json
{
  "status": "success",
  "message": "Cart retrieved successfully.",
  "data": {
    "id": "b3f1...",
    "status": "active",
    "coupon_code": null,
    "items": [
      {
        "id": "9a2c...",
        "product": {"id": "...", "name": "Lavender Body Wash", "slug": "lavender-body-wash", "sku": "LBW-001"},
        "variant": {"id": "...", "name": "500ml", "sku": "LBW-001-500", "attributes": {"size": "500ml"}, "stock_quantity": 42},
        "quantity": 2,
        "unit_price": "499.00",
        "current_price": "499.00",
        "line_total": "998.00",
        "created_at": "...", "updated_at": "..."
      }
    ],
    "created_at": "...", "updated_at": "..."
  }
}
```

### Add item
`POST /api/cart/items/`

```json
{ "product_id": "3fa8...", "variant_id": "5cb2...", "quantity": 2 }
```

Adding a product/variant already in the cart **increases the existing
line's quantity** instead of creating a duplicate row.

Validation error (400):
```json
{
  "status": "error",
  "message": "Validation failed.",
  "errors": { "quantity": ["Quantity must be greater than zero."] }
}
```

Stock conflict (409):
```json
{ "status": "error", "message": "Only 3 unit(s) available for this item." }
```

### Update quantity
`PATCH /api/cart/items/<uuid:id>/`
```json
{ "quantity": 5 }
```

### Remove item
`DELETE /api/cart/items/<uuid:id>/` → 204

### Clear cart
`DELETE /api/cart/clear/` → 204 (also detaches any applied coupon)

### Summary
`GET /api/cart/summary/`
```json
{
  "status": "success",
  "message": "Cart summary retrieved successfully.",
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

## Coupons

### Apply
`POST /api/coupons/apply/`
```json
{ "code": "SUMMER10" }
```
Success (200) returns the coupon code plus refreshed totals. Failure
modes: `404` unknown code, `400` inactive/expired/minimum-not-met,
`409` usage limit exceeded (global or per-user) or a coupon is already
applied.

### Remove
`DELETE /api/coupons/remove/` → 200 with refreshed totals, or `400`
if no coupon was applied.

### Admin CRUD
`GET/POST /api/admin/coupons/` (list = STAFF+, create = ADMIN)
`GET/PATCH/DELETE /api/admin/coupons/<uuid:id>/` (get = STAFF+, write = ADMIN)

`POST /api/admin/coupons/`
```json
{
  "code": "summer10",
  "description": "10% off, up to ₹200",
  "discount_type": "percentage",
  "discount_value": "10.00",
  "minimum_order_amount": "500.00",
  "maximum_discount_amount": "200.00",
  "usage_limit": 1000,
  "usage_limit_per_user": 1,
  "valid_from": "2026-07-01T00:00:00Z",
  "valid_until": "2026-08-31T23:59:59Z",
  "is_active": true
}
```
`DELETE` deactivates rather than hard-deletes (same soft-delete pattern
already used by `Category`/`Product`/`ProductVariant`), since
`CouponUsage` history references it.

---

## Wishlist

### Get
`GET /api/wishlist/`

### Add
`POST /api/wishlist/items/`
```json
{ "product_id": "3fa8..." }
```
`409` if the product is already saved, `400` if inactive.

### Remove
`DELETE /api/wishlist/items/<uuid:id>/` → 204

### Move to cart
`POST /api/wishlist/items/<uuid:id>/move-to-cart/`
```json
{ "variant_id": "5cb2...", "quantity": 1 }
```
Re-validates product/variant availability and stock (via the same
`cart.services.add_item` used by the cart endpoints — no duplicated
logic), adds it to the cart, then removes it from the wishlist.

---

## Permission error example (any endpoint)
```json
{ "status": "error", "message": "You must be an Admin to perform this action." }
```
(403, using the existing `IsAdminRole.message` from `users/permissions.py`)

## Not found example
```json
{ "status": "error", "message": "Resource not found." }
```
(404, from the existing global exception handler)

---

## How Checkout / Orders will build on this

- **Cart → Order**: the Checkout view will call
  `cart.pricing.calculate_cart_totals(cart)` to get the exact same
  subtotal/discount/shipping/tax/grand_total shown in `/api/cart/summary/`,
  then snapshot each `CartItem` into an `OrderItem` (product, variant,
  quantity, and the *current* price at that moment — reusing
  `cart.pricing.current_unit_price`).
- **Coupon confirmation**: the moment an order is actually placed,
  Checkout must call `coupons.services.confirm_coupon_usage(cart)`.
  This is the hand-off point that flips the pending `CouponUsage` row
  to `confirmed=True` and atomically increments `Coupon.used_count`.
  Until that call happens, applying/removing a coupon while shopping
  never consumes a customer's per-user usage allowance.
- **Cart lifecycle**: after an order is created, set
  `cart.status = Cart.Status.ORDERED` (or call
  `cart.services.clear_cart(cart)` and leave it `ACTIVE` again for a
  fresh cart) — either is a one-line addition once Orders exists.
- **Guest carts**: a guest's `Cart` is keyed off `GuestSession`, and
  `GuestSession.convert_to_user()` already exists — Checkout/guest
  conversion should merge or reassign `cart.guest_session` → `cart.user`
  at that point (not implemented here, since it's out of scope, but the
  data model supports it directly).
- **Stock decrement**: `ProductVariant.stock_quantity` is only *read*
  by this phase (for validation). Actually decrementing stock belongs
  to Orders, at the moment payment/placement succeeds — reuse
  `cart.services._available_stock` as the check just before decrementing.

No Order or Payment models/views were created in this phase, per the brief.
