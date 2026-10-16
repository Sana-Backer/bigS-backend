"""
dashboard/selectors.py  — REPLACE your existing get_active_banners() with this
(and add the small helpers above it). Everything else in selectors.py stays.

Also: in get_banner_queryset() add .select_related("category") so the admin
list doesn't run one query per row.
"""

from django.db.models import Q
from django.utils import timezone

from .models import Banner, BannerPlacement


def _live(qs):
    """is_active AND inside the optional start_at/end_at window."""
    now = timezone.now()
    return (
        qs.filter(is_active=True)
        .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
        .filter(Q(end_at__isnull=True) | Q(end_at__gte=now))
    )


def _by_device(qs, device):
    """
    device="desktop" -> laptop banners only
    device="mobile"  -> phone banners; if there are none, fall back to the
                        desktop ones so a phone never gets an empty hero
    device=None      -> no device filtering (old behaviour)
    """
    if device not in ("mobile", "desktop"):
        return qs
    wanted = qs.filter(is_mobile=(device == "mobile"))
    if device == "mobile" and not wanted.exists():
        return qs.filter(is_mobile=False)
    return wanted


def get_active_banners(placement=None, device=None, category_slug=None):
    qs = _live(Banner.objects.select_related("category"))
    if placement:
        qs = qs.filter(placement=placement)

    if placement == BannerPlacement.SHOP_CATEGORY:
        # 1) banners for this exact category
        if category_slug:
            specific = _by_device(
                qs.filter(category__slug=category_slug, category__is_active=True), device
            )
            if specific.exists():
                return specific
        # 2) fallback: the default shop-page banner (no category)
        qs = qs.filter(category__isnull=True)

    return _by_device(qs, device)