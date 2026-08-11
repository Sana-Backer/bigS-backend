"""
payments/selectors.py
"""

from django.db.models import Q

from .constants import REFUNDABLE_TRANSACTION_STATUSES
from .exceptions import PaymentTransactionNotFound
from .models import PaymentTransaction


def get_payment_queryset():
    return PaymentTransaction.objects.select_related("order", "initiated_by")


def get_payment_transaction_for_admin(id):
    try:
        return get_payment_queryset().get(id=id)
    except PaymentTransaction.DoesNotExist:
        raise PaymentTransactionNotFound()


def get_active_payment_transaction_for_order(order):
    """
    The most recent transaction currently eligible for a refund — i.e.
    PAID or PARTIALLY_REFUNDED. Refunds may only ever be initiated
    from a transaction in one of these two statuses.
    """
    txn = (
        get_payment_queryset()
        .filter(order=order, status__in=REFUNDABLE_TRANSACTION_STATUSES)
        .order_by("-created_at")
        .first()
    )
    if txn is None:
        raise PaymentTransactionNotFound("No successful payment found for this order.")
    return txn


def get_admin_payment_queryset(params):
    """
    Applies optional filters from query params: status, order_id,
    order_number/search (matches order number or Razorpay identifiers),
    date_from, date_to.
    """
    qs = get_payment_queryset()

    status_ = params.get("status")
    if status_:
        qs = qs.filter(status=status_)

    order_id = params.get("order_id")
    if order_id:
        qs = qs.filter(order_id=order_id)

    search = params.get("order_number") or params.get("search")
    if search:
        qs = qs.filter(
            Q(order__order_number__icontains=search)
            | Q(razorpay_order_id__icontains=search)
            | Q(razorpay_payment_id__icontains=search)
        )

    date_from = params.get("date_from")
    if date_from:
        qs = qs.filter(created_at__date__gte=date_from)

    date_to = params.get("date_to")
    if date_to:
        qs = qs.filter(created_at__date__lte=date_to)

    return qs
