"""
wishlist/urls.py

Mount in root urls.py:
    path("api/wishlist/", include("wishlist.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.WishlistDetailView.as_view(), name="wishlist-detail"),
    path("items/", views.WishlistItemCreateView.as_view(), name="wishlist-item-create"),
    path("items/<uuid:id>/", views.WishlistItemDestroyView.as_view(), name="wishlist-item-destroy"),
    path("items/<uuid:id>/move-to-cart/", views.WishlistItemMoveToCartView.as_view(), name="wishlist-item-move-to-cart"),
]
