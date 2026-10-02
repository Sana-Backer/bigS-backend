"""
dashboard/models.py

Banner — the only model this app owns. Everything else in `dashboard`
(overview/sales-analytics/reports) is pure read-only aggregation over
orders/catalog/users/payments and has no models of its own, hence no
migrations/ folder existed here before this file.

A Banner is a single image-based promo slot shown on the storefront's
home screen (hero carousel, secondary promo strip, etc. — see
`BannerPlacement`). Admins manage these through the CRUD surface in
views.py; the storefront reads them back through a separate, public,
read-only endpoint (see PublicActiveBannersView) that only ever
returns banners that are both `is_active` and currently inside their
optional scheduling window.
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


class Banner(TimeStampedModel):
    """
    One homepage banner slot.

    `sort_order` controls display order within a given `placement`
    (ascending — lower numbers show first). `start_at`/`end_at` are
    optional: leave both blank for a banner that runs indefinitely once
    activated, or set either/both to schedule it.
    """

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    title = models.CharField(
        max_length=200, blank=True,
        help_text="Internal label shown in the admin list — not necessarily displayed on the site.",
    )
    subtitle = models.CharField(max_length=300, blank=True)

    image = models.ImageField(
        upload_to="banners/",
        help_text="Primary banner image (desktop/default).",
    )
    mobile_image = models.ImageField(
        upload_to="banners/mobile/", blank=True, null=True,
        help_text="Optional alternate image for small screens. Falls back to `image` if not set.",
    )

    link_url = models.URLField(
        max_length=500, blank=True,
        help_text="Where the banner navigates to when clicked. Leave blank for a non-clickable banner.",
    )
    cta_text = models.CharField(
        max_length=100, blank=True,
        help_text="Call-to-action label, e.g. 'Shop Now'. Only meaningful if link_url is set.",
    )

    placement = models.CharField(
        max_length=20, choices=BannerPlacement.choices, default=BannerPlacement.HOME_HERO, db_index=True,
    )
    sort_order = models.PositiveSmallIntegerField(default=0)

    is_active = models.BooleanField(default=True, db_index=True)
    start_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Optional. Banner is hidden before this time if set.",
    )
    end_at = models.DateTimeField(
        null=True, blank=True,
        help_text="Optional. Banner is hidden after this time if set.",
    )

    class Meta:
        verbose_name = "Banner"
        verbose_name_plural = "Banners"
        ordering = ["placement", "sort_order", "-created_at"]
        indexes = [
            models.Index(fields=["placement", "is_active"]),
            models.Index(fields=["sort_order"]),
        ]

    def __str__(self):
        return self.title or f"Banner ({self.get_placement_display()})"

    def clean(self):
        if self.start_at and self.end_at and self.start_at >= self.end_at:
            raise ValidationError({"end_at": "end_at must be after start_at."})

    def save(self, *args, **kwargs):
        self.full_clean()
        super().save(*args, **kwargs)

    @property
    def is_currently_active(self) -> bool:
        """
        is_active AND (no start_at or already started) AND (no end_at or
        not yet ended). This is the single source of truth for "should
        the storefront show this banner right now" — both
        PublicActiveBannersView and admin tooling should read this
        property rather than re-deriving the same three checks elsewhere.
        """
        if not self.is_active:
            return False
        now = timezone.now()
        if self.start_at and self.start_at > now:
            return False
        if self.end_at and self.end_at < now:
            return False
        return True