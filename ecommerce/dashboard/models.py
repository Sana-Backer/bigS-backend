"""
dashboard/models.py   (full replacement)

Changes vs. your version:
  + BannerPlacement.SHOP_CATEGORY      -> banner shown on the products/shop page
  + Banner.is_mobile  (bool)           -> False = laptop/desktop banner, True = phone banner
  + Banner.category   (FK, nullable)   -> which category's shop page the banner belongs to
                                          (blank = the default "all products" shop banner)
  + clean(): category only allowed with the SHOP_CATEGORY placement
"""

import uuid

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class BannerPlacement(models.TextChoices):
    HOME_HERO = "home_hero", "Home — Hero"
    HOME_PROMO = "home_promo", "Home — Secondary Promo"
    SHOP_CATEGORY = "shop_category", "Shop page — Category Banner"


class Banner(TimeStampedModel):
    """
    One banner slot.

    Device targeting : `is_mobile` False = laptop/desktop banner, True = phone banner.
    Category banners : placement=SHOP_CATEGORY + `category` set -> shown on that
                       category's products page. placement=SHOP_CATEGORY with NO
                       category -> the default banner for /products (also used as
                       the fallback for categories that have no banner of their own).
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(
        max_length=200, blank=True,
        help_text="Internal label shown in the admin list — not necessarily displayed on the site.",
    )
    subtitle = models.CharField(max_length=300, blank=True)

    image = models.ImageField(
        upload_to="banners/",
        help_text="Banner image. Upload a phone-sized image when 'is_mobile' is ticked, a wide one otherwise.",
    )
    mobile_image = models.ImageField(
        upload_to="banners/mobile/", blank=True, null=True,
        help_text="(Legacy) optional alternate image for small screens. Prefer separate banners with is_mobile=True.",
    )

    link_url = models.URLField(max_length=500, blank=True,
        help_text="Where the banner navigates to when clicked. Leave blank for a non-clickable banner.")
    cta_text = models.CharField(max_length=100, blank=True,
        help_text="Call-to-action label, e.g. 'Shop Now'. Only meaningful if link_url is set.")

    placement = models.CharField(
        max_length=20, choices=BannerPlacement.choices,
        default=BannerPlacement.HOME_HERO, db_index=True,
    )
    is_mobile = models.BooleanField(
        default=False, db_index=True,
        help_text="Tick for a phone-screen banner. Leave unticked for a laptop/desktop banner.",
    )
    category = models.ForeignKey(
        "catalog.Category", null=True, blank=True,
        on_delete=models.CASCADE, related_name="banners",
        help_text="Only for 'Shop page — Category Banner'. Leave blank for the default shop-page banner.",
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    is_active = models.BooleanField(default=True, db_index=True)
    start_at = models.DateTimeField(null=True, blank=True,
        help_text="Optional. Banner is hidden before this time if set.")
    end_at = models.DateTimeField(null=True, blank=True,
        help_text="Optional. Banner is hidden after this time if set.")

    class Meta:
        verbose_name = "Banner"
        verbose_name_plural = "Banners"
        ordering = ["placement", "sort_order", "-created_at"]
        indexes = [
            models.Index(fields=["placement", "is_active"]),
            models.Index(fields=["placement", "is_mobile", "is_active"]),
            models.Index(fields=["sort_order"]),
        ]

    def __str__(self):
        device = "Phone" if self.is_mobile else "Desktop"
        label = self.title or self.get_placement_display()
        if self.category_id:
            label += f" · {self.category.name}"
        return f"{label} ({device})"

    def clean(self):
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValidationError({"end_at": "end_at must be after start_at."})
        if self.category_id and self.placement != BannerPlacement.SHOP_CATEGORY:
            raise ValidationError(
                {"category": "A category can only be set for the 'Shop page — Category Banner' placement."}
            )

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_currently_active(self) -> bool:
        if not self.is_active:
            return False
        now = timezone.now()
        if self.start_at and self.start_at > now:
            return False
        if self.end_at and self.end_at < now:
            return False
        return True