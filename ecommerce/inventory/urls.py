"""
inventory/urls.py

Root urls.py:
    path("api/admin/inventory/", include("inventory.urls")),
"""

from django.urls import path

from . import views

urlpatterns = [
    path("stock/", views.StockListView.as_view(), name="inventory-stock"),
    path("stock/summary/", views.StockSummaryView.as_view(), name="inventory-summary"),
    path("stock/adjust/", views.StockAdjustView.as_view(), name="inventory-adjust"),
    path("stock/bulk-adjust/", views.StockBulkAdjustView.as_view(), name="inventory-bulk-adjust"),
    path("stock/set/", views.StockSetView.as_view(), name="inventory-set"),
    path("stock/export/", views.StockExportView.as_view(), name="inventory-export"),
    path("stock/import/", views.StockImportView.as_view(), name="inventory-import"),
    path("movements/", views.MovementListView.as_view(), name="inventory-movements"),

    path("policies/", views.PolicyListCreateView.as_view(), name="inventory-policy-list"),
    path("policies/<uuid:id>/", views.PolicyDetailView.as_view(), name="inventory-policy-detail"),
    path("suppliers/", views.SupplierListCreateView.as_view(), name="inventory-supplier-list"),
    path("suppliers/<uuid:id>/", views.SupplierDetailView.as_view(), name="inventory-supplier-detail"),

    path("purchase-orders/", views.PurchaseOrderListCreateView.as_view(), name="inventory-po-list"),
    path("purchase-orders/<uuid:id>/", views.PurchaseOrderDetailView.as_view(), name="inventory-po-detail"),
    path("purchase-orders/<uuid:id>/mark-ordered/", views.PurchaseOrderMarkOrderedView.as_view(), name="inventory-po-order"),
    path("purchase-orders/<uuid:id>/receive/", views.PurchaseOrderReceiveView.as_view(), name="inventory-po-receive"),
    path("purchase-orders/<uuid:id>/cancel/", views.PurchaseOrderCancelView.as_view(), name="inventory-po-cancel"),
]
