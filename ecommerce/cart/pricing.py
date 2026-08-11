"""
cart/pricing.py

Reusable pricing service.

This module is intentionally the SINGLE source of truth for turning a
Cart's line items into money totals. It must stay free of view/request
concerns so that the upcoming Checkout and Orders phases can import and
reuse `calculate_cart_totals()` (or a near-identical `calculate_totals()`
over an order's line items) without duplicating arithmetic.

Rules
-----
- Decimal everywhere. Never float.
- Never trust CartItem.unit_price for the total — always re-read the
  current effective_price from the Product/ProductVariant tables. This
  protects against stale snapshots and any client-supplied price
  tampering.
- Coupon discount is calculated here too, so "apply coupon" and "view
  cart summary" always agree with each other.
"""

from decimal import ROUND_HALF_UP, Decimal

# Shipping / tax are simple pluggable placeholders for now — the brief
# does not define a shipping/tax engine yet. Kept as named constants so
# the checkout phase can swap these for a real rate lookup without
# touching the calculation shape callers depend on.
FLAT_SHIPPING_FEE = Decimal("0.00")
TAX_RATE = Decimal("0.00")  # e.g. Decimal("0.05") for 5% — wire up when tax rules exist

TWO_PLACES = Decimal("0.01")


def _q(amount: Decimal) -> Decimal:
    return Decimal(amount).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def current_unit_price(item) -> Decimal:
    """
    The authoritative, non-trusted current price for a cart item —
    read live from the variant (if any) or product record.
    """
    if item.variant_id:
        return Decimal(item.variant.effective_price)
    return Decimal(item.product.effective_price)


def calculate_cart_totals(cart) -> dict:
    """
    Compute totals for a cart.

    Returns a dict:
        {
            "subtotal": Decimal,
            "discount": Decimal,
            "shipping_amount": Decimal,
            "tax_amount": Decimal,
            "grand_total": Decimal,
            "total_quantity": int,
            "item_count": int,
        }
    """
    items = list(
        cart.items.select_related("product", "variant").all()
    )

    subtotal = Decimal("0.00")
    total_quantity = 0
    for item in items:
        price = current_unit_price(item)
        subtotal += price * item.quantity
        total_quantity += item.quantity

    subtotal = _q(subtotal)

    discount = Decimal("0.00")
    if cart.coupon_id and cart.coupon.is_currently_valid:
        from coupons.services import calculate_discount
        discount = calculate_discount(cart.coupon, subtotal)

    discount = _q(min(discount, subtotal))  # never discount more than the subtotal

    taxable_amount = subtotal - discount
    tax_amount = _q(taxable_amount * TAX_RATE) if TAX_RATE else Decimal("0.00")

    shipping_amount = FLAT_SHIPPING_FEE if items else Decimal("0.00")
    shipping_amount = _q(shipping_amount)

    grand_total = _q(subtotal - discount + shipping_amount + tax_amount)

    return {
        "subtotal": subtotal,
        "discount": discount,
        "shipping_amount": shipping_amount,
        "tax_amount": tax_amount,
        "grand_total": grand_total,
        "total_quantity": total_quantity,
        "item_count": len(items),
    }
