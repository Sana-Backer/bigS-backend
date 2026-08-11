"""
users/models.py

Custom user system for the eCommerce platform.

Models
------
User            – Custom AbstractBaseUser replacing Django's default
UserProfile     – Extended profile data (1-to-1 with User)
Address         – Multiple shipping/billing addresses per user
GuestSession    – Tracks guest checkouts (no account required)
GuestAddress    – Address captured at guest checkout
PasswordResetToken – Secure token for password reset flow
"""

import uuid
from django.contrib.auth.models import (
    AbstractBaseUser, BaseUserManager, PermissionsMixin,
)
from django.db import models
from django.utils import timezone
from django.core.validators import RegexValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PHONE_REGEX = RegexValidator(
    regex=r"^\+?1?\d{9,15}$",
    message="Phone number must be in format: '+999999999'. Up to 15 digits.",
)


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ---------------------------------------------------------------------------
# Custom User Manager
# ---------------------------------------------------------------------------

class UserManager(BaseUserManager):
    """Manager for the custom User model."""

    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("Email address is required.")
        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("role", User.Role.CUSTOMER)
        return self._create_user(email, password, **extra_fields)

    def create_staff(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("role", User.Role.STAFF)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("role", User.Role.ADMIN)
        extra_fields.setdefault("is_active", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


# ---------------------------------------------------------------------------
# User
# ---------------------------------------------------------------------------

class User(AbstractBaseUser, PermissionsMixin, TimeStampedModel):
    """
    Custom user replacing Django's default.

    Uses email as the login identifier instead of username.

    Roles (multi-level):
      CUSTOMER  – regular shoppers
      STAFF     – can manage catalog, orders; cannot manage users
      MANAGER   – can manage catalog, orders, and regular users
      ADMIN     – full access (superuser equivalent via roles)
    """

    class Role(models.TextChoices):
        CUSTOMER = "customer", "Customer"
        STAFF    = "staff",    "Staff"
        MANAGER  = "manager",  "Manager"
        ADMIN    = "admin",    "Admin"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    # -- Identification
    email      = models.EmailField(unique=True, db_index=True)
    first_name = models.CharField(max_length=150, blank=True)
    last_name  = models.CharField(max_length=150, blank=True)
    phone      = models.CharField(max_length=17, validators=[PHONE_REGEX], blank=True)

    # -- Role & Access
    role       = models.CharField(max_length=20, choices=Role.choices, default=Role.CUSTOMER, db_index=True)
    is_active  = models.BooleanField(default=True, db_index=True)
    is_staff   = models.BooleanField(default=False)  # Django admin access

    # -- Timestamps
    last_login_ip  = models.GenericIPAddressField(null=True, blank=True)
    date_joined    = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD  = "email"
    REQUIRED_FIELDS = []  # email + password only for createsuperuser

    class Meta:
        verbose_name = "User"
        verbose_name_plural = "Users"
        ordering = ["-date_joined"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["role", "is_active"]),
        ]

    def __str__(self):
        return self.email

    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}".strip() or self.email

    # ------------------------------------------------------------------
    # Role helpers  (use these in permission checks instead of raw strings)
    # ------------------------------------------------------------------

    @property
    def is_customer(self):
        return self.role == self.Role.CUSTOMER

    @property
    def is_staff_member(self):
        return self.role in (self.Role.STAFF, self.Role.MANAGER, self.Role.ADMIN)

    @property
    def is_manager(self):
        return self.role in (self.Role.MANAGER, self.Role.ADMIN)

    @property
    def is_admin_role(self):
        return self.role == self.Role.ADMIN


# ---------------------------------------------------------------------------
# UserProfile  (1-to-1 extended data)
# ---------------------------------------------------------------------------

class UserProfile(TimeStampedModel):
    """Extended profile — created automatically via post_save signal."""

    class Gender(models.TextChoices):
        MALE        = "M", "Male"
        FEMALE      = "F", "Female"
        OTHER       = "O", "Other"
        PREFER_NOT  = "N", "Prefer not to say"

    user   = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    avatar = models.ImageField(upload_to="avatars/", blank=True, null=True)
    bio    = models.TextField(max_length=500, blank=True)
    gender = models.CharField(max_length=1, choices=Gender.choices, blank=True)
    date_of_birth = models.DateField(null=True, blank=True)

    # Marketing preferences
    newsletter_subscribed = models.BooleanField(default=False)
    sms_notifications     = models.BooleanField(default=False)

    # Internal tracking
    total_orders      = models.PositiveIntegerField(default=0)
    total_spent       = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    is_email_verified = models.BooleanField(default=False)
    email_verified_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "User Profile"

    def __str__(self):
        return f"Profile of {self.user.email}"


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

class Address(TimeStampedModel):
    """
    Shipping / billing address linked to a registered user.
    A user can have multiple addresses; one marked as default.
    """

    class AddressType(models.TextChoices):
        SHIPPING = "shipping", "Shipping"
        BILLING  = "billing",  "Billing"
        BOTH     = "both",     "Shipping & Billing"

    id          = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user        = models.ForeignKey(User, on_delete=models.CASCADE, related_name="addresses")
    label       = models.CharField(max_length=50, blank=True, help_text="e.g. Home, Office")
    address_type = models.CharField(max_length=10, choices=AddressType.choices, default=AddressType.BOTH)

    full_name   = models.CharField(max_length=200)
    phone       = models.CharField(max_length=17, validators=[PHONE_REGEX], blank=True)
    line1       = models.CharField(max_length=255)
    line2       = models.CharField(max_length=255, blank=True)
    city        = models.CharField(max_length=100)
    state       = models.CharField(max_length=100)
    postal_code = models.CharField(max_length=20)
    country     = models.CharField(max_length=100, default="India")
    is_default  = models.BooleanField(default=False)

    class Meta:
        verbose_name = "Address"
        verbose_name_plural = "Addresses"
        ordering = ["-is_default", "-created_at"]

    def __str__(self):
        return f"{self.full_name}, {self.city} ({self.user.email})"

    def save(self, *args, **kwargs):
        # Ensure only one default address per user
        if self.is_default:
            Address.objects.filter(user=self.user, is_default=True).exclude(pk=self.pk).update(is_default=False)
        super().save(*args, **kwargs)


# ---------------------------------------------------------------------------
# GuestSession  (guest checkout — no account required)
# ---------------------------------------------------------------------------

class GuestSession(TimeStampedModel):
    """
    Represents a guest checkout session.

    Basic contact details are captured here. If the guest later
    registers with the same email, orders can be linked retroactively.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    session_key  = models.CharField(max_length=64, unique=True, db_index=True)

    # Contact info (saved from checkout form)
    email        = models.EmailField(db_index=True)
    first_name   = models.CharField(max_length=150)
    last_name    = models.CharField(max_length=150, blank=True)
    phone        = models.CharField(max_length=17, validators=[PHONE_REGEX], blank=True)

    # Linked user (set if guest registers/logs in later)
    converted_user = models.ForeignKey(
        User, null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name="guest_sessions",
    )
    is_converted = models.BooleanField(default=False)
    ip_address   = models.GenericIPAddressField(null=True, blank=True)
    user_agent   = models.TextField(blank=True)
    expires_at   = models.DateTimeField()

    class Meta:
        verbose_name = "Guest Session"
        verbose_name_plural = "Guest Sessions"
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["email"]),
            models.Index(fields=["session_key"]),
        ]

    def __str__(self):
        return f"Guest {self.email} [{self.session_key[:8]}...]"

    @property
    def is_expired(self):
        return timezone.now() > self.expires_at

    def convert_to_user(self, user):
        """Link this guest session to a registered user."""
        self.converted_user = user
        self.is_converted = True
        self.save(update_fields=["converted_user", "is_converted", "updated_at"])


# ---------------------------------------------------------------------------
# GuestAddress  (address captured during guest checkout)
# ---------------------------------------------------------------------------

class GuestAddress(TimeStampedModel):
    """
    Shipping / billing address for a guest checkout — not linked to a User.
    Created alongside or referencing a GuestSession.
    """

    id           = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    guest        = models.ForeignKey(GuestSession, on_delete=models.CASCADE, related_name="addresses")
    address_type = models.CharField(
        max_length=10,
        choices=Address.AddressType.choices,
        default=Address.AddressType.BOTH,
    )
    full_name    = models.CharField(max_length=200)
    phone        = models.CharField(max_length=17, validators=[PHONE_REGEX], blank=True)
    line1        = models.CharField(max_length=255)
    line2        = models.CharField(max_length=255, blank=True)
    city         = models.CharField(max_length=100)
    state        = models.CharField(max_length=100)
    postal_code  = models.CharField(max_length=20)
    country      = models.CharField(max_length=100, default="India")

    class Meta:
        verbose_name = "Guest Address"

    def __str__(self):
        return f"{self.full_name}, {self.city} (guest)"


# ---------------------------------------------------------------------------
# PasswordResetToken
# ---------------------------------------------------------------------------

class PasswordResetToken(TimeStampedModel):
    """Secure single-use token for password reset."""

    id         = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user       = models.ForeignKey(User, on_delete=models.CASCADE, related_name="password_reset_tokens")
    token      = models.CharField(max_length=64, unique=True, db_index=True)
    expires_at = models.DateTimeField()
    is_used    = models.BooleanField(default=False)
    used_at    = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Password Reset Token"
        ordering = ["-created_at"]

    def __str__(self):
        return f"Reset token for {self.user.email}"

    @property
    def is_valid(self):
        return not self.is_used and timezone.now() < self.expires_at

    def consume(self):
        self.is_used = True
        self.used_at = timezone.now()
        self.save(update_fields=["is_used", "used_at", "updated_at"])
