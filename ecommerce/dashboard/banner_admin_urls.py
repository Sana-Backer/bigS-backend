"""
dashboard/banner_admin_urls.py

Mount in root urls.py:
    path("api/admin/banners/", include("dashboard.banner_admin_urls")),

Kept as its own file (rather than folded into urls.py/report_urls.py/
analytics_urls.py) because it mounts at a different prefix — same
reasoning as dashboard/report_urls.py and dashboard/analytics_urls.py
each being split out by their own prefix.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.BannerListCreateView.as_view(), name="admin-banner-list-create"),
    path("<uuid:id>/", views.BannerDetailView.as_view(), name="admin-banner-detail"),
]