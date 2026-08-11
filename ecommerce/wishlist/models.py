"""
wishlist/models.py

Wishlist is authenticated-user-only (the brief's wishlist section never
mentions guests, unlike cart) — one Wishlist per User.
"""

import uuid

from django.db import models

from catalog.models import Product
from users.models import User


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class Wishlist(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="wishlist")

    class Meta:
        verbose_name = "Wishlist"
        verbose_name_plural = "Wishlists"

    def __str__(self):
        return f"Wishlist({self.user.email})"


class WishlistItem(TimeStampedModel):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wishlist_items")

    class Meta:
        verbose_name = "Wishlist Item"
        verbose_name_plural = "Wishlist Items"
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(fields=["wishlist", "product"], name="unique_wishlist_product"),
        ]
        indexes = [
            models.Index(fields=["wishlist"]),
        ]

    def __str__(self):
        return f"{self.product.name} in {self.wishlist}"
