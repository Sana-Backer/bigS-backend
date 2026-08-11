"""
coupons/models.py

Coupon           – discount rule definition
CouponUsage      – records who has used which coupon (per-user limit
                   enforcement + audit trail). `confirmed=False` means
                   "currently applied to a cart, not yet on a placed
                   order"; the future Checkout/Orders phase is expected
                   to call coupons.services.confirm_coupon_usage(cart)
                   when an order is actually placed, which flips
                   `confirmed=True` and increments Coupon.used_count.
                   Until then, usage limits are enforced against
                   CONFIRMED usages only, so removing/re-applying a
                   coupon during shopping never burns a customer's
                   per-user allowance.
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from users.models import GuestSession, User


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Coupon(TimeStampedModel):
    class DiscountType(models.TextChoices):
        PERCENTAGE = "percentage", "Percentage"
        FIXED = "fixed", "Fixed Amount"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    code = models.CharField(max_length=50, unique=True, db_index=True)
    description = models.CharField(max_length=500, blank=True)

    discount_type = models.CharField(max_length=20, choices=DiscountType.choices)
    discount_value = models.DecimalField(max_digits=12, decimal_places=2)

    minimum_order_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Cart subtotal must be >= this amount for the coupon to apply.",
    )
    maximum_discount_amount = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True,
        help_text="Caps the discount amount. Mainly relevant for percentage coupons.",
    )

    usage_limit = models.PositiveIntegerField(
        null=True, blank=True, help_text="Total number of times this coupon may be used, across all users. Blank = unlimited."
    )
    usage_limit_per_user = models.PositiveIntegerField(
        null=True, blank=True, help_text="Times a single user/guest may use this coupon. Blank = unlimited."
    )
    used_count = models.PositiveIntegerField(default=0)

    valid_from = models.DateTimeField()
    valid_until = models.DateTimeField()
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Coupon"
        verbose_name_plural = "Coupons"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["code"]),
            models.Index(fields=["is_active"]),
            models.Index(fields=["valid_from", "valid_until"]),
        ]
        constraints = [
            models.CheckConstraint(
                check=models.Q(discount_value__gt=0), name="coupon_discount_value_gt_zero"
            ),
        ]

    def __str__(self):
        return self.code

    def clean(self):
        if self.valid_from and self.valid_until and self.valid_from >= self.valid_until:
            raise ValidationError({"valid_until": "valid_until must be after valid_from."})
        if self.discount_type == self.DiscountType.PERCENTAGE and self.discount_value > 100:
            raise ValidationError({"discount_value": "Percentage discount cannot exceed 100."})

    def save(self, *args, **kwargs):
        self.code = self.code.upper().strip()
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_currently_valid(self):
        now = timezone.now()
        return self.is_active and self.valid_from <= now <= self.valid_until

    @property
    def is_globally_exhausted(self):
        return self.usage_limit is not None and self.used_count >= self.usage_limit


class CouponUsage(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    coupon = models.ForeignKey(Coupon, on_delete=models.CASCADE, related_name="usages")
    user = models.ForeignKey(
        User, null=True, blank=True, on_delete=models.CASCADE, related_name="coupon_usages"
    )
    guest_session = models.ForeignKey(
        GuestSession, null=True, blank=True, on_delete=models.CASCADE, related_name="coupon_usages"
    )
    cart = models.ForeignKey(
        "cart.Cart", null=True, blank=True, on_delete=models.SET_NULL, related_name="coupon_usages"
    )
    confirmed = models.BooleanField(
        default=False,
        help_text="True once an order using this coupon has actually been placed.",
    )
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Coupon Usage"
        verbose_name_plural = "Coupon Usages"
        ordering = ["-created_at"]
        constraints = [
            models.CheckConstraint(
                check=(
                    models.Q(user__isnull=False, guest_session__isnull=True)
                    | models.Q(user__isnull=True, guest_session__isnull=False)
                ),
                name="couponusage_belongs_to_exactly_one_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["coupon", "confirmed"]),
        ]

    def __str__(self):
        owner = self.user.email if self.user_id else f"guest:{self.guest_session_id}"
        return f"{self.coupon.code} used by {owner}"
