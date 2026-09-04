"""
ecommerce/urls.py – root URL configuration.
"""

from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/", include("users.urls")),
    path("api/", include("catalog.urls")),
    path("api/cart/", include("cart.urls")),
    path("api/", include("coupons.urls")),
    path("api/wishlist/", include("wishlist.urls")),
    path("api/", include("orders.urls")),
    path("api/checkout/", include("checkout.urls")),
    path("api/payments/", include("payments.urls")),
    path("api/admin/", include("payments.admin_urls")),
    path("api/shipping/", include("shipping.urls")),
    path("api/admin/", include("shipping.admin_urls")),
    path("api/", include("shipping.order_urls")),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
