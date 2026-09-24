"""
catalog/models.py

Core models for the eCommerce catalog:
  - Category (hierarchical)
  - Product
  - ProductVariant
  - ProductImage
"""

import uuid
from django.db import models
from django.utils.text import slugify
from django.core.exceptions import ValidationError


# ---------------------------------------------------------------------------
# Mixins
# ---------------------------------------------------------------------------

class TimeStampedModel(models.Model):
    """Abstract base that adds created_at / updated_at to every model."""

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Category
# ---------------------------------------------------------------------------

class Category(TimeStampedModel):
    """
    Product category supporting unlimited parent/child hierarchy.

    Example tree:
        Beauty Care  (parent=None)
        └─ Skin Care  (parent=Beauty Care)
           └─ Moisturisers
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=200)
    slug = models.SlugField(max_length=220, unique=True, blank=True)
    description = models.TextField(blank=True)
    image = models.ImageField(upload_to="categories/", blank=True, null=True)
    parent = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="children",
    )
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Category"
        verbose_name_plural = "Categories"
        ordering = ["name"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        # Auto-generate slug from name if not supplied
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        base = slugify(self.name)
        slug = base
        n = 1
        while Category.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    def soft_delete(self):
        """Deactivate this category (and cascade to children)."""
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])
        self.children.filter(is_active=True).update(is_active=False)


# ---------------------------------------------------------------------------
# Product
# ---------------------------------------------------------------------------

class Product(TimeStampedModel):
    """
    A sellable product in the catalog.

    base_price  – the regular / original price
    sale_price  – optional discounted price (must be <= base_price)
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="products",
    )
    name = models.CharField(max_length=300)
    slug = models.SlugField(max_length=320, unique=True, blank=True)
    sku = models.CharField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    short_description = models.CharField(max_length=500, blank=True)
    brand = models.CharField(max_length=200, blank=True, db_index=True)

    base_price = models.DecimalField(max_digits=12, decimal_places=2)
    sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )

    # ------------------------------------------------------------------
    # Product detail page content (About / Ingredients / Usage / FAQ tabs)
    # ------------------------------------------------------------------

    about_title = models.CharField(
        max_length=300,
        blank=True,
        help_text=(
            "Small caption/overline shown directly above the About tab's "
            "description, e.g. 'ABOUT THE PRODUCT'."
        ),
    )
    about_heading = models.CharField(
        max_length=500,
        blank=True,
        help_text=(
            "Large heading statement for the product (shown in the page's "
            "hero/summary section), e.g. 'A boost of anti-oxidant rich "
            "nourishing renewal for dull, dry and tired skin.'"
        ),
    )
    recommended_for = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Bullet list shown under 'Recommended For', e.g. "
            '["Dull Skin", "Hyper Pigmentation", "Uneven Skin Tone"]'
        ),
    )
    good_to_know = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Bullet list shown under 'Good To Know', e.g. "
            '["pH: 4.8", "Vegan, Cruelty-Free", "For All Skin-Types"]'
        ),
    )
    ingredients_title = models.CharField(
        max_length=300,
        blank=True,
        help_text="Heading shown above the Ingredients tab's content.",
    )
    ingredients = models.TextField(
        blank=True,
        help_text="Content for the 'Ingredients' tab on the product page.",
    )
    usage = models.TextField(
        blank=True,
        help_text="Content for the 'Usage' tab on the product page (how to use).",
    )
    faqs = models.JSONField(
        default=list,
        blank=True,
        help_text=(
            "Content for the 'FAQ' tab. List of objects, e.g. "
            '[{"question": "Is this vegan?", "answer": "Yes, fully vegan."}]'
        ),
    )

    is_featured = models.BooleanField(default=False, db_index=True)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Product"
        verbose_name_plural = "Products"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["slug"]),
            models.Index(fields=["sku"]),
            models.Index(fields=["is_active", "is_featured"]),
            models.Index(fields=["brand"]),
        ]

    def __str__(self):
        return self.name

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self):
        if self.sale_price is not None and self.sale_price > self.base_price:
            raise ValidationError(
                {"sale_price": "sale_price must be less than or equal to base_price."}
            )

        for field_name in ("recommended_for", "good_to_know"):
            value = getattr(self, field_name)
            if value in (None, ""):
                setattr(self, field_name, [])
                continue
            if not isinstance(value, list) or not all(
                isinstance(item, str) for item in value
            ):
                raise ValidationError(
                    {field_name: f"{field_name} must be a list of strings."}
                )

        if self.faqs in (None, ""):
            self.faqs = []
        elif not isinstance(self.faqs, list) or not all(
            isinstance(item, dict) and "question" in item and "answer" in item
            for item in self.faqs
        ):
            raise ValidationError(
                {"faqs": "faqs must be a list of objects with 'question' and 'answer' keys."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        if not self.slug:
            self.slug = self._unique_slug()
        super().save(*args, **kwargs)

    def _unique_slug(self):
        base = slugify(self.name)
        slug = base
        n = 1
        while Product.objects.filter(slug=slug).exclude(pk=self.pk).exists():
            slug = f"{base}-{n}"
            n += 1
        return slug

    # ------------------------------------------------------------------
    # Computed helpers (also exposed as serializer fields)
    # ------------------------------------------------------------------

    @property
    def effective_price(self):
        """The price the customer actually pays."""
        return self.sale_price if self.sale_price is not None else self.base_price

    @property
    def discount_percentage(self):
        """Percentage discount vs base_price, or 0 if no sale."""
        if self.sale_price and self.base_price:
            discount = ((self.base_price - self.sale_price) / self.base_price) * 100
            return round(float(discount), 1)
        return 0

    def soft_delete(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


# ---------------------------------------------------------------------------
# ProductVariant
# ---------------------------------------------------------------------------

class ProductVariant(TimeStampedModel):
    """
    A specific variant of a product (e.g. "500 ml – Lavender").

    `attributes` is a free-form JSON dict, e.g.:
        {"size": "500ml", "fragrance": "lavender", "colour": "purple"}

    Uniqueness of attribute combinations is enforced in clean() below.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product, on_delete=models.CASCADE, related_name="variants"
    )
    name = models.CharField(max_length=300)
    sku = models.CharField(max_length=100, unique=True)
    attributes = models.JSONField(default=dict, blank=True)

    price = models.DecimalField(max_digits=12, decimal_places=2)
    sale_price = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    stock_quantity = models.PositiveIntegerField(default=0)
    weight = models.DecimalField(
        max_digits=8, decimal_places=3, null=True, blank=True,
        help_text="Weight in kilograms"
    )

    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)

    class Meta:
        verbose_name = "Product Variant"
        verbose_name_plural = "Product Variants"
        ordering = ["product", "name"]
        indexes = [
            models.Index(fields=["sku"]),
            models.Index(fields=["is_active"]),
        ]

    def __str__(self):
        return f"{self.product.name} – {self.name}"

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    def clean(self):
        # 1. sale_price check
        if self.sale_price is not None and self.sale_price > self.price:
            raise ValidationError(
                {"sale_price": "sale_price must be <= price for this variant."}
            )

        # 2. Duplicate attribute combination check
        if self.attributes:
            qs = ProductVariant.objects.filter(
                product=self.product,
                attributes=self.attributes,
            ).exclude(pk=self.pk)
            if qs.exists():
                raise ValidationError(
                    "A variant with the same attribute combination already exists "
                    "for this product."
                )

    def save(self, *args, **kwargs):
        self.full_clean()
        # Ensure only one default variant per product
        if self.is_default:
            ProductVariant.objects.filter(
                product=self.product, is_default=True
            ).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def effective_price(self):
        return self.sale_price if self.sale_price is not None else self.price

    @property
    def in_stock(self):
        return self.stock_quantity > 0

    def soft_delete(self):
        self.is_active = False
        self.save(update_fields=["is_active", "updated_at"])


# ---------------------------------------------------------------------------
# ProductImage
# ---------------------------------------------------------------------------

class ProductImage(TimeStampedModel):
    """
    An image that belongs to either a Product or a specific ProductVariant
    (at least one FK must be set).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    product = models.ForeignKey(
        Product,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
    )
    variant = models.ForeignKey(
        ProductVariant,
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="images",
    )
    image = models.ImageField(upload_to="products/")
    alt_text = models.CharField(max_length=255, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = "Product Image"
        verbose_name_plural = "Product Images"
        ordering = ["sort_order", "created_at"]

    def __str__(self):
        owner = self.product or self.variant
        return f"Image for {owner}"

    def clean(self):
        if not self.product and not self.variant:
            raise ValidationError(
                "A ProductImage must be linked to either a Product or a Variant."
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)
