"""
dashboard/urls.py

Mount in root urls.py:
    path("api/admin/dashboard/", include("dashboard.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("overview/", views.DashboardOverviewView.as_view(), name="dashboard-overview"),
    path("sales-analytics/", views.SalesAnalyticsView.as_view(), name="dashboard-sales-analytics"),
    path("top-selling/", views.TopSellingProductsView.as_view(), name="dashboard-top-selling"),
    path("top-categories/", views.TopCategoriesView.as_view(), name="dashboard-top-categories"),
    path("revenue-overview/", views.RevenueOverviewView.as_view(), name="dashboard-revenue-overview"),
    path("recent-orders/", views.RecentOrdersView.as_view(), name="dashboard-recent-orders"),
]
