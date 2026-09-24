"""
checkout/services.py

Orchestration layer that sits between the checkout APIViews and the
reusable domain services (cart, coupons, orders). Deliberately thin —
all money math still comes from cart.pricing, all order-creation
mechanics still come from orders.services.
"""

from decimal import Decimal

from django.shortcuts import get_object_or_404

from cart.pricing import calculate_cart_totals, current_unit_price
from coupons import services as coupon_services
from orders.constants import PaymentMethod
from orders import services as order_services
from users.models import Address, GuestAddress

from .exceptions import AddressRequired, GuestEmailRequired


# ---------------------------------------------------------------------------
# Address resolution
# ---------------------------------------------------------------------------

def resolve_address(*, user, guest_session, address_id=None, address_data=None):
    """
    Returns an Address (user) or GuestAddress (guest) instance ready to
    be passed straight into orders.services.snapshot_address().
    """
    if address_id:
        if user is None:
            raise AddressRequired("Guests cannot reference a saved address by ID.")
        return get_object_or_404(Address, id=address_id, user=user)

    if address_data:
        if user is not None:
            return Address.objects.create(user=user, address_type=Address.AddressType.BOTH, **address_data)
        return GuestAddress.objects.create(guest=guest_session, **address_data)

    raise AddressRequired()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def validate_cart_for_checkout(cart) -> dict:
    """
    Read-only pre-check used by POST /api/checkout/validate/. Never
    mutates anything — just reports what would happen if checkout were
    attempted right now.
    """
    items_report = []
    is_valid = True

    for item in cart.items.select_related("product", "variant"):
        product = item.product
        variant = item.variant

        problems = []
        if not product.is_active:
            problems.append("Product is no longer active.")
        if variant is not None and not variant.is_active:
            problems.append("Variant is no longer active.")

        available_stock = variant.stock_quantity if variant is not None else None
        if available_stock is not None and item.quantity > available_stock:
            problems.append(f"Only {available_stock} unit(s) in stock.")

        current_price = current_unit_price(item)
        price_changed = current_price != Decimal(item.unit_price)

        if problems:
            is_valid = False

        items_report.append({
            "cart_item_id": str(item.id),
            "product_id": str(product.id),
            "variant_id": str(variant.id) if variant else None,
            "name": product.name if variant is None else f"{product.name} ({variant.name})",
            "quantity": item.quantity,
            "available_stock": available_stock,
            "price_when_added": str(item.unit_price),
            "current_price": str(current_price),
            "price_changed": price_changed,
            "problems": problems,
        })

    if cart.coupon_id and not cart.coupon.is_currently_valid:
        is_valid = False

    totals = calculate_cart_totals(cart)

    return {
        "is_valid": is_valid,
        "items": items_report,
        "subtotal": totals["subtotal"],
        "discount": totals["discount"],
        "shipping": totals["shipping_amount"],
        "tax": totals["tax_amount"],
        "total": totals["grand_total"],
    }


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------

def quote(cart, coupon_code=None) -> dict:
    """
    Server-authoritative price preview. If `coupon_code` is supplied and
    differs from whatever is currently applied to the cart, the coupon
    is validated and its discount previewed WITHOUT being persisted to
    the cart — applying it for real still goes through
    POST /api/coupons/apply/.
    """
    if coupon_code and (not cart.coupon_id or cart.coupon.code != coupon_code.upper().strip()):
        totals = calculate_cart_totals(cart)  # subtotal without the new coupon
        coupon = coupon_services.validate_coupon(coupon_code, totals["subtotal"])
        discount = coupon_services.calculate_discount(coupon, totals["subtotal"])
        # NOTE: tax_amount is currently always 0.00 (cart.pricing.TAX_RATE is
        # an unwired placeholder). Once a real tax rate is added, this preview
        # must recompute tax against (subtotal - discount) here too, same as
        # cart.pricing.calculate_cart_totals does.
        tax_amount = totals["tax_amount"]
        two_places = Decimal("0.01")
        grand_total = (totals["subtotal"] - discount + totals["shipping_amount"] + tax_amount).quantize(two_places)
        return {
            "subtotal": totals["subtotal"],
            "discount": discount,
            "shipping_amount": totals["shipping_amount"],
            "tax_amount": tax_amount,
            "grand_total": grand_total,
            "total_quantity": totals["total_quantity"],
            "item_count": totals["item_count"],
        }
    return calculate_cart_totals(cart)


# ---------------------------------------------------------------------------
# Order creation orchestration
# ---------------------------------------------------------------------------

def create_order(*, user, guest_session, cart, data):
    shipping_address = resolve_address(
        user=user, guest_session=guest_session,
        address_id=data.get("shipping_address_id"),
        address_data=data.get("shipping_address"),
    )

    if data.get("billing_address_id") or data.get("billing_address"):
        billing_address = resolve_address(
            user=user, guest_session=guest_session,
            address_id=data.get("billing_address_id"),
            address_data=data.get("billing_address"),
        )
    else:
        # No billing address supplied — reuse the shipping address object
        # (not a duplicate DB row) as billing too.
        billing_address = shipping_address

    if user is not None:
        customer_email = user.email
        customer_phone = data.get("guest_phone") or user.phone
    else:
        customer_email = data.get("guest_email") or guest_session.email
        customer_phone = data.get("guest_phone") or guest_session.phone
        if not customer_email:
            raise GuestEmailRequired()

    return order_services.create_order_from_cart(
        user=user,
        guest_session=guest_session,
        cart=cart,
        billing_address=billing_address,
        shipping_address=shipping_address,
        customer_email=customer_email,
        customer_phone=customer_phone or "",
        payment_method=data.get("payment_method") or PaymentMethod.RAZORPAY,
        notes=data.get("notes", ""),
    )
