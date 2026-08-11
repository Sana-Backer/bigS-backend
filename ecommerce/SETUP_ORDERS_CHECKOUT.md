# Orders & Checkout — Setup

## 1. What changed in existing files

- `ecommerce/settings.py` — added `orders`, `checkout` to `INSTALLED_APPS`.
- `ecommerce/urls.py` — mounted `orders.urls` at `/api/` and `checkout.urls` at `/api/checkout/`.

No `users`, `catalog`, `cart`, `coupons`, or `wishlist` files were touched
in this phase. No models, permissions, pricing logic, or response
helpers were duplicated — see "What was reused" below.

## 2. Install & migrate

```bash
python manage.py makemigrations orders checkout
python manage.py migrate
```

`checkout` has no models, so `makemigrations checkout` will report
"No changes detected" — that's expected, it's a pure orchestration app.

`orders` migrations depend on `cart` and `coupons` already being
migrated (FKs to `cart.Cart` and `coupons.Coupon`), so run this after
the previous phase's migrations, or just run `migrate` with no app
name and Django will resolve the dependency order automatically.

## 3. What was reused (per the brief's explicit instructions)

| Concern | Reused from | Not duplicated |
|---|---|---|
| Pricing math | `cart.pricing.calculate_cart_totals()` | No second subtotal/discount/tax/total calculator was written. `orders.services` and `checkout.services` only ever read this dict. |
| Coupon validation/consumption | `coupons.services.validate_coupon()`, `calculate_discount()`, `confirm_coupon_usage()` | Order creation re-validates the coupon (catches a limit exhausted mid-checkout) but never recomputes a discount formula itself. |
| Stock field | `ProductVariant.stock_quantity` (confirmed as the only inventory field in the project — no separate inventory app exists) | No new stock/inventory model was created. "Reserve or reduce" resolves to **reduce**, since that's what the existing schema supports. |
| Cart empty-check / clear | `cart.services.ensure_not_empty()`, `clear_cart()` | |
| Owner resolution (user vs. guest via `X-Guest-Token`) | `cart.selectors.resolve_owner()` | |
| Permissions | `users.permissions.IsAuthenticatedOrGuest` (customer + checkout endpoints), `IsManagerOrAdmin` (admin order endpoints — its own docstring says "viewing all orders" is its intended use) | No new permission classes. |
| Response envelope | `common.responses.ok/created/no_content` (same `{"status": ..., "message": ..., "data": ...}` shape from the cart/coupons/wishlist phase) | |
| Address models | `users.models.Address` (registered users), `users.models.GuestAddress` (guests) | No new address model. |

## 4. New URLs

```
POST /api/checkout/validate/
POST /api/checkout/quote/
POST /api/checkout/create-order/

GET  /api/orders/
GET  /api/orders/<uuid:id>/
POST /api/orders/<uuid:id>/cancel/

GET   /api/admin/orders/
GET   /api/admin/orders/<uuid:id>/
PATCH /api/admin/orders/<uuid:id>/status/
PATCH /api/admin/orders/<uuid:id>/payment-status/
PATCH /api/admin/orders/<uuid:id>/fulfillment-status/
POST  /api/admin/orders/<uuid:id>/cancel/
```

## 5. Sanity checklist after migrating

- `python manage.py check`
- Confirm **Orders**, **Order Items**, **Order Status Histories** appear in `/admin/`.
- `python manage.py shell`:
  ```python
  from orders.models import Order
  Order.objects.count()
  ```
