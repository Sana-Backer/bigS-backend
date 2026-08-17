"""
orders/urls.py

Mount in root urls.py:
    path("api/", include("orders.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    # Customer-facing
    path("orders/", views.OrderListView.as_view(), name="order-list"),
    path("orders/<uuid:id>/", views.OrderDetailView.as_view(), name="order-detail"),
    path("orders/by-number/<str:order_number>/", views.OrderByNumberView.as_view(), name="order-by-number"),
    path("orders/<uuid:id>/cancel/", views.OrderCancelView.as_view(), name="order-cancel"),

    # Admin
    path("admin/orders/", views.AdminOrderListView.as_view(), name="admin-order-list"),
    path("admin/orders/<uuid:id>/", views.AdminOrderDetailView.as_view(), name="admin-order-detail"),
    path("admin/orders/<uuid:id>/status/", views.AdminOrderStatusUpdateView.as_view(), name="admin-order-status"),
    path("admin/orders/<uuid:id>/payment-status/", views.AdminOrderPaymentStatusUpdateView.as_view(), name="admin-order-payment-status"),
    path("admin/orders/<uuid:id>/fulfillment-status/", views.AdminOrderFulfillmentStatusUpdateView.as_view(), name="admin-order-fulfillment-status"),
    path("admin/orders/<uuid:id>/cancel/", views.AdminOrderCancelView.as_view(), name="admin-order-cancel"),
]
