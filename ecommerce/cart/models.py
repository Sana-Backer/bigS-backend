"""
cart/models.py

Cart and CartItem models.

Design notes
------------
- A Cart belongs to EXACTLY ONE of: an authenticated `user` OR a
  `guest_session` (users.models.GuestSession). Enforced with a
  CheckConstraint (belt) and model.clean() (braces) since not every
  backend enforces CheckConstraints identically (e.g. older SQLite).
- CartItem.unit_price is a PRICE SNAPSHOT captured at the moment the
  item was added/updated, kept only for display/audit purposes
  (e.g. "price when added"). It is NEVER trusted for totals — see
  cart/pricing.py, which always re-reads Product/ProductVariant for the
  authoritative current price.
- Duplicate (product, variant) combinations in the same cart are
  prevented at the database level with two partial unique constraints
  (one for variant IS NOT NULL, one for variant IS NULL), because a
  plain UniqueConstraint on (cart, product, variant) would NOT catch
  duplicates where variant is NULL — most backends treat NULLs as
  distinct for uniqueness purposes.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models

from catalog.models import Product, ProductVariant
from users.models import GuestSession, User


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Cart(TimeStampedModel):
    """
    Shopping cart. Belongs to either a registered User or a GuestSession,
    never both, never neither.
    """

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        ORDERED = "ordered", "Ordered"           # converted into an order (future phase)
        ABANDONED = "abandoned", "Abandoned"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    user = models.OneToOneField(
        User, null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="cart",
    )
    guest_session = models.OneToOneField(
        GuestSession, null=True, blank=True,
        on_delete=models.CASCADE,
        related_name="cart",
    )

    status = models.CharField(
        max_length=20, choices=Status.choices, default=Status.ACTIVE, db_index=True
    )

    # Set by coupons.services when a coupon is successfully applied.
    coupon = models.ForeignKey(
        "coupons.Coupon", null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="carts",
    )

    class Meta:
        verbose_name = "Cart"
        verbose_name_plural = "Carts"
        ordering = ["-updated_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(user__isnull=False, guest_session__isnull=True)
                    | models.Q(user__isnull=True, guest_session__isnull=False)
                ),
                name="cart_belongs_to_exactly_one_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["status"]),
        ]

    def __str__(self):
        owner = self.user.email if self.user_id else f"guest:{self.guest_session_id}"
        return f"Cart({owner})"

    def clean(self):
        if bool(self.user_id) == bool(self.guest_session_id):
            raise ValidationError(
                "A cart must belong to exactly one of: user or guest_session."
            )

    def save(self, *args, **kwargs):
        self.clean()
        super().save(*args, **kwargs)


class CartItem(TimeStampedModel):
    """A single line item in a cart."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cart = models.ForeignKey(Cart, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="cart_items"
    )
    variant = models.ForeignKey(
        ProductVariant, null=True, blank=True,
        on_delete=models.CASCADE, related_name="cart_items",
    )
    quantity = models.PositiveIntegerField(default=1)

    # Snapshot only — see module docstring. NOT used for totals.
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        verbose_name = "Cart Item"
        verbose_name_plural = "Cart Items"
        ordering = ["created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["cart", "product", "variant"],
                condition=models.Q(variant__isnull=False),
                name="unique_cart_product_variant",
            ),
            models.UniqueConstraint(
                fields=["cart", "product"],
                condition=models.Q(variant__isnull=True),
                name="unique_cart_product_no_variant",
            ),
            models.CheckConstraint(
                check=models.Q(quantity__gt=0),
                name="cart_item_quantity_gt_zero",
            ),
        ]
        indexes = [
            models.Index(fields=["cart"]),
            models.Index(fields=["product"]),
        ]

    def __str__(self):
        return f"{self.quantity} x {self.product.name} (cart {self.cart_id})"

    def clean(self):
        if self.variant_id and self.variant.product_id != self.product_id:
            raise ValidationError(
                {"variant": "This variant does not belong to the selected product."}
            )
