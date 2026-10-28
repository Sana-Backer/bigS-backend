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
- Stock model: ProductVariant.stock_quantity is the inventory field for
  items sold WITH a variant. For items sold WITHOUT a variant,
  Product.stock_quantity is the inventory field instead (see
  catalog.models.Product.stock_quantity's own docstring: "Only used
  while the product has no variants"). There is no separate
  reservation/inventory app, so "reserve or reduce stock" resolves to
  REDUCE stock_quantity (on whichever of the two rows applies) at
  order-creation time, inside the same locked transaction that creates
  the order. Restoring it on cancellation is the exact inverse
  operation, applied to the same row the reduction came from.
- Cart lifecycle: cart.services.ensure_not_empty()/clear_cart() are
  reused rather than reimplemented.
"""

import logging
import secrets
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from cart import services as cart_services
from cart.pricing import calculate_cart_totals
from catalog.models import Product, ProductVariant
from coupons import services as coupon_services
from inventory import services as inventory_services
from inventory.models import StockMovement

from .constants import (
    CANCELLABLE_ORDER_STATUSES,
    FULFILLMENT_STATUS_TRANSITIONS,
    ORDER_STATUS_TRANSITIONS,
    PAYMENT_STATUS_TRANSITIONS,
    FulfillmentStatus,
    OrderStatus,
    PaymentMethod,
    PaymentStatus,
    is_transition_allowed,
)
from .exceptions import (
    DuplicateOrderCreation,
    InvalidStatusTransition,
    OrderNotCancellable,
)
from .models import Order, OrderItem, OrderStatusHistory

logger = logging.getLogger(__name__)


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
    payment_method=PaymentMethod.RAZORPAY,
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

    # 3. Lock every stock-relevant row up front, in a stable (id) order,
    #    to avoid deadlocks between two concurrent checkouts that share
    #    overlapping products. Items WITH a variant lock the
    #    ProductVariant row; items WITHOUT a variant lock the Product
    #    row itself (Product.stock_quantity is the inventory field for
    #    variant-less items — see catalog.models.Product's docstring).
    items_qs = cart.items.select_related("product", "variant").order_by("id")
    items = list(items_qs)

    variant_ids = sorted({str(i.variant_id) for i in items if i.variant_id})
    locked_variants = {
        str(v.id): v
        for v in ProductVariant.objects.select_for_update().filter(id__in=variant_ids)
    }

    product_ids_without_variant = sorted({str(i.product_id) for i in items if not i.variant_id})
    locked_products = {
        str(p.id): p
        for p in Product.objects.select_for_update().filter(id__in=product_ids_without_variant)
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
        else:
            # Variant-less item — stock lives on the Product row itself.
            product = locked_products.get(str(item.product_id))
            if product is None or product.stock_quantity < item.quantity:
                available = product.stock_quantity if product else 0
                raise InsufficientStock(
                    f"Only {available} unit(s) of '{item.product.name}' available."
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
        payment_method=payment_method,
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

    # 14. Reduce stock on the locked variant rows, or the Product row
    #     itself for items that were added to cart without a variant.
    for item in items:
        target = (locked_variants[str(item.variant_id)] if item.variant_id
                  else locked_products[str(item.product_id)])
        inventory_services.record_movement(
            target, -item.quantity, StockMovement.Type.SALE,
            reference=order.order_number, user=user,
        )

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
# Auto-shipment hook
# ---------------------------------------------------------------------------

def _schedule_auto_shipment(order_id, changed_by=None):
    """
    Ask the shipping app to create the Shiprocket shipment for this order
    — but only AFTER the surrounding DB transaction has committed
    (transaction.on_commit), for two reasons:
      1. the Shiprocket HTTP call must not run while this transaction is
         still open (it would hold DB locks for the length of a network
         call), and
      2. if Shiprocket fails, the status change that triggered it must
         stay saved, not roll back.

    shipping.services is imported lazily because shipping already imports
    orders.services; a top-level import here would be circular.
    """
    def _run():
        try:
            from shipping.services import auto_create_shipment_for_order
            auto_create_shipment_for_order(order_id, created_by=changed_by)
        except Exception:  # last-resort guard: a callback error must never reach the caller
            logger.exception("Auto-shipment hook failed for order %s", order_id)

    transaction.on_commit(_run)


def _cancel_shipment_for_order(order: Order, changed_by=None, reason=""):
    """
    If this order has a live Shiprocket shipment, cancel it with Shiprocket.

    Called from inside the cancelling transaction, as the LAST step, so
    that if Shiprocket refuses (or the shipment is already out for
    delivery) the exception propagates and the WHOLE cancellation rolls
    back — we never end up with a cancelled order whose courier pickup is
    still booked. No shipment (or one already cancelled) is a no-op.

    shipping.services is imported lazily because shipping imports orders.
    """
    from shipping.constants import ShipmentStatus
    from shipping.models import Shipment
    from shipping.services import cancel_shipment

    shipment = Shipment.objects.filter(order=order).first()
    if shipment is None or shipment.status == ShipmentStatus.CANCELLED:
        return
    cancel_shipment(shipment, changed_by=changed_by, reason=reason)


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
    # Order just became CONFIRMED -> create the Shiprocket shipment automatically.
    if new_status == OrderStatus.CONFIRMED:
        _schedule_auto_shipment(order.pk, changed_by)
    # Order cancelled through this generic path -> don't leave a live shipment behind.
    elif new_status == OrderStatus.CANCELLED:
        _cancel_shipment_for_order(order, changed_by, reason or "Order cancelled.")
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
    # A prepaid order that was confirmed BEFORE its payment landed was skipped
    # by the auto-shipment hook; now that it's paid, try again (no-op if the
    # order isn't confirmed yet or already has a shipment).
    if new_status == PaymentStatus.PAID:
        _schedule_auto_shipment(order.pk, changed_by)
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

    # Last step, inside the same transaction: cancel the Shiprocket shipment
    # (if any). If Shiprocket refuses, this raises and everything above —
    # stock restore, status change, history — rolls back with it.
    _cancel_shipment_for_order(order, changed_by, reason)
    return order


def _restore_stock_for_order(order: Order):
    """
    Adds each cancelled order item's quantity back to stock — the
    ProductVariant row for items that were ordered with a variant, or
    the Product row itself for items that were ordered without one
    (the exact inverse of the two branches in step 14 of
    create_order_from_cart()).
    """
    items = list(order.items.select_related("product", "variant"))
    if not items:
        return

    # Variant-backed items.
    variant_items = [i for i in items if i.variant_id]
    if variant_items:
        locked_variants = {
            v.id: v
            for v in ProductVariant.objects.select_for_update().filter(
                id__in=[i.variant_id for i in variant_items]
            )
        }
        for item in variant_items:
            variant = locked_variants.get(item.variant_id)
            if variant is None:
                continue  # variant itself was deleted from the catalog since — nothing to restore
            inventory_services.record_movement(
                variant, item.quantity, StockMovement.Type.ORDER_CANCEL,
                reference=order.order_number,
            )

    # Variant-less items — stock lives on the Product row itself.
    product_items = [i for i in items if not i.variant_id and i.product_id]
    if product_items:
        locked_products = {
            p.id: p
            for p in Product.objects.select_for_update().filter(
                id__in=[i.product_id for i in product_items]
            )
        }
        for item in product_items:
            product = locked_products.get(item.product_id)
            if product is None:
                continue  # product itself was deleted from the catalog since — nothing to restore
            inventory_services.record_movement(
                product, item.quantity, StockMovement.Type.ORDER_CANCEL,
                reference=order.order_number,
            )