"""
catalog/views.py

DRF ViewSets and APIViews for the catalog app.

Endpoints summary
-----------------
Categories
  GET    /api/categories/               – list active
  POST   /api/categories/               – create
  GET    /api/categories/{id}/          – retrieve
  PUT    /api/categories/{id}/          – update
  DELETE /api/categories/{id}/          – soft delete
  GET    /api/categories/tree/          – hierarchical tree

Products
  GET    /api/products/                 – paginated list + filter/search
  POST   /api/products/                 – create
  GET    /api/products/{id}/            – detail
  PUT    /api/products/{id}/            – update
  PATCH  /api/products/{id}/            – partial update
  DELETE /api/products/{id}/            – soft delete
  GET    /api/products/featured/        – featured products
  GET    /api/products/search/          – search alias
  GET    /api/products/by-category/{slug}/ – by category slug

Variants
  GET    /api/products/{product_id}/variants/
  POST   /api/products/{product_id}/variants/
  GET    /api/variants/{id}/
  PUT    /api/variants/{id}/
  DELETE /api/variants/{id}/

Images
  POST   /api/products/{product_id}/images/
  DELETE /api/images/{id}/
"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework import status, filters
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.generics import (
    ListCreateAPIView, RetrieveUpdateDestroyAPIView,
    RetrieveUpdateAPIView, DestroyAPIView, CreateAPIView,
)
from rest_framework.permissions import IsAuthenticatedOrReadOnly
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.viewsets import ViewSet
from django_filters.rest_framework import DjangoFilterBackend
from .pagination import StandardResultsPagination

from .models import Category, Product, ProductVariant, ProductImage
from .serializers import (
    CategorySerializer, CategoryCreateUpdateSerializer,
    ProductListSerializer, ProductDetailSerializer, ProductCreateUpdateSerializer,
    ProductVariantSerializer, ProductVariantCreateUpdateSerializer,
    ProductImageSerializer, ProductImageCreateSerializer,
)
from .filters import ProductFilter


# ---------------------------------------------------------------------------
# Helpers / Utilities
# ---------------------------------------------------------------------------

def success_response(data, status_code=status.HTTP_200_OK, message=None):
    payload = {"status": "success", "data": data}
    if message:
        payload["message"] = message
    return Response(payload, status=status_code)


def error_response(message, status_code, errors=None):
    payload = {"status": "error", "message": message}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=status_code)


# ---------------------------------------------------------------------------
# Category Views
# ---------------------------------------------------------------------------

class CategoryListCreateView(ListCreateAPIView):
    """
    GET  /api/categories/  – list active categories
    POST /api/categories/  – create category (auth required)

    Response (GET):
    {
        "status": "success",
        "data": [ { "id": "...", "name": "Beauty Care", ... }, ... ]
    }
    """

    permission_classes = [IsAuthenticatedOrReadOnly]

    def get_queryset(self):
        return Category.objects.filter(is_active=True).select_related("parent")

    def get_serializer_class(self):
        if self.request.method == "POST":
            return CategoryCreateUpdateSerializer
        return CategorySerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        serializer = CategorySerializer(qs, many=True, context={"request": request})
        return success_response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = CategoryCreateUpdateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        out = CategorySerializer(instance, context={"request": request})
        return success_response(out.data, status.HTTP_201_CREATED, "Category created.")


class CategoryRetrieveUpdateDestroyView(RetrieveUpdateDestroyAPIView):
    """
    GET    /api/categories/{id}/
    PUT    /api/categories/{id}/
    DELETE /api/categories/{id}/  – soft delete
    """

    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = Category.objects.all()
    lookup_field = "id"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return CategoryCreateUpdateSerializer
        return CategorySerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = CategorySerializer(instance, context={"request": request})
        return success_response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = CategoryCreateUpdateSerializer(
            instance, data=request.data, partial=partial,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        out = CategorySerializer(instance, context={"request": request})
        return success_response(out.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return Response(
            {"status": "success", "message": "Category deactivated."},
            status=status.HTTP_204_NO_CONTENT,
        )


class CategoryTreeView(APIView):
    """
    GET /api/categories/tree/

    Returns the full hierarchical category tree (root nodes with nested children).

    Response:
    {
        "status": "success",
        "data": [
            {
                "id": "...", "name": "Beauty Care", "children": [
                    { "id": "...", "name": "Skin Care", "children": [...] }
                ]
            },
            ...
        ]
    }
    """

    def get(self, request):
        roots = (
            Category.objects.filter(is_active=True, parent=None)
            .prefetch_related("children__children")
        )
        serializer = CategorySerializer(roots, many=True, context={"request": request})
        return success_response(serializer.data)


# ---------------------------------------------------------------------------
# Product Views
# ---------------------------------------------------------------------------

PRODUCT_ORDERING_FIELDS = {
    "price": "base_price",
    "-price": "-base_price",
    "created_at": "created_at",
    "-created_at": "-created_at",
}


class ProductListCreateView(ListCreateAPIView):
    """
    GET  /api/products/  – paginated, filterable list
    POST /api/products/  – create product

    Query params:
      ?category=skin-care
      ?brand=Botanica
      ?min_price=5&max_price=50
      ?featured=true
      ?search=cream
      ?ordering=-price
      ?page=2&page_size=10
    """

    permission_classes = [IsAuthenticatedOrReadOnly]
    pagination_class = StandardResultsPagination
    filter_backends = [DjangoFilterBackend, filters.OrderingFilter]
    filterset_class = ProductFilter
    ordering_fields = ["base_price", "created_at"]
    ordering = ["-created_at"]

    def get_queryset(self):
        qs = (
            Product.objects.filter(is_active=True)
            .select_related("category")
            .prefetch_related("images", "variants")
        )
        ordering_param = self.request.query_params.get("ordering")
        if ordering_param and ordering_param in PRODUCT_ORDERING_FIELDS:
            qs = qs.order_by(PRODUCT_ORDERING_FIELDS[ordering_param])
        return qs

    def get_serializer_class(self):
        return ProductCreateUpdateSerializer if self.request.method == "POST" else ProductListSerializer

    def list(self, request, *args, **kwargs):
        qs = self.filter_queryset(self.get_queryset())
        page = self.paginate_queryset(qs)
        if page is not None:
            serializer = ProductListSerializer(page, many=True, context={"request": request})
            return self.get_paginated_response(serializer.data)
        serializer = ProductListSerializer(qs, many=True, context={"request": request})
        return success_response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        serializer = ProductCreateUpdateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        instance = serializer.save()
        return Response(
            {"status": "success", "data": serializer.data, "message": "Product created."},
            status=status.HTTP_201_CREATED,
        )


class ProductRetrieveUpdateDestroyView(RetrieveUpdateDestroyAPIView):
    """
    GET    /api/products/{id}/
    PUT    /api/products/{id}/
    PATCH  /api/products/{id}/
    DELETE /api/products/{id}/
    """

    permission_classes = [IsAuthenticatedOrReadOnly]
    lookup_field = "id"

    def get_queryset(self):
        return (
            Product.objects.filter(is_active=True)
            .select_related("category")
            .prefetch_related("images", "variants__images")
        )

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ProductCreateUpdateSerializer
        return ProductDetailSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ProductDetailSerializer(instance, context={"request": request})
        return success_response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = ProductCreateUpdateSerializer(
            instance, data=request.data, partial=partial,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return success_response(serializer.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return Response(
            {"status": "success", "message": "Product deactivated."},
            status=status.HTTP_204_NO_CONTENT,
        )


class FeaturedProductsView(APIView):
    """GET /api/products/featured/"""

    def get(self, request):
        qs = (
            Product.objects.filter(is_active=True, is_featured=True)
            .select_related("category")
            .prefetch_related("images", "variants")
        )
        serializer = ProductListSerializer(qs, many=True, context={"request": request})
        return success_response(serializer.data)


class ProductSearchView(APIView):
    """
    GET /api/products/search/?search=<term>

    Alias for the list endpoint search – returns matching products.
    """

    def get(self, request):
        term = request.query_params.get("search", "").strip()
        if not term:
            return error_response("Query param `search` is required.", status.HTTP_400_BAD_REQUEST)

        from django.db.models import Q
        qs = (
            Product.objects.filter(is_active=True)
            .filter(
                Q(name__icontains=term)
                | Q(description__icontains=term)
                | Q(short_description__icontains=term)
                | Q(brand__icontains=term)
                | Q(sku__icontains=term)
            )
            .select_related("category")
            .prefetch_related("images", "variants")
        )
        serializer = ProductListSerializer(qs, many=True, context={"request": request})
        return success_response(serializer.data)


class ProductsByCategoryView(APIView):
    """GET /api/products/by-category/{slug}/"""

    def get(self, request, slug):
        category = get_object_or_404(Category, slug=slug, is_active=True)
        qs = (
            Product.objects.filter(is_active=True, category=category)
            .select_related("category")
            .prefetch_related("images", "variants")
        )
        serializer = ProductListSerializer(qs, many=True, context={"request": request})
        return success_response({
            "category": {"id": category.id, "name": category.name, "slug": category.slug},
            "products": serializer.data,
        })


# ---------------------------------------------------------------------------
# Variant Views
# ---------------------------------------------------------------------------

class ProductVariantListCreateView(ListCreateAPIView):
    """
    GET  /api/products/{product_id}/variants/
    POST /api/products/{product_id}/variants/
    """

    permission_classes = [IsAuthenticatedOrReadOnly]

    def _get_product(self):
        return get_object_or_404(Product, id=self.kwargs["product_id"], is_active=True)

    def get_queryset(self):
        product = self._get_product()
        return ProductVariant.objects.filter(product=product, is_active=True).prefetch_related("images")

    def get_serializer_class(self):
        return ProductVariantCreateUpdateSerializer if self.request.method == "POST" else ProductVariantSerializer

    def list(self, request, *args, **kwargs):
        qs = self.get_queryset()
        serializer = ProductVariantSerializer(qs, many=True, context={"request": request})
        return success_response(serializer.data)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        product = self._get_product()
        serializer = ProductVariantCreateUpdateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        variant = serializer.save(product=product)
        out = ProductVariantSerializer(variant, context={"request": request})
        return Response(
            {"status": "success", "data": out.data, "message": "Variant created."},
            status=status.HTTP_201_CREATED,
        )


class ProductVariantDetailView(RetrieveUpdateDestroyAPIView):
    """
    GET    /api/variants/{id}/
    PUT    /api/variants/{id}/
    DELETE /api/variants/{id}/
    """

    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = ProductVariant.objects.filter(is_active=True).prefetch_related("images")
    lookup_field = "id"

    def get_serializer_class(self):
        if self.request.method in ("PUT", "PATCH"):
            return ProductVariantCreateUpdateSerializer
        return ProductVariantSerializer

    def retrieve(self, request, *args, **kwargs):
        instance = self.get_object()
        serializer = ProductVariantSerializer(instance, context={"request": request})
        return success_response(serializer.data)

    @transaction.atomic
    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        serializer = ProductVariantCreateUpdateSerializer(
            instance, data=request.data, partial=partial,
            context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        variant = serializer.save()
        out = ProductVariantSerializer(variant, context={"request": request})
        return success_response(out.data)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.soft_delete()
        return Response(
            {"status": "success", "message": "Variant deactivated."},
            status=status.HTTP_204_NO_CONTENT,
        )


# ---------------------------------------------------------------------------
# Image Views
# ---------------------------------------------------------------------------

class ProductImageCreateView(CreateAPIView):
    """POST /api/products/{product_id}/images/"""

    permission_classes = [IsAuthenticatedOrReadOnly]
    serializer_class = ProductImageCreateSerializer

    def _get_product(self):
        return get_object_or_404(Product, id=self.kwargs["product_id"], is_active=True)

    @transaction.atomic
    def create(self, request, *args, **kwargs):
        product = self._get_product()
        serializer = ProductImageCreateSerializer(
            data=request.data, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        image = serializer.save(product=product)
        out = ProductImageSerializer(image, context={"request": request})
        return Response(
            {"status": "success", "data": out.data, "message": "Image uploaded."},
            status=status.HTTP_201_CREATED,
        )


class ProductImageDestroyView(DestroyAPIView):
    """DELETE /api/images/{id}/"""

    permission_classes = [IsAuthenticatedOrReadOnly]
    queryset = ProductImage.objects.all()
    lookup_field = "id"

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        instance.delete()
        return Response(
            {"status": "success", "message": "Image deleted."},
            status=status.HTTP_204_NO_CONTENT,
        )
