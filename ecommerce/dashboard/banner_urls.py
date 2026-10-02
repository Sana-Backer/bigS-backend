"""
dashboard/banner_urls.py

Mount in root urls.py:
    path("api/banners/", include("dashboard.banner_urls")),

Public surface — no "admin" in the path, no auth. This is what the
storefront's home screen actually calls.
"""

from django.urls import path

from . import views

urlpatterns = [
    path("", views.PublicActiveBannersView.as_view(), name="public-banner-list"),
]