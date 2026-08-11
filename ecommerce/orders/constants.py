"""
orders/constants.py

Named status values + allowed-transition maps. Views/services must go
through `assert_transition_allowed()` below rather than writing status
strings inline anywhere else in the codebase.
"""

from django.db import models


class OrderStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    CONFIRMED = "confirmed", "Confirmed"
    PROCESSING = "processing", "Processing"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for Delivery"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"


class PaymentStatus(models.TextChoices):
    PENDING = "pending", "Pending"
    AUTHORIZED = "authorized", "Authorized"
    PAID = "paid", "Paid"
    FAILED = "failed", "Failed"
    REFUNDED = "refunded", "Refunded"
    PARTIALLY_REFUNDED = "partially_refunded", "Partially Refunded"


class FulfillmentStatus(models.TextChoices):
    UNFULFILLED = "unfulfilled", "Unfulfilled"
    PROCESSING = "processing", "Processing"
    PACKED = "packed", "Packed"
    SHIPPED = "shipped", "Shipped"
    OUT_FOR_DELIVERY = "out_for_delivery", "Out for Delivery"
    DELIVERED = "delivered", "Delivered"
    CANCELLED = "cancelled", "Cancelled"


# ---------------------------------------------------------------------------
# Allowed transitions. A status maps to the set of statuses it may move to.
# Anything not listed as a destination from the current status is rejected.
# ---------------------------------------------------------------------------

ORDER_STATUS_TRANSITIONS = {
    OrderStatus.PENDING: {OrderStatus.CONFIRMED, OrderStatus.CANCELLED, OrderStatus.FAILED},
    OrderStatus.CONFIRMED: {OrderStatus.PROCESSING, OrderStatus.CANCELLED},
    OrderStatus.PROCESSING: {OrderStatus.PACKED, OrderStatus.CANCELLED},
    OrderStatus.PACKED: {OrderStatus.SHIPPED, OrderStatus.CANCELLED},
    OrderStatus.SHIPPED: {OrderStatus.OUT_FOR_DELIVERY},
    OrderStatus.OUT_FOR_DELIVERY: {OrderStatus.DELIVERED},
    OrderStatus.DELIVERED: {OrderStatus.REFUNDED, OrderStatus.PARTIALLY_REFUNDED},
    OrderStatus.CANCELLED: set(),
    OrderStatus.FAILED: set(),
    OrderStatus.REFUNDED: set(),
    OrderStatus.PARTIALLY_REFUNDED: {OrderStatus.REFUNDED},
}

# Orders may only be customer/admin-cancelled from these statuses.
CANCELLABLE_ORDER_STATUSES = {OrderStatus.PENDING, OrderStatus.CONFIRMED}

# Statuses where stock has already been deducted and must be restored on cancel.
STOCK_DEDUCTED_STATUSES = {
    OrderStatus.PENDING, OrderStatus.CONFIRMED, OrderStatus.PROCESSING,
    OrderStatus.PACKED, OrderStatus.SHIPPED, OrderStatus.OUT_FOR_DELIVERY,
    OrderStatus.DELIVERED,
}

PAYMENT_STATUS_TRANSITIONS = {
    PaymentStatus.PENDING: {PaymentStatus.AUTHORIZED, PaymentStatus.PAID, PaymentStatus.FAILED},
    PaymentStatus.AUTHORIZED: {PaymentStatus.PAID, PaymentStatus.FAILED},
    PaymentStatus.PAID: {PaymentStatus.REFUNDED, PaymentStatus.PARTIALLY_REFUNDED},
    PaymentStatus.FAILED: {PaymentStatus.PENDING},
    PaymentStatus.REFUNDED: set(),
    PaymentStatus.PARTIALLY_REFUNDED: {PaymentStatus.REFUNDED},
}

FULFILLMENT_STATUS_TRANSITIONS = {
    FulfillmentStatus.UNFULFILLED: {FulfillmentStatus.PROCESSING, FulfillmentStatus.CANCELLED},
    FulfillmentStatus.PROCESSING: {FulfillmentStatus.PACKED, FulfillmentStatus.CANCELLED},
    FulfillmentStatus.PACKED: {FulfillmentStatus.SHIPPED, FulfillmentStatus.CANCELLED},
    FulfillmentStatus.SHIPPED: {FulfillmentStatus.OUT_FOR_DELIVERY},
    FulfillmentStatus.OUT_FOR_DELIVERY: {FulfillmentStatus.DELIVERED},
    FulfillmentStatus.DELIVERED: set(),
    FulfillmentStatus.CANCELLED: set(),
}


def is_transition_allowed(transition_map, current, new):
    if current == new:
        return False
    return new in transition_map.get(current, set())
