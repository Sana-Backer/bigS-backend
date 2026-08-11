"""
coupons/views.py

Cart-facing:
  POST   /api/coupons/apply/
  DELETE /api/coupons/remove/

Admin (reuses users.permissions — IsStaffOrAbove for read, IsAdminRole
for write, same pattern already used by AdminUserListCreateView etc.):
  GET    /api/admin/coupons/
  POST   /api/admin/coupons/
  GET    /api/admin/coupons/<uuid:id>/
  PATCH  /api/admin/coupons/<uuid:id>/
  DELETE /api/admin/coupons/<uuid:id>/
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.views import APIView

from cart import selectors as cart_selectors
from cart import services as cart_services
from cart.pricing import calculate_cart_totals
from common.responses import created, no_content, ok
from users.permissions import IsAdminRole, IsAuthenticatedOrGuest, IsStaffOrAbove

from . import services
from .models import Coupon
from .serializers import (
    ApplyCouponSerializer,
    CouponCreateUpdateSerializer,
    CouponSerializer,
)


# ---------------------------------------------------------------------------
# Cart-facing
# ---------------------------------------------------------------------------

class CouponApplyView(APIView):
    """POST /api/coupons/apply/  Body: {"code": "SUMMER10"}"""

    permission_classes = [IsAuthenticatedOrGuest]

    @transaction.atomic
    def post(self, request):
        serializer = ApplyCouponSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        user, guest_session = cart_selectors.resolve_owner(request)
        cart = cart_services.get_or_create_cart(user=user, guest_session=guest_session)

        services.apply_coupon_to_cart(
            cart, serializer.validated_data["code"], user=user, guest_session=guest_session
        )
        totals = calculate_cart_totals(cart)
        return ok(
            {"coupon_code": cart.coupon.code, **totals},
            "Coupon applied successfully.",
        )


class CouponRemoveView(APIView):
    """DELETE /api/coupons/remove/"""

    permission_classes = [IsAuthenticatedOrGuest]

    @transaction.atomic
    def delete(self, request):
        user, guest_session = cart_selectors.resolve_owner(request)
        cart = cart_services.get_or_create_cart(user=user, guest_session=guest_session)
        services.remove_coupon_from_cart(cart)
        totals = calculate_cart_totals(cart)
        return ok(totals, "Coupon removed from cart.")


# ---------------------------------------------------------------------------
# Admin
# ---------------------------------------------------------------------------

class AdminCouponListCreateView(APIView):
    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated(), IsStaffOrAbove()]

    def get(self, request):
        qs = Coupon.objects.all().order_by("-created_at")
        is_active = request.query_params.get("is_active")
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        search = request.query_params.get("search", "").strip()
        if search:
            qs = qs.filter(code__icontains=search)

        from catalog.pagination import StandardResultsPagination
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(CouponSerializer(page, many=True).data)

    @transaction.atomic
    def post(self, request):
        serializer = CouponCreateUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        coupon = serializer.save()
        return created(CouponSerializer(coupon).data, "Coupon created.")


class AdminCouponDetailView(APIView):
    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsStaffOrAbove()]
        return [IsAuthenticated(), IsAdminRole()]

    def _get(self, id):
        return get_object_or_404(Coupon, id=id)

    def get(self, request, id):
        return ok(CouponSerializer(self._get(id)).data)

    @transaction.atomic
    def patch(self, request, id):
        coupon = self._get(id)
        serializer = CouponCreateUpdateSerializer(coupon, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok(CouponSerializer(coupon).data, "Coupon updated.")

    def delete(self, request, id):
        coupon = self._get(id)
        coupon.is_active = False
        coupon.save(update_fields=["is_active", "updated_at"])
        return no_content("Coupon deactivated.")
