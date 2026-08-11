# Cart, Coupons & Wishlist — Setup

## 1. What changed in existing files

Only two existing files were touched, both additively:

- `ecommerce/settings.py` — added `cart`, `coupons`, `wishlist` to `INSTALLED_APPS`.
- `ecommerce/urls.py` — mounted the three new `urls.py` files.
- `catalog/exceptions.py` — one small, backward-compatible fix to the
  generic fallback branch of `custom_exception_handler`, so new 409
  `APIException`s (e.g. `InsufficientStock`) render their `detail`
  message cleanly instead of a stringified dict. The 400/401/403/404
  branches are untouched, so every existing users/catalog response is
  byte-for-byte the same as before.

No existing models, permissions, or views were modified or duplicated.

## 2. Install & migrate

```bash
pip install -r requirements.txt   # unchanged, no new packages needed

python manage.py makemigrations cart coupons wishlist
python manage.py migrate
```

Expected migration order: `cart` first is fine even though `Cart.coupon`
points at `coupons.Coupon` — Django resolves the FK by app label + model
name lazily, and both apps migrate within the same `migrate` run, so it
doesn't matter which of `cart`/`coupons` gets a lower migration number.
If you ever run `migrate cart` in isolation before `coupons` exists,
Django will still create the table; the FK constraint is deferred until
both apps' tables exist in the same transaction/run.

## 3. Sanity checklist after migrating

- `python manage.py check` — should report no issues.
- Open `/admin/` and confirm **Cart**, **Cart Items**, **Coupons**,
  **Coupon Usages**, **Wishlists**, and **Wishlist Items** all appear.
- `python manage.py shell`:
  ```python
  from cart.models import Cart
  from coupons.models import Coupon
  from wishlist.models import Wishlist
  Cart.objects.count(), Coupon.objects.count(), Wishlist.objects.count()
  ```

## 4. New URLs

```
GET    /api/cart/
POST   /api/cart/items/
PATCH  /api/cart/items/<uuid:id>/
DELETE /api/cart/items/<uuid:id>/
DELETE /api/cart/clear/
GET    /api/cart/summary/

POST   /api/coupons/apply/
DELETE /api/coupons/remove/
GET    /api/admin/coupons/
POST   /api/admin/coupons/
GET    /api/admin/coupons/<uuid:id>/
PATCH  /api/admin/coupons/<uuid:id>/
DELETE /api/admin/coupons/<uuid:id>/

GET    /api/wishlist/
POST   /api/wishlist/items/
DELETE /api/wishlist/items/<uuid:id>/
POST   /api/wishlist/items/<uuid:id>/move-to-cart/
```
