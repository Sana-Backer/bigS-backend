"""
payments/urls.py

Mount in root urls.py:
    path("api/payments/", include("payments.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("razorpay/create/", views.RazorpayCreateOrderView.as_view(), name="razorpay-create-order"),
    path("razorpay/verify/", views.RazorpayVerifyPaymentView.as_view(), name="razorpay-verify-payment"),
    path("razorpay/refund/", views.RazorpayRefundView.as_view(), name="razorpay-refund"),
    path("webhooks/razorpay/", views.RazorpayWebhookView.as_view(), name="razorpay-webhook"),
]
