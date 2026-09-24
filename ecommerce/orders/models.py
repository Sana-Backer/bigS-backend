"""
orders/models.py

Order              – one placed order, for a registered user OR a guest.
OrderItem          – snapshotted line item (survives product edits/deletes).
OrderStatusHistory – audit trail of every status change.

Design notes
------------
- Mirrors cart.models.Cart's "exactly one owner" pattern (user XOR
  guest_session), same CheckConstraint shape, for consistency.
- billing_address_snapshot / shipping_address_snapshot are JSONField
  copies taken at order-creation time. The live Address/GuestAddress
  row is NEVER read again for an existing order — if the customer
  edits or deletes their address afterwards, the historical order is
  unaffected. See orders.services._snapshot_address().
- OrderItem.product / .variant use on_delete=SET_NULL (not CASCADE),
  specifically so deleting a Product/ProductVariant from the catalog
  can never delete order history. product_name/variant_name/sku/
  unit_price are captured as plain snapshot fields for the same reason.
- `cart` is a nullable FK back to the cart.Cart it was created from —
  purely for traceability/support lookups, not relied on for any
  calculation (all money fields on Order are final, computed values).
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from catalog.models import Product, ProductVariant
from coupons.models import Coupon
from users.models import GuestSession, User

from .constants import FulfillmentStatus, OrderStatus, PaymentMethod, PaymentStatus

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Order(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order_number = models.CharField(max_length=32, unique=True, db_index=True, editable=False)

    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    guest_session = models.ForeignKey(
        GuestSession, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    # Traceability only — see module docstring.
    cart = models.ForeignKey(
        "cart.Cart", null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )

    customer_email = models.EmailField(db_index=True)
    customer_phone = models.CharField(max_length=17, blank=True)

    billing_address_snapshot = models.JSONField(default=dict)
    shipping_address_snapshot = models.JSONField(default=dict)

    subtotal = models.DecimalField(max_digits=12, decimal_places=2)
    discount_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    shipping_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=10, default="INR")

    coupon = models.ForeignKey(
        Coupon, null=True, blank=True, on_delete=models.SET_NULL, related_name="orders"
    )
    coupon_code = models.CharField(max_length=50, blank=True)  # snapshot, survives coupon deletion

    status = models.CharField(
        max_length=30, choices=OrderStatus.choices, default=OrderStatus.PENDING, db_index=True
    )
    payment_status = models.CharField(
        max_length=30, choices=PaymentStatus.choices, default=PaymentStatus.PENDING, db_index=True
    )
    payment_method = models.CharField(
        max_length=10, choices=PaymentMethod.choices, default=PaymentMethod.RAZORPAY, db_index=True,
    )
    fulfillment_status = models.CharField(
        max_length=30, choices=FulfillmentStatus.choices, default=FulfillmentStatus.UNFULFILLED, db_index=True
    )

    notes = models.TextField(blank=True)

    class Meta:
        verbose_name = "Order"
        verbose_name_plural = "Orders"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order_number"]),
            models.Index(fields=["status"]),
            models.Index(fields=["payment_status"]),
            models.Index(fields=["fulfillment_status"]),
            models.Index(fields=["customer_email"]),
            models.Index(fields=["created_at"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(user__isnull=False, guest_session__isnull=True)
                    | models.Q(user__isnull=True, guest_session__isnull=False)
                ),
                name="order_belongs_to_exactly_one_owner",
            ),
        ]

    def __str__(self):
        return self.order_number

    def clean(self):
        if bool(self.user_id) == bool(self.guest_session_id):
            raise ValidationError(
                "An order must belong to exactly one of: user or guest_session."
            )

    @property
    def is_cancellable(self):
        from .constants import CANCELLABLE_ORDER_STATUSES
        return self.status in CANCELLABLE_ORDER_STATUSES


class OrderItem(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="items")

    # Nullable + SET_NULL: order history must survive catalog deletions.
    product = models.ForeignKey(
        Product, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_items"
    )
    variant = models.ForeignKey(
        ProductVariant, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_items"
    )

    # Snapshots — authoritative for display/history regardless of what
    # happens to the live product/variant afterwards.
    product_name = models.CharField(max_length=300)
    variant_name = models.CharField(max_length=300, blank=True)
    sku = models.CharField(max_length=100)

    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    quantity = models.PositiveIntegerField()
    total_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Order Item"
        verbose_name_plural = "Order Items"
        ordering = ["created_at"]
        constraints = [
            models.CheckConstraint(check=models.Q(quantity__gt=0), name="order_item_quantity_gt_zero"),
        ]
        indexes = [
            models.Index(fields=["order"]),
            models.Index(fields=["product"]),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product_name} (order {self.order.order_number})"


class OrderStatusHistory(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name="status_history")

    # Free-text field, NOT constrained to one choices enum, because this
    # single history table records changes across three different status
    # dimensions (order status, payment status, fulfillment status).
    status_type = models.CharField(
        max_length=20,
        choices=[("order", "Order Status"), ("payment", "Payment Status"), ("fulfillment", "Fulfillment Status")],
        default="order",
    )
    old_status = models.CharField(max_length=30, blank=True)
    new_status = models.CharField(max_length=30)
    changed_by = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.SET_NULL, related_name="order_status_changes"
    )
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = "Order Status History"
        verbose_name_plural = "Order Status Histories"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["order", "status_type"]),
        ]

    def __str__(self):
        return f"{self.order.order_number}: {self.old_status or '—'} → {self.new_status}"
