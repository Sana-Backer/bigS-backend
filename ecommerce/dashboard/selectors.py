"""
dashboard/selectors.py
"""

from django.db.models import Q
from django.utils import timezone

from .exceptions import BannerNotFound
from .models import Banner


def get_banner_queryset():
    return Banner.objects.all()


def get_banner_for_admin(banner_id):
    try:
        return get_banner_queryset().get(id=banner_id)
    except Banner.DoesNotExist:
        raise BannerNotFound()


def get_active_banners(placement=None):
    """
    Banners the storefront should render right now: is_active=True and
    inside their optional start_at/end_at window — the same rule
    Banner.is_currently_active expresses per-instance, applied here as a
    queryset filter so the public endpoint doesn't even load inactive or
    expired rows.
    """
    now = timezone.now()
    qs = Banner.objects.filter(
        is_active=True,
    ).filter(
        Q(start_at__isnull=True) | Q(start_at__lte=now),
    ).filter(
        Q(end_at__isnull=True) | Q(end_at__gte=now),
    )
    if placement:
        qs = qs.filter(placement=placement)
    return qs