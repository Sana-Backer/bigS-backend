"""
catalog/urls.py

URL configuration for the catalog app.

Mount this in your project urls.py:
    path("api/", include("catalog.urls")),
"""

from django.urls import path
from . import views

urlpatterns = [
    # ------------------------------------------------------------------
    # Categories
    # ------------------------------------------------------------------
    path(
        "categories/",
        views.CategoryListCreateView.as_view(),
        name="category-list-create",
    ),
    path(
        "categories/tree/",
        views.CategoryTreeView.as_view(),
        name="category-tree",
    ),
    path(
        "categories/<uuid:id>/",
        views.CategoryRetrieveUpdateDestroyView.as_view(),
        name="category-detail",
    ),

    # ------------------------------------------------------------------
    # Products  (specific paths before the generic <uuid:id> pattern)
    # ------------------------------------------------------------------
    path(
        "products/featured/",
        views.FeaturedProductsView.as_view(),
        name="product-featured",
    ),
    path(
        "products/search/",
        views.ProductSearchView.as_view(),
        name="product-search",
    ),
    path(
        "products/by-category/<slug:slug>/",
        views.ProductsByCategoryView.as_view(),
        name="product-by-category",
    ),
    path(
        "products/",
        views.ProductListCreateView.as_view(),
        name="product-list-create",
    ),
    path(
        "products/<uuid:id>/",
        views.ProductRetrieveUpdateDestroyView.as_view(),
        name="product-detail",
    ),

    # ------------------------------------------------------------------
    # Variants  (nested under products + standalone)
    # ------------------------------------------------------------------
    path(
        "products/<uuid:product_id>/variants/",
        views.ProductVariantListCreateView.as_view(),
        name="variant-list-create",
    ),
    path(
        "variants/<uuid:id>/",
        views.ProductVariantDetailView.as_view(),
        name="variant-detail",
    ),

    # ------------------------------------------------------------------
    # Images
    # ------------------------------------------------------------------
    path(
        "products/<uuid:product_id>/images/",
        views.ProductImageCreateView.as_view(),
        name="image-create",
    ),
    path(
        "images/<uuid:id>/",
        views.ProductImageDestroyView.as_view(),
        name="image-delete",
    ),
    path("api/catalog/import/", CatalogImportView.as_view()),
]
