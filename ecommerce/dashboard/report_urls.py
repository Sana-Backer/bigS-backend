"""
dashboard/report_urls.py

Mount in root urls.py:
    path("api/admin/reports/", include("dashboard.report_urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("sales/", views.SalesReportView.as_view(), name="report-sales"),
    path("products/", views.ProductPerformanceReportView.as_view(), name="report-products"),
    path("customers/", views.CustomerReportView.as_view(), name="report-customers"),
    path("inventory/", views.InventoryReportView.as_view(), name="report-inventory"),
    path("order-status/", views.OrderStatusBreakdownView.as_view(), name="report-order-status"),
]
