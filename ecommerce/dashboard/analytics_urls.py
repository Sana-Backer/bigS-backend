"""
dashboard/analytics_urls.py

Mount in root urls.py:
    path("api/admin/analytics/", include("dashboard.analytics_urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("revenue-trend/", views.RevenueTrendView.as_view(), name="analytics-revenue-trend"),
    path("category-performance/", views.CategoryPerformanceView.as_view(), name="analytics-category-performance"),
    path("customer-growth/", views.CustomerGrowthView.as_view(), name="analytics-customer-growth"),
    path("average-order-value/", views.AverageOrderValueView.as_view(), name="analytics-average-order-value"),
]
