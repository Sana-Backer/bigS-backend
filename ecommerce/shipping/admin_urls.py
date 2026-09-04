"""
shipping/admin_urls.py

Mount in root urls.py:
    path("api/admin/", include("shipping.admin_urls")),

Kept separate from shipping/urls.py (which mounts under /api/shipping/)
because these routes live under /api/admin/... instead — same pattern
payments/admin_urls.py already uses.
"""

from django.urls import path

from . import views

urlpatterns = [
    path(
        "orders/<uuid:order_id>/shipping/create/",
        views.AdminCreateShipmentView.as_view(),
        name="admin-shipment-create",
    ),
    path(
        "shipments/<uuid:id>/assign-awb/",
        views.AdminAssignAWBView.as_view(),
        name="admin-shipment-assign-awb",
    ),
    path(
        "shipments/<uuid:id>/label/",
        views.AdminGenerateLabelView.as_view(),
        name="admin-shipment-label",
    ),
    path(
        "shipments/<uuid:id>/manifest/",
        views.AdminGenerateManifestView.as_view(),
        name="admin-shipment-manifest",
    ),
    path(
        "shipments/<uuid:id>/tracking/",
        views.AdminShipmentTrackingView.as_view(),
        name="admin-shipment-tracking",
    ),
    path(
        "shipments/<uuid:id>/cancel/",
        views.AdminCancelShipmentView.as_view(),
        name="admin-shipment-cancel",
    ),
]
