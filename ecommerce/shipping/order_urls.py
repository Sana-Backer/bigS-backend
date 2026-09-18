"""
shipping/order_urls.py

Mount in root urls.py:
    path("api/", include("shipping.order_urls")),

Kept separate from shipping/urls.py because this single route lives
under /api/orders/... (alongside orders.urls) rather than under
/api/shipping/... — mirrors why payments/admin_urls.py is split out
from payments/urls.py.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("orders/<uuid:order_id>/tracking/", views.OrderTrackingView.as_view(), name="order-tracking"),
]
