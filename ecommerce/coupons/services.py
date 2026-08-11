"""
coupons/services.py
"""

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.utils import timezone

from .exceptions import (
    CouponAlreadyApplied,
    CouponMinimumNotMet,
    CouponNotActive,
    CouponNotFound,
    CouponNotValidYet,
    CouponUsageLimitExceeded,
    CouponUserLimitExceeded,
    NoCouponApplied,
)
from .models import Coupon, CouponUsage

TWO_PLACES = Decimal("0.01")


def calculate_discount(coupon: Coupon, subtotal: Decimal) -> Decimal:
    """Pure calculation — assumes the coupon has already been validated."""
    subtotal = Decimal(subtotal)
    if coupon.discount_type == Coupon.DiscountType.PERCENTAGE:
        discount = subtotal * (Decimal(coupon.discount_value) / Decimal("100"))
    else:
        discount = Decimal(coupon.discount_value)

    if coupon.maximum_discount_amount is not None:
        discount = min(discount, Decimal(coupon.maximum_discount_amount))

    discount = min(discount, subtotal)
    return discount.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)


def _confirmed_usage_count_for_owner(coupon, user, guest_session):
    qs = CouponUsage.objects.filter(coupon=coupon, confirmed=True)
    if user is not None:
        return qs.filter(user=user).count()
    return qs.filter(guest_session=guest_session).count()


def validate_coupon(code, subtotal: Decimal, user=None, guest_session=None) -> Coupon:
    """
    Validates a coupon code can be applied right now. Raises a
    coupons.exceptions.* APIException on any failure. Returns the
    Coupon instance on success.
    """
    try:
        coupon = Coupon.objects.get(code=code.upper().strip())
    except Coupon.DoesNotExist:
        raise CouponNotFound()

    if not coupon.is_active:
        raise CouponNotActive()

    now = timezone.now()
    if now < coupon.valid_from:
        raise CouponNotValidYet()
    if now > coupon.valid_until:
        raise CouponNotActive("This coupon has expired.")

    if coupon.minimum_order_amount is not None and Decimal(subtotal) < Decimal(coupon.minimum_order_amount):
        raise CouponMinimumNotMet(
            f"A minimum order amount of {coupon.minimum_order_amount} is required for this coupon."
        )

    if coupon.is_globally_exhausted:
        raise CouponUsageLimitExceeded()

    if coupon.usage_limit_per_user is not None:
        used = _confirmed_usage_count_for_owner(coupon, user, guest_session)
        if used >= coupon.usage_limit_per_user:
            raise CouponUserLimitExceeded()

    return coupon


@transaction.atomic
def apply_coupon_to_cart(cart, code, user=None, guest_session=None):
    from cart.pricing import calculate_cart_totals

    if cart.coupon_id:
        raise CouponAlreadyApplied()

    totals = calculate_cart_totals(cart)
    coupon = validate_coupon(code, totals["subtotal"], user=user, guest_session=guest_session)

    cart.coupon = coupon
    cart.save(update_fields=["coupon", "updated_at"])

    CouponUsage.objects.get_or_create(
        coupon=coupon, user=user, guest_session=guest_session, cart=cart,
        confirmed=False,
        defaults={"used_at": timezone.now()},
    )
    return coupon


@transaction.atomic
def remove_coupon_from_cart(cart):
    if not cart.coupon_id:
        raise NoCouponApplied()
    CouponUsage.objects.filter(cart=cart, confirmed=False).delete()
    cart.coupon = None
    cart.save(update_fields=["coupon", "updated_at"])


@transaction.atomic
def confirm_coupon_usage(cart):
    """
    Hand-off point for the Checkout/Orders phase: call this the moment
    an order is actually placed from `cart`, so the coupon's used_count
    and this user's per-user usage are permanently recorded.
    """
    if not cart.coupon_id:
        return
    coupon = cart.coupon
    usage = CouponUsage.objects.filter(cart=cart, coupon=coupon, confirmed=False).first()
    if usage:
        usage.confirmed = True
        usage.used_at = timezone.now()
        usage.save(update_fields=["confirmed", "used_at", "updated_at"])

    from django.db.models import F

    Coupon.objects.filter(pk=coupon.pk).update(used_count=F("used_count") + 1)
