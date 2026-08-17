"""
orders/selectors.py
"""

from django.db.models import Q

from .exceptions import OrderNotFound
from .models import Order


def get_order_queryset():
    return (
        Order.objects
        .select_related("user", "guest_session", "coupon", "cart")
        .prefetch_related("items__product", "items__variant", "status_history")
    )


def get_order_for_owner(order_id, user=None, guest_session=None):
    """
    Scoped lookup: raises OrderNotFound (404) if the order doesn't exist
    OR belongs to someone else — a user must never learn whether another
    user's order ID exists.
    """
    qs = get_order_queryset()
    if user is not None:
        qs = qs.filter(user=user)
    else:
        qs = qs.filter(guest_session=guest_session)
    try:
        return qs.get(id=order_id)
    except Order.DoesNotExist:
        raise OrderNotFound()


def get_order_by_number_for_owner(order_number, user=None, guest_session=None):
    qs = get_order_queryset()
    if user is not None:
        qs = qs.filter(user=user)
    else:
        qs = qs.filter(guest_session=guest_session)
    try:
        return qs.get(order_number=order_number)
    except Order.DoesNotExist:
        raise OrderNotFound()


def get_orders_for_owner(user=None, guest_session=None):
    qs = get_order_queryset()
    if user is not None:
        return qs.filter(user=user)
    return qs.filter(guest_session=guest_session)


def get_order_for_admin(order_id):
    try:
        return get_order_queryset().get(id=order_id)
    except Order.DoesNotExist:
        raise OrderNotFound()


def get_admin_order_queryset(params):
    """
    Applies optional filters from query params: status, payment_status,
    fulfillment_status, date_from, date_to, customer (email or user
    email), order_number/search.
    """
    qs = get_order_queryset()

    status = params.get("status")
    if status:
        qs = qs.filter(status=status)

    payment_status = params.get("payment_status")
    if payment_status:
        qs = qs.filter(payment_status=payment_status)

    fulfillment_status = params.get("fulfillment_status")
    if fulfillment_status:
        qs = qs.filter(fulfillment_status=fulfillment_status)

    date_from = params.get("date_from")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)

    date_to = params.get("date_to")
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    customer = params.get("customer")
    if customer:
        qs = qs.filter(
            Q(customer_email__icontains=customer) | Q(user__email__icontains=customer)
        )

    order_number = params.get("order_number") or params.get("search")
    if order_number:
        qs = qs.filter(order_number__icontains=order_number)

    return qs
