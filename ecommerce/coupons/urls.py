"""
coupons/urls.py

Mount in root urls.py:
    path("api/", include("coupons.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    # Cart-facing
    path("coupons/apply/", views.CouponApplyView.as_view(), name="coupon-apply"),
    path("coupons/remove/", views.CouponRemoveView.as_view(), name="coupon-remove"),

    # Admin
    path("admin/coupons/", views.AdminCouponListCreateView.as_view(), name="admin-coupon-list"),
    path("admin/coupons/<uuid:id>/", views.AdminCouponDetailView.as_view(), name="admin-coupon-detail"),
]
