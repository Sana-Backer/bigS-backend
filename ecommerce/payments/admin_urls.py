"""
payments/admin_urls.py

Mount in root urls.py:
    path("api/admin/", include("payments.admin_urls")),

Kept separate from payments/urls.py (which mounts under /api/payments/)
because these three routes live under /api/admin/... instead.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("payments/", views.AdminPaymentListView.as_view(), name="admin-payment-list"),
    path("payments/<uuid:id>/", views.AdminPaymentDetailView.as_view(), name="admin-payment-detail"),
    path("orders/<uuid:order_id>/refund/", views.AdminOrderRefundView.as_view(), name="admin-order-refund"),
]
