"""
shipping/urls.py

Mount in root urls.py:
    path("api/shipping/", include("shipping.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("serviceability/", views.ServiceabilityView.as_view(), name="shipping-serviceability"),
    path("webhooks/shiprocket/", views.ShiprocketWebhookView.as_view(), name="shiprocket-webhook"),
]
