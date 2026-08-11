"""
cart/urls.py

Mount in root urls.py:
    path("api/cart/", include("cart.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.CartDetailView.as_view(), name="cart-detail"),
    path("items/", views.CartItemListCreateView.as_view(), name="cart-item-create"),
    path("items/<uuid:id>/", views.CartItemDetailView.as_view(), name="cart-item-detail"),
    path("clear/", views.CartClearView.as_view(), name="cart-clear"),
    path("summary/", views.CartSummaryView.as_view(), name="cart-summary"),
]
