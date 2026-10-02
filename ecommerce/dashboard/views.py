"""
dashboard/views.py

All views here are staff-only (reuses users.permissions.IsManagerOrAdmin
— same role gate as orders/payments admin surfaces: "viewing all
orders, financial reports" already covers dashboard/report data) and
read-only (GET). Query params are validated by a serializer, the
actual work happens in services.py, and results go out through the
project's common.responses.ok() envelope.
"""

from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView
 
from catalog.pagination import StandardResultsPagination
from common.responses import created, ok
from users.permissions import IsManagerOrAdmin
 
from . import selectors, services
from .serializers import (
    BannerCreateUpdateSerializer,
    BannerSerializer,
    CustomerReportQuerySerializer,
    DashboardOverviewQuerySerializer,
    DateRangeQuerySerializer,
    InventoryReportQuerySerializer,
    LimitQuerySerializer,
    PeriodQuerySerializer,
    ProductReportQuerySerializer,
    RecentOrdersQuerySerializer,
    RevenueOverviewQuerySerializer,
    SalesReportQuerySerializer,
)



class AdminReadOnlyView(APIView):
    """Shared base: staff/admin only, GET-only surface."""

    permission_classes = [IsAuthenticated, IsManagerOrAdmin]


def _paginate(request, data: list):
    paginator = StandardResultsPagination()
    page = paginator.paginate_queryset(data, request)
    return paginator.get_paginated_response(page)


# ---------------------------------------------------------------------------
# Dashboard — /api/admin/dashboard/
# ---------------------------------------------------------------------------

class DashboardOverviewView(AdminReadOnlyView):
    """GET /api/admin/dashboard/overview/?range=7d|30d|90d|1y"""

    def get(self, request):
        query = DashboardOverviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_dashboard_overview(range_key=query.validated_data["range"])
        return ok(data, "Dashboard overview retrieved successfully.")


class SalesAnalyticsView(AdminReadOnlyView):
    """GET /api/admin/dashboard/sales-analytics/?period=daily|weekly|monthly|yearly"""

    def get(self, request):
        query = PeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_sales_analytics(period=query.validated_data["period"])
        return ok(data, "Sales analytics retrieved successfully.")


class TopSellingProductsView(AdminReadOnlyView):
    """GET /api/admin/dashboard/top-selling/?limit=&date_from=&date_to="""

    def get(self, request):
        query = LimitQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_top_selling_products(
            limit=query.validated_data["limit"],
            date_from=query.validated_data.get("date_from"),
            date_to=query.validated_data.get("date_to"),
        )
        return ok(data, "Top selling products retrieved successfully.")


class TopCategoriesView(AdminReadOnlyView):
    """GET /api/admin/dashboard/top-categories/?date_from=&date_to="""

    def get(self, request):
        query = DateRangeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_top_categories(
            date_from=query.validated_data.get("date_from"),
            date_to=query.validated_data.get("date_to"),
        )
        return ok(data, "Top categories retrieved successfully.")


class RevenueOverviewView(AdminReadOnlyView):
    """GET /api/admin/dashboard/revenue-overview/?months=7"""

    def get(self, request):
        query = RevenueOverviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_revenue_overview(months=query.validated_data["months"])
        return ok(data, "Revenue overview retrieved successfully.")


class RecentOrdersView(AdminReadOnlyView):
    """GET /api/admin/dashboard/recent-orders/?limit=10"""

    def get(self, request):
        query = RecentOrdersQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_recent_orders(limit=query.validated_data["limit"])
        return ok(data, "Recent orders retrieved successfully.")


# ---------------------------------------------------------------------------
# Reports — /api/admin/reports/
# ---------------------------------------------------------------------------

class SalesReportView(AdminReadOnlyView):
    """GET /api/admin/reports/sales/?date_from=&date_to=&group_by=day|week|month"""

    def get(self, request):
        query = SalesReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_sales_report(
            date_from=query.validated_data["date_from"],
            date_to=query.validated_data["date_to"],
            group_by=query.validated_data["group_by"],
        )
        return _paginate(request, data)


class ProductPerformanceReportView(AdminReadOnlyView):
    """GET /api/admin/reports/products/?date_from=&date_to=&ordering=-revenue"""

    def get(self, request):
        query = ProductReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_product_performance_report(
            date_from=query.validated_data.get("date_from"),
            date_to=query.validated_data.get("date_to"),
            ordering=query.validated_data["ordering"],
        )
        return _paginate(request, data)


class CustomerReportView(AdminReadOnlyView):
    """GET /api/admin/reports/customers/?date_from=&date_to=&ordering=-total_spent"""

    def get(self, request):
        query = CustomerReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_customer_report(
            date_from=query.validated_data.get("date_from"),
            date_to=query.validated_data.get("date_to"),
            ordering=query.validated_data["ordering"],
        )
        return _paginate(request, data)


class InventoryReportView(AdminReadOnlyView):
    """GET /api/admin/reports/inventory/?low_stock_threshold=10"""

    def get(self, request):
        query = InventoryReportQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_inventory_report(
            low_stock_threshold=query.validated_data["low_stock_threshold"],
        )
        return _paginate(request, data)


class OrderStatusBreakdownView(AdminReadOnlyView):
    """GET /api/admin/reports/order-status/"""

    def get(self, request):
        data = services.get_order_status_breakdown()
        return ok(data, "Order status breakdown retrieved successfully.")


# ---------------------------------------------------------------------------
# Analytics — /api/admin/analytics/
# ---------------------------------------------------------------------------

class RevenueTrendView(AdminReadOnlyView):
    """GET /api/admin/analytics/revenue-trend/?period=daily|weekly|monthly|yearly"""

    def get(self, request):
        query = PeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_revenue_trend(period=query.validated_data["period"])
        return ok(data, "Revenue trend retrieved successfully.")


class CategoryPerformanceView(AdminReadOnlyView):
    """GET /api/admin/analytics/category-performance/?date_from=&date_to="""

    def get(self, request):
        query = DateRangeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_category_performance(
            date_from=query.validated_data.get("date_from"),
            date_to=query.validated_data.get("date_to"),
        )
        return ok(data, "Category performance retrieved successfully.")


class CustomerGrowthView(AdminReadOnlyView):
    """GET /api/admin/analytics/customer-growth/?period=daily|weekly|monthly|yearly"""

    def get(self, request):
        query = PeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_customer_growth(period=query.validated_data["period"])
        return ok(data, "Customer growth retrieved successfully.")


class AverageOrderValueView(AdminReadOnlyView):
    """GET /api/admin/analytics/average-order-value/?period=daily|weekly|monthly|yearly"""

    def get(self, request):
        query = PeriodQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = services.get_average_order_value_trend(period=query.validated_data["period"])
        return ok(data, "Average order value trend retrieved successfully.")


class BannerListCreateView(AdminReadOnlyView):
    """
    GET  /api/admin/banners/?placement=&is_active=  — paginated, newest first within ordering.
    POST /api/admin/banners/                         — create a new banner.
 
    Named AdminReadOnlyView above refers to the base class's original
    read-only-reports purpose; this view itself also handles POST, so
    it does not actually stay read-only — only the IsManagerOrAdmin gate
    it provides is being reused here.
    """
 
    def get(self, request):
        qs = selectors.get_banner_queryset()
        placement = request.query_params.get("placement")
        if placement:
            qs = qs.filter(placement=placement)
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() in ("1", "true", "yes"))
 
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(
            BannerSerializer(page, many=True, context={"request": request}).data
        )
 
    def post(self, request):
        serializer = BannerCreateUpdateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        banner = serializer.save()
        return created(BannerSerializer(banner, context={"request": request}).data, "Banner created successfully.")
 
 
class BannerDetailView(AdminReadOnlyView):
    """
    GET    /api/admin/banners/<uuid:id>/
    PATCH  /api/admin/banners/<uuid:id>/
    PUT    /api/admin/banners/<uuid:id>/
    DELETE /api/admin/banners/<uuid:id>/
    """
 
    def get(self, request, id):
        banner = selectors.get_banner_for_admin(id)
        return ok(BannerSerializer(banner, context={"request": request}).data, "Banner retrieved successfully.")
 
    def patch(self, request, id):
        banner = selectors.get_banner_for_admin(id)
        serializer = BannerCreateUpdateSerializer(
            banner, data=request.data, partial=True, context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        banner = serializer.save()
        return ok(BannerSerializer(banner, context={"request": request}).data, "Banner updated successfully.")
 
    def put(self, request, id):
        banner = selectors.get_banner_for_admin(id)
        serializer = BannerCreateUpdateSerializer(banner, data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        banner = serializer.save()
        return ok(BannerSerializer(banner, context={"request": request}).data, "Banner updated successfully.")
 
    def delete(self, request, id):
        banner = selectors.get_banner_for_admin(id)
        banner.delete()
        return ok({}, "Banner deleted successfully.")
 
 
class PublicActiveBannersView(APIView):
    """
    GET /api/banners/?placement=home_hero
 
    Public, read-only — the storefront's home screen calls this
    directly (no auth). Only ever returns banners that are both
    is_active and currently inside their start_at/end_at window; see
    selectors.get_active_banners().
    """
 
    permission_classes = [AllowAny]
 
    def get(self, request):
        qs = selectors.get_active_banners(placement=request.query_params.get("placement"))
        return ok(BannerSerializer(qs, many=True, context={"request": request}).data, "Banners retrieved successfully.")
 
