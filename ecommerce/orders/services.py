"""
orders/services.py

The heavy lifting for turning a Cart into an Order, plus status
transition + cancellation logic.

Reuse, not reinvention
-----------------------
- Pricing: cart.pricing.calculate_cart_totals() is the ONLY place
  subtotal/discount/shipping/tax/grand_total are computed — this module
  never re-derives money math, it just reads that dict.
- Coupon validation/consumption: coupons.services.validate_coupon() and
  coupons.services.confirm_coupon_usage() are reused as-is.
- Stock model: ProductVariant.stock_quantity is the ONLY inventory
  field in this project (confirmed by inspecting catalog/models.py) —
  there is no separate reservation/inventory app, so "reserve or
  reduce stock" resolves to REDUCE stock_quantity at order-creation
  time, inside the same locked transaction that creates the order.
  Restoring it on cancellation is the exact inverse operation.
- Cart lifecycle: cart.services.ensure_not_empty()/clear_cart() are
  reused rather than reimplemented.
"""

import secrets
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from cart import services as cart_services
from cart.pricing import calculate_cart_totals
from catalog.models import ProductVariant
from coupons import services as coupon_services

from .constants import (
    CANCELLABLE_ORDER_STATUSES,
    FULFILLMENT_STATUS_TRANSITIONS,
    ORDER_STATUS_TRANSITIONS,
    PAYMENT_STATUS_TRANSITIONS,
    FulfillmentStatus,
    OrderStatus,
    PaymentStatus,
    is_transition_allowed,
)
from .exceptions import (
    DuplicateOrderCreation,
    InvalidStatusTransition,
    OrderNotCancellable,
)
from .models import Order, OrderItem, OrderStatusHistory


# ---------------------------------------------------------------------------
# Order number
# ---------------------------------------------------------------------------

def generate_order_number() -> str:
    """e.g. ORD-20260722-9F3C1A — date + random suffix, checked unique."""
    for _ in range(10):
        candidate = f"ORD-{timezone.now():%Y%m%d}-{secrets.token_hex(3).upper()}"
        if not Order.objects.filter(order_number=candidate).exists():
            return candidate
    # Astronomically unlikely fallback
    return f"ORD-{timezone.now():%Y%m%d%H%M%S}-{secrets.token_hex(4).upper()}"


# ---------------------------------------------------------------------------
# Address snapshotting
# ---------------------------------------------------------------------------

def snapshot_address(address) -> dict:
    """
    Accepts an Address instance, a GuestAddress instance, or a plain
    dict (already in snapshot shape) and returns a plain JSON-safe dict.
    This is the ONLY place order address snapshots are built, so the
    stored shape never has to change in more than one place later.
    """
    if address is None:
        return {}
    if isinstance(address, dict):
        return dict(address)
    return {
        "full_name": address.full_name,
        "phone": address.phone,
        "line1": address.line1,
        "line2": address.line2,
        "city": address.city,
        "state": address.state,
        "postal_code": address.postal_code,
        "country": address.country,
    }


# ---------------------------------------------------------------------------
# Order creation
# ---------------------------------------------------------------------------

@transaction.atomic
def create_order_from_cart(
    *,
    user=None,
    guest_session=None,
    cart,
    billing_address,
    shipping_address,
    customer_email,
    customer_phone="",
    notes="",
):
    """
    Creates an Order (+ OrderItems + initial OrderStatusHistory) from
    the given cart, following the exact sequence in the brief:
    lock stock rows -> validate cart/products/variants/stock -> recompute
    prices -> validate coupon -> calculate totals -> create records ->
    reduce stock -> clear cart. Everything is inside one transaction;
    any failure rolls back all of it (no partial order, no partial
    stock reduction, cart is not cleared).
    """
    # 1. Lock the cart row itself first, so two concurrent checkout
    #    requests for the same cart can't both proceed.
    from cart.models import Cart
    cart = Cart.objects.select_for_update().get(pk=cart.pk)

    if cart.status != Cart.Status.ACTIVE:
        raise DuplicateOrderCreation()

    # 2. Cart must not be empty.
    cart_services.ensure_not_empty(cart)

    # 3. Lock every stock-relevant ProductVariant row up front, in a
    #    stable (id) order, to avoid deadlocks between two concurrent
    #    checkouts that share overlapping products.
    items_qs = cart.items.select_related("product", "variant").order_by("id")
    items = list(items_qs)

    variant_ids = sorted({str(i.variant_id) for i in items if i.variant_id})
    locked_variants = {
        str(v.id): v
        for v in ProductVariant.objects.select_for_update().filter(id__in=variant_ids)
    }

    # 4/5/6/7. Validate every product/variant is still active and has stock.
    from cart.exceptions import InsufficientStock, ProductUnavailable, VariantUnavailable

    for item in items:
        if not item.product.is_active:
            raise ProductUnavailable(f"'{item.product.name}' is no longer available.")
        if item.variant_id:
            variant = locked_variants.get(str(item.variant_id))
            if variant is None or not variant.is_active:
                raise VariantUnavailable(
                    f"The selected variant for '{item.product.name}' is no longer available."
                )
            if variant.stock_quantity < item.quantity:
                raise InsufficientStock(
                    f"Only {variant.stock_quantity} unit(s) of '{item.product.name} "
                    f"({variant.name})' available."
                )

    # 8. Recalculate prices + totals from the DB (never trust cart snapshot).
    totals = calculate_cart_totals(cart)

    # 9. Re-validate the coupon at the moment of order placement (catches
    #    a limit that was exhausted by someone else since it was applied).
    coupon = None
    if cart.coupon_id:
        coupon = coupon_services.validate_coupon(
            cart.coupon.code, totals["subtotal"], user=user, guest_session=guest_session
        )

    # 10. Totals are already calculated above.

    # 11. Create the Order.
    order = Order.objects.create(
        order_number=generate_order_number(),
        user=user,
        guest_session=guest_session,
        cart=cart,
        customer_email=customer_email,
        customer_phone=customer_phone,
        billing_address_snapshot=snapshot_address(billing_address),
        shipping_address_snapshot=snapshot_address(shipping_address),
        subtotal=totals["subtotal"],
        discount_amount=totals["discount"],
        shipping_amount=totals["shipping_amount"],
        tax_amount=totals["tax_amount"],
        total_amount=totals["grand_total"],
        coupon=coupon,
        coupon_code=coupon.code if coupon else "",
        status=OrderStatus.PENDING,
        payment_status=PaymentStatus.PENDING,
        fulfillment_status=FulfillmentStatus.UNFULFILLED,
        notes=notes,
    )

    # 12. Create OrderItems with full snapshots.
    order_items = []
    for item in items:
        variant = locked_variants.get(str(item.variant_id)) if item.variant_id else None
        unit_price = Decimal(variant.effective_price) if variant else Decimal(item.product.effective_price)
        order_items.append(OrderItem(
            order=order,
            product=item.product,
            variant=variant,
            product_name=item.product.name,
            variant_name=variant.name if variant else "",
            sku=variant.sku if variant else item.product.sku,
            unit_price=unit_price,
            quantity=item.quantity,
            total_price=(unit_price * item.quantity).quantize(Decimal("0.01")),
        ))
    OrderItem.objects.bulk_create(order_items)

    # 13. Address snapshots already created above as part of Order fields.

    # 14. Reduce stock on the locked variant rows.
    for item in items:
        if item.variant_id:
            variant = locked_variants[str(item.variant_id)]
            variant.stock_quantity -= item.quantity
            variant.save(update_fields=["stock_quantity", "updated_at"])

    # 15. Initial status history record.
    OrderStatusHistory.objects.create(
        order=order,
        status_type="order",
        old_status="",
        new_status=OrderStatus.PENDING,
        changed_by=user,
        reason="Order created from checkout.",
    )

    # Confirm coupon usage (increments used_count, marks CouponUsage confirmed).
    if coupon:
        coupon_services.confirm_coupon_usage(cart)

    # 16. Clear the cart only now that everything above succeeded.
    cart_services.clear_cart(cart)

    return order


# ---------------------------------------------------------------------------
# Status transitions
# ---------------------------------------------------------------------------

@transaction.atomic
def change_order_status(order: Order, new_status, changed_by=None, reason=""):
    if not is_transition_allowed(ORDER_STATUS_TRANSITIONS, order.status, new_status):
        raise InvalidStatusTransition(
            f"Cannot move an order from '{order.status}' to '{new_status}'."
        )
    old_status = order.status
    order.status = new_status
    order.save(update_fields=["status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order, status_type="order", old_status=old_status, new_status=new_status,
        changed_by=changed_by, reason=reason,
    )
    return order


@transaction.atomic
def change_payment_status(order: Order, new_status, changed_by=None, reason=""):
    if not is_transition_allowed(PAYMENT_STATUS_TRANSITIONS, order.payment_status, new_status):
        raise InvalidStatusTransition(
            f"Cannot move payment status from '{order.payment_status}' to '{new_status}'."
        )
    old_status = order.payment_status
    order.payment_status = new_status
    order.save(update_fields=["payment_status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order, status_type="payment", old_status=old_status, new_status=new_status,
        changed_by=changed_by, reason=reason,
    )
    return order


@transaction.atomic
def change_fulfillment_status(order: Order, new_status, changed_by=None, reason=""):
    if not is_transition_allowed(FULFILLMENT_STATUS_TRANSITIONS, order.fulfillment_status, new_status):
        raise InvalidStatusTransition(
            f"Cannot move fulfillment status from '{order.fulfillment_status}' to '{new_status}'."
        )
    old_status = order.fulfillment_status
    order.fulfillment_status = new_status
    order.save(update_fields=["fulfillment_status", "updated_at"])
    OrderStatusHistory.objects.create(
        order=order, status_type="fulfillment", old_status=old_status, new_status=new_status,
        changed_by=changed_by, reason=reason,
    )
    return order


# ---------------------------------------------------------------------------
# Cancellation (customer or admin-initiated)
# ---------------------------------------------------------------------------

@transaction.atomic
def cancel_order(order: Order, changed_by=None, reason="Cancelled by customer."):
    # Re-fetch + lock so two concurrent cancel/status-update calls can't race.
    order = Order.objects.select_for_update().get(pk=order.pk)

    if order.status not in CANCELLABLE_ORDER_STATUSES:
        raise OrderNotCancellable(
            f"Orders in '{order.status}' status can no longer be cancelled."
        )

    _restore_stock_for_order(order)

    old_status = order.status
    order.status = OrderStatus.CANCELLED
    order.fulfillment_status = FulfillmentStatus.CANCELLED
    order.save(update_fields=["status", "fulfillment_status", "updated_at"])

    OrderStatusHistory.objects.create(
        order=order, status_type="order", old_status=old_status,
        new_status=OrderStatus.CANCELLED, changed_by=changed_by, reason=reason,
    )
    OrderStatusHistory.objects.create(
        order=order, status_type="fulfillment", old_status="",
        new_status=FulfillmentStatus.CANCELLED, changed_by=changed_by, reason=reason,
    )
    return order


def _restore_stock_for_order(order: Order):
    """Adds each cancelled order item's quantity back to variant stock."""
    items = list(order.items.select_related("variant").filter(variant__isnull=False))
    variant_ids = [i.variant_id for i in items]
    if not variant_ids:
        return
    locked = {
        v.id: v for v in ProductVariant.objects.select_for_update().filter(id__in=variant_ids)
    }
    for item in items:
        variant = locked.get(item.variant_id)
        if variant is None:
            continue  # variant itself was deleted from the catalog since — nothing to restore
        variant.stock_quantity += item.quantity
        variant.save(update_fields=["stock_quantity", "updated_at"])
