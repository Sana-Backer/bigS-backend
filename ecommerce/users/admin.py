"""
users/admin.py

Django admin configuration for the users app.

Custom admin classes:
  UserAdmin        – manages User + inlines for Profile and Addresses
  UserProfileAdmin – standalone profile management
  AddressAdmin     – address list/detail
  GuestSessionAdmin
  PasswordResetTokenAdmin
"""

from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.utils.html import format_html
from django.utils import timezone

from .models import User, UserProfile, Address, GuestSession, GuestAddress, PasswordResetToken


# ---------------------------------------------------------------------------
# Inlines
# ---------------------------------------------------------------------------

class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = "Profile"
    fields = [
        "avatar", "bio", "gender", "date_of_birth",
        "newsletter_subscribed", "sms_notifications",
        "total_orders", "total_spent",
        "is_email_verified", "email_verified_at",
    ]
    readonly_fields = ["total_orders", "total_spent", "email_verified_at"]


class AddressInline(admin.TabularInline):
    model = Address
    extra = 0
    fields = ["label", "address_type", "full_name", "city", "state", "country", "is_default"]
    readonly_fields = ["created_at"]


# ---------------------------------------------------------------------------
# User Admin
# ---------------------------------------------------------------------------

@admin.register(User)
class UserAdmin(BaseUserAdmin):
    """
    Full admin for the custom User model.
    Groups actions: view, activate/deactivate, promote to staff.
    """

    # List view
    list_display  = [
        "email", "full_name_display", "role", "role_badge",
        "is_active", "is_staff", "date_joined",
    ]
    list_filter   = ["role", "is_active", "is_staff", "date_joined"]
    search_fields = ["email", "first_name", "last_name", "phone"]
    ordering      = ["-date_joined"]
    list_per_page = 50

    # Detail view
    fieldsets = (
        ("Account", {
            "fields": ("email", "password")
        }),
        ("Personal Info", {
            "fields": ("first_name", "last_name", "phone")
        }),
        ("Roles & Permissions", {
            "fields": ("role", "is_active", "is_staff", "is_superuser", "groups", "user_permissions")
        }),
        ("Audit", {
            "fields": ("date_joined", "last_login", "last_login_ip"),
            "classes": ("collapse",),
        }),
    )

    # Create user form
    add_fieldsets = (
        ("Create User", {
            "classes": ("wide",),
            "fields": ("email", "first_name", "last_name", "role", "password1", "password2"),
        }),
    )

    readonly_fields = ["date_joined", "last_login", "last_login_ip"]
    inlines         = [UserProfileInline, AddressInline]

    # Username field is email
    ordering        = ["-date_joined"]

    # Override because we use email not username
    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "username" in form.base_fields:
            form.base_fields.pop("username", None)
        return form

    # Custom display methods
    @admin.display(description="Name")
    def full_name_display(self, obj):
        return obj.full_name or "—"

    @admin.display(description="Role")
    def role_badge(self, obj):
        colors = {
            "customer": "#3b82f6",
            "staff":    "#f59e0b",
            "manager":  "#8b5cf6",
            "admin":    "#ef4444",
        }
        color = colors.get(obj.role, "#6b7280")
        return format_html(
            '<span style="background:{}22; color:{}; border:1px solid {}; '
            'padding:2px 8px; border-radius:4px; font-size:11px; font-weight:600">{}</span>',
            color, color, color, obj.get_role_display()
        )

    # Bulk actions
    @admin.action(description="Activate selected users")
    def activate_users(self, request, queryset):
        queryset.update(is_active=True)
        self.message_user(request, f"{queryset.count()} user(s) activated.")

    @admin.action(description="Deactivate selected users")
    def deactivate_users(self, request, queryset):
        queryset.exclude(pk=request.user.pk).update(is_active=False)
        self.message_user(request, "Selected users deactivated (your own account was skipped).")

    @admin.action(description="Promote selected to Staff role")
    def promote_to_staff(self, request, queryset):
        queryset.filter(role=User.Role.CUSTOMER).update(role=User.Role.STAFF, is_staff=True)
        self.message_user(request, "Selected customers promoted to Staff.")

    actions = [activate_users, deactivate_users, promote_to_staff]


# ---------------------------------------------------------------------------
# UserProfile Admin
# ---------------------------------------------------------------------------

@admin.register(UserProfile)
class UserProfileAdmin(admin.ModelAdmin):
    list_display  = ["user", "gender", "is_email_verified", "newsletter_subscribed", "total_orders", "total_spent"]
    list_filter   = ["gender", "is_email_verified", "newsletter_subscribed"]
    search_fields = ["user__email", "user__first_name", "user__last_name"]
    readonly_fields = ["total_orders", "total_spent", "email_verified_at"]


# ---------------------------------------------------------------------------
# Address Admin
# ---------------------------------------------------------------------------

@admin.register(Address)
class AddressAdmin(admin.ModelAdmin):
    list_display  = ["full_name", "user", "city", "state", "country", "address_type", "is_default"]
    list_filter   = ["address_type", "is_default", "country"]
    search_fields = ["user__email", "full_name", "city", "state", "postal_code"]
    raw_id_fields = ["user"]


# ---------------------------------------------------------------------------
# GuestSession Admin
# ---------------------------------------------------------------------------

class GuestAddressInline(admin.TabularInline):
    model = GuestAddress
    extra = 0
    fields = ["full_name", "city", "state", "country", "address_type"]
    readonly_fields = fields


@admin.register(GuestSession)
class GuestSessionAdmin(admin.ModelAdmin):
    list_display  = [
        "email", "first_name", "is_converted",
        "is_expired_display", "ip_address", "created_at",
    ]
    list_filter   = ["is_converted"]
    search_fields = ["email", "first_name", "last_name", "session_key"]
    readonly_fields = [
        "session_key", "ip_address", "user_agent",
        "is_converted", "converted_user", "expires_at", "created_at",
    ]
    inlines = [GuestAddressInline]

    @admin.display(description="Expired?", boolean=True)
    def is_expired_display(self, obj):
        return obj.is_expired


# ---------------------------------------------------------------------------
# PasswordResetToken Admin
# ---------------------------------------------------------------------------

@admin.register(PasswordResetToken)
class PasswordResetTokenAdmin(admin.ModelAdmin):
    list_display  = ["user", "is_used", "is_valid_display", "expires_at", "created_at"]
    list_filter   = ["is_used"]
    search_fields = ["user__email"]
    readonly_fields = ["token", "user", "expires_at", "is_used", "used_at", "created_at"]

    @admin.display(description="Valid?", boolean=True)
    def is_valid_display(self, obj):
        return obj.is_valid
