"""
shipping/selectors.py
"""

from .exceptions import ShipmentNotFound
from .models import Shipment


def get_shipment_queryset():
    return Shipment.objects.select_related("order")


def get_shipment_for_admin(shipment_id):
    try:
        return get_shipment_queryset().get(id=shipment_id)
    except Shipment.DoesNotExist:
        raise ShipmentNotFound()


def get_shipment_for_order(order):
    """Returns the Shipment for this Order, or None if it has none yet."""
    return get_shipment_queryset().filter(order=order).first()


def get_shipment_for_owner(order_id, user=None, guest_session=None):
    """
    Scoped lookup used by the customer-facing tracking endpoint: raises
    ShipmentNotFound (404) if the order doesn't exist, belongs to
    someone else, or has no shipment yet — mirroring orders.selectors'
    "don't leak whether this ID exists" guarantee.
    """
    qs = get_shipment_queryset().filter(order_id=order_id)
    if user is not None:
        qs = qs.filter(order__user=user)
    else:
        qs = qs.filter(order__guest_session=guest_session)
    shipment = qs.first()
    if shipment is None:
        raise ShipmentNotFound()
    return shipment
