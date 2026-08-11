"""
checkout/urls.py

Mount in root urls.py:
    path("api/checkout/", include("checkout.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("validate/", views.CheckoutValidateView.as_view(), name="checkout-validate"),
    path("quote/", views.CheckoutQuoteView.as_view(), name="checkout-quote"),
    path("create-order/", views.CreateOrderView.as_view(), name="checkout-create-order"),
]
