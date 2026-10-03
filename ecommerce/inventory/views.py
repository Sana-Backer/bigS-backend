"""
inventory/views.py

Mounted at /api/admin/inventory/  (see urls.py)

Stock
  GET  stock/                 levels   ?status=in_stock|low|out|attention &q= &category=<slug> &kind=variant|product
  GET  stock/summary/         headline numbers
  POST stock/adjust/          +/- change with a reason            (staff+)
  POST stock/bulk-adjust/     many adjustments, all-or-nothing    (staff+)
  POST stock/set/             absolute count (stocktake)          (manager+)
  GET  stock/export/          .xlsx of current levels
  POST stock/import/          .xlsx stocktake  [?dry_run=true]    (manager+)
  GET  movements/             ledger  ?sku= &variant= &product= &type= &reference= &date_from= &date_to=
Setup
  GET/POST  policies/   GET/PUT/PATCH/DELETE  policies/<id>/
  GET/POST  suppliers/  GET/PUT/PATCH/DELETE  suppliers/<id>/
Purchasing
  GET/POST  purchase-orders/        GET/PUT/PATCH purchase-orders/<id>/
  POST      purchase-orders/<id>/mark-ordered/ | receive/ | cancel/

Reads need staff+. Catalog-wide setup (policies, suppliers, POs, stocktake,
imports) needs manager+. Day-to-day adjust/receive is open to staff.
"""

from datetime import datetime

from django.http import HttpResponse
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import IsAuthenticated, SAFE_METHODS, BasePermission
from rest_framework.views import APIView

from common.responses import ok, created, err
from users.permissions import IsManagerOrAdmin, IsStaffOrAbove, _is_at_least_manager, _is_at_least_staff

from . import excel, selectors, services
from .exceptions import InventoryError
from .models import PurchaseOrder, StockMovement, StockPolicy, Supplier
from .serializers import (
    AdjustSerializer, BulkAdjustSerializer, PurchaseOrderSerializer, ReceiveSerializer,
    SetStockSerializer, StockMovementSerializer, StockPolicySerializer, SupplierSerializer,
)

STAFF_READ = [IsAuthenticated, IsStaffOrAbove]


class StaffReadManagerWrite(BasePermission):
    message = "Changing this requires Manager or Admin role."

    def has_permission(self, request, view):
        u = request.user
        if request.method in SAFE_METHODS:
            return bool(u and _is_at_least_staff(u))
        return bool(u and _is_at_least_manager(u))


class InventoryErrorMixin:
    """Turn expected InventoryErrors into the project's {"status": "error"} envelope."""

    def handle_exception(self, exc):
        if isinstance(exc, InventoryError):
            return err(str(exc), status.HTTP_400_BAD_REQUEST)
        return super().handle_exception(exc)


class InvAPIView(InventoryErrorMixin, APIView):
    permission_classes = STAFF_READ


def _parse_date(value, name):
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError({name: "Use YYYY-MM-DD."})


# ---------------------------------------------------------------------------
# Stock levels
# ---------------------------------------------------------------------------

class StockListView(InvAPIView):
    def get(self, request):
        q = request.query_params
        rows = selectors.stock_rows(
            search=q.get("q"), category_slug=q.get("category"),
            status=q.get("status"), kind=q.get("kind"),
        )
        from catalog.pagination import StandardResultsPagination
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(rows, request, view=self)
        return paginator.get_paginated_response(page)


class StockSummaryView(InvAPIView):
    def get(self, request):
        return ok(selectors.stock_summary())


class StockAdjustView(InvAPIView):
    def post(self, request):
        s = AdjustSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        target = services.resolve_target(product_id=d.get("product_id"), variant_id=d.get("variant_id"))
        mv = services.record_movement(target, d["change"], d["movement_type"],
                                      reference=d["reference"], note=d["note"], user=request.user)
        return created(StockMovementSerializer(mv).data, "Stock adjusted.")


class StockBulkAdjustView(InvAPIView):
    def post(self, request):
        s = BulkAdjustSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        items = []
        for d in s.validated_data["items"]:
            items.append({
                "target": services.resolve_target(product_id=d.get("product_id"), variant_id=d.get("variant_id")),
                "change": d["change"], "movement_type": d["movement_type"],
                "reference": d["reference"], "note": d["note"],
            })
        movements = services.bulk_adjust(items, user=request.user)
        return created(StockMovementSerializer(movements, many=True).data, f"{len(movements)} adjustment(s) applied.")


class StockSetView(InvAPIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request):
        s = SetStockSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        d = s.validated_data
        target = services.resolve_target(product_id=d.get("product_id"), variant_id=d.get("variant_id"))
        mv = services.set_stock(target, d["quantity"], note=d["note"], reference=d["reference"], user=request.user)
        if mv is None:
            return ok({"stock_quantity": target.stock_quantity}, "Already at that quantity – nothing changed.")
        return created(StockMovementSerializer(mv).data, "Stock set.")


class StockExportView(InvAPIView):
    def get(self, request):
        q = request.query_params
        rows = selectors.stock_rows(search=q.get("q"), category_slug=q.get("category"),
                                    status=q.get("status"), kind=q.get("kind"))
        resp = HttpResponse(
            excel.export_stock(rows),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        resp["Content-Disposition"] = f'attachment; filename="stock-{timezone.now():%Y%m%d-%H%M}.xlsx"'
        return resp


class StockImportView(InvAPIView):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]
    parser_classes = [MultiPartParser]

    def post(self, request):
        upload = request.FILES.get("file")
        if not upload or not upload.name.lower().endswith(".xlsx"):
            return err("Upload an .xlsx file in the 'file' field.")
        dry = request.query_params.get("dry_run", "").lower() in ("1", "true", "yes")
        result = excel.import_stocktake(upload, user=request.user, dry_run=dry)
        if not result["ok"]:
            return err("Import rejected – fix the errors and re-upload. Nothing was changed.",
                       status.HTTP_400_BAD_REQUEST, errors=result["errors"])
        return ok(result, "Dry run only – nothing was changed." if dry else
                  f"Stocktake applied: {len(result['changes'])} item(s) changed.")


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------

class MovementListView(InventoryErrorMixin, generics.ListAPIView):
    permission_classes = STAFF_READ
    serializer_class = StockMovementSerializer
    filter_backends = []  # plain, explicit filtering below

    def get_queryset(self):
        q = self.request.query_params
        qs = StockMovement.objects.select_related("created_by")
        if q.get("sku"):
            qs = qs.filter(sku__iexact=q["sku"])
        if q.get("variant"):
            qs = qs.filter(variant_id=q["variant"])
        if q.get("product"):
            qs = qs.filter(product_id=q["product"])
        if q.get("type"):
            qs = qs.filter(movement_type=q["type"])
        if q.get("reference"):
            qs = qs.filter(reference__iexact=q["reference"])
        df, dt = _parse_date(q.get("date_from"), "date_from"), _parse_date(q.get("date_to"), "date_to")
        if df:
            qs = qs.filter(created_at__date__gte=df)
        if dt:
            qs = qs.filter(created_at__date__lte=dt)
        return qs


# ---------------------------------------------------------------------------
# Policies & suppliers
# ---------------------------------------------------------------------------

class PolicyListCreateView(InventoryErrorMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, StaffReadManagerWrite]
    serializer_class = StockPolicySerializer
    queryset = StockPolicy.objects.select_related("product", "variant")
    filter_backends = []


class PolicyDetailView(InventoryErrorMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, StaffReadManagerWrite]
    serializer_class = StockPolicySerializer
    queryset = StockPolicy.objects.all()
    lookup_field = "id"


class SupplierListCreateView(InventoryErrorMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, StaffReadManagerWrite]
    serializer_class = SupplierSerializer
    queryset = Supplier.objects.all()
    filter_backends = []


class SupplierDetailView(InventoryErrorMixin, generics.RetrieveUpdateDestroyAPIView):
    permission_classes = [IsAuthenticated, StaffReadManagerWrite]
    serializer_class = SupplierSerializer
    queryset = Supplier.objects.all()
    lookup_field = "id"

    def perform_destroy(self, instance):
        # Suppliers with history are deactivated, not deleted.
        if instance.purchase_orders.exists():
            instance.is_active = False
            instance.save(update_fields=["is_active", "updated_at"])
        else:
            instance.delete()


# ---------------------------------------------------------------------------
# Purchase orders
# ---------------------------------------------------------------------------

class PurchaseOrderListCreateView(InventoryErrorMixin, generics.ListCreateAPIView):
    permission_classes = [IsAuthenticated, StaffReadManagerWrite]
    serializer_class = PurchaseOrderSerializer
    filter_backends = []

    def get_queryset(self):
        qs = PurchaseOrder.objects.select_related("supplier").prefetch_related("items")
        s = self.request.query_params.get("status")
        return qs.filter(status=s) if s else qs


class PurchaseOrderDetailView(InventoryErrorMixin, generics.RetrieveUpdateAPIView):
    permission_classes = [IsAuthenticated, StaffReadManagerWrite]
    serializer_class = PurchaseOrderSerializer
    queryset = PurchaseOrder.objects.select_related("supplier").prefetch_related("items")
    lookup_field = "id"


class _PoAction(InvAPIView):
    def get_po(self, id):
        from django.shortcuts import get_object_or_404
        return get_object_or_404(PurchaseOrder, pk=id)


class PurchaseOrderMarkOrderedView(_PoAction):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        po = services.mark_ordered(self.get_po(id))
        return ok(PurchaseOrderSerializer(po, context={"request": request}).data, "Marked as ordered.")


class PurchaseOrderCancelView(_PoAction):
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        po = services.cancel_purchase_order(self.get_po(id))
        return ok(PurchaseOrderSerializer(po, context={"request": request}).data, "Purchase order cancelled.")


class PurchaseOrderReceiveView(_PoAction):
    """Staff can receive deliveries."""

    def post(self, request, id):
        s = ReceiveSerializer(data=request.data)
        s.is_valid(raise_exception=True)
        lines = s.validated_data.get("lines")
        lines = [{"item_id": str(l["item_id"]), "quantity": l["quantity"]} for l in lines] if lines else None
        po = services.receive_purchase_order(self.get_po(id), lines, user=request.user)
        return ok(PurchaseOrderSerializer(po, context={"request": request}).data, "Stock received.")
