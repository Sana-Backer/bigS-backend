"""
cart/selectors.py

Read-only query helpers, including the logic that resolves "whose cart
is this request for" — authenticated user, or guest via X-Guest-Token,
reusing the existing GuestSession model and the same header contract
already used by users.permissions.IsAuthenticatedOrGuest.
"""

from django.utils import timezone

from users.models import GuestSession

from .exceptions import GuestSessionInvalid, GuestTokenRequired
from .models import Cart


def resolve_owner(request):
    """
    Returns a (user, guest_session) tuple — exactly one is non-None.
    Raises a cart exception if neither an authenticated user nor a
    valid guest token is present.
    """
    if request.user and request.user.is_authenticated:
        return request.user, None

    guest_token = request.headers.get("X-Guest-Token")
    if not guest_token:
        raise GuestTokenRequired()

    try:
        guest_session = GuestSession.objects.get(
            session_key=guest_token,
            expires_at__gt=timezone.now(),
        )
    except GuestSession.DoesNotExist:
        raise GuestSessionInvalid()

    return None, guest_session


def get_cart_queryset():
    return Cart.objects.select_related("user", "guest_session", "coupon").prefetch_related(
        "items__product", "items__variant"
    )


def get_cart_for_owner(user=None, guest_session=None):
    """Returns the active cart for the given owner, or None."""
    qs = get_cart_queryset().filter(status=Cart.Status.ACTIVE)
    if user is not None:
        return qs.filter(user=user).first()
    return qs.filter(guest_session=guest_session).first()


def get_cart_item(cart, item_id):
    from django.shortcuts import get_object_or_404
    return get_object_or_404(
        cart.items.select_related("product", "variant"), id=item_id
    )
