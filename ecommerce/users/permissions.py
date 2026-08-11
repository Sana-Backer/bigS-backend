"""
users/permissions.py

Multi-level permission system for the eCommerce platform.

Permission Hierarchy (lowest → highest):
  CUSTOMER  → can view their own data, place orders
  STAFF     → CUSTOMER + manage catalog (products/categories/images)
  MANAGER   → STAFF + manage regular users, view all orders
  ADMIN     → MANAGER + manage staff/managers, full system access

DRF Permission Classes
----------------------
  IsAdminRole            – only ADMIN role users
  IsManagerOrAdmin       – MANAGER or ADMIN
  IsStaffOrAbove         – STAFF, MANAGER, or ADMIN
  IsOwnerOrStaffOrAbove  – object owner OR staff+
  IsOwnerOrAdmin         – object owner OR admin only
  IsAdminOrReadOnly      – ADMIN for writes, anyone for reads
  IsStaffOrAboveOrReadOnly – staff+ for writes, anyone for reads

Function-based View Decorators (use on @api_view functions)
-------------------------------------------------------------
  admin_required
  manager_or_admin_required
  staff_required
  owner_or_staff_required(user_field)

Class-based View Mixins
-----------------------
  AdminRequiredMixin
  ManagerOrAdminMixin
  StaffOrAboveMixin

Usage examples
--------------
# DRF class-based view:
class MyView(APIView):
    permission_classes = [IsStaffOrAbove]

# Function-based view:
@api_view(["GET"])
@staff_required
def my_view(request): ...

# Multiple permissions (AND):
permission_classes = [IsAuthenticated, IsStaffOrAbove]
"""

from functools import wraps

from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission, IsAuthenticated, SAFE_METHODS
from rest_framework.response import Response
from rest_framework import status


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_user_role(user):
    """Return the user's role string, or None for anonymous."""
    if not user or not user.is_authenticated:
        return None
    return getattr(user, "role", None)


def _is_at_least_staff(user):
    from users.models import User
    return user.is_authenticated and user.role in (
        User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN
    )


def _is_at_least_manager(user):
    from users.models import User
    return user.is_authenticated and user.role in (
        User.Role.MANAGER, User.Role.ADMIN
    )


def _is_admin(user):
    from users.models import User
    return user.is_authenticated and user.role == User.Role.ADMIN


# ---------------------------------------------------------------------------
# DRF Permission Classes
# ---------------------------------------------------------------------------

class IsAdminRole(BasePermission):
    """
    Grants access only to users with role=ADMIN.
    Use for superuser-level operations (e.g. delete users, change roles).
    """
    message = "You must be an Admin to perform this action."

    def has_permission(self, request, view):
        return bool(request.user and _is_admin(request.user))


class IsManagerOrAdmin(BasePermission):
    """
    Grants access to MANAGER and ADMIN.
    Use for: user management, viewing all orders, financial reports.
    """
    message = "You must be a Manager or Admin to perform this action."

    def has_permission(self, request, view):
        return bool(request.user and _is_at_least_manager(request.user))


class IsStaffOrAbove(BasePermission):
    """
    Grants access to STAFF, MANAGER, and ADMIN.
    Use for: catalog management, product CRUD.
    """
    message = "You must be a Staff member or above to perform this action."

    def has_permission(self, request, view):
        return bool(request.user and _is_at_least_staff(request.user))


class IsStaffOrAboveOrReadOnly(BasePermission):
    """
    Read-only for everyone; write access requires STAFF or above.
    Use for: product catalog endpoints.
    """
    message = "Write access requires Staff or above role."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and _is_at_least_staff(request.user))


class IsAdminOrReadOnly(BasePermission):
    """
    Read-only for everyone; write access requires ADMIN.
    Use for: category management, site-wide settings.
    """
    message = "Write access requires Admin role."

    def has_permission(self, request, view):
        if request.method in SAFE_METHODS:
            return True
        return bool(request.user and _is_admin(request.user))


class IsOwnerOrStaffOrAbove(BasePermission):
    """
    Object-level: allows the object's owner OR any staff+ user.
    Use for: user profile, order detail, address.

    The view must implement `get_object()` and the object must have
    a `user` attribute, or override `has_object_permission`.
    """
    message = "You do not have permission to access this resource."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if _is_at_least_staff(request.user):
            return True
        # Support objects with .user FK or objects that ARE the user
        owner = getattr(obj, "user", obj)
        return owner == request.user


class IsOwnerOrAdmin(BasePermission):
    """
    Object-level: allows only the object's owner or an ADMIN.
    Use for: deleting accounts, changing sensitive data.
    """
    message = "Only the account owner or an Admin can perform this action."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        if _is_admin(request.user):
            return True
        owner = getattr(obj, "user", obj)
        return owner == request.user


class IsSelfOrManagerOrAdmin(BasePermission):
    """
    Allows a user to read/edit their own record.
    Managers/Admins can access any user record.
    Staff can read any record but not write.
    """
    message = "You do not have permission to modify this user."

    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated)

    def has_object_permission(self, request, view, obj):
        # Admin/Manager: full access
        if _is_at_least_manager(request.user):
            return True
        # Staff: read-only access to other users
        if _is_at_least_staff(request.user) and request.method in SAFE_METHODS:
            return True
        # Self: full access to own record
        target = obj if hasattr(obj, "email") else getattr(obj, "user", None)
        return target == request.user


class IsAuthenticatedOrGuest(BasePermission):
    """
    Allows authenticated users OR requests with a valid guest session token
    in the X-Guest-Token header.
    Use for: checkout, cart operations.
    """
    message = "Authentication or a valid guest session token is required."

    def has_permission(self, request, view):
        if request.user and request.user.is_authenticated:
            return True
        guest_token = request.headers.get("X-Guest-Token")
        if guest_token:
            from users.models import GuestSession
            from django.utils import timezone
            return GuestSession.objects.filter(
                session_key=guest_token,
                expires_at__gt=timezone.now(),
            ).exists()
        return False


# ---------------------------------------------------------------------------
# Class-based View Mixins
# ---------------------------------------------------------------------------

class AdminRequiredMixin:
    """Mixin for CBVs requiring ADMIN role."""
    permission_classes = [IsAuthenticated, IsAdminRole]


class ManagerOrAdminMixin:
    """Mixin for CBVs requiring MANAGER or ADMIN role."""
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]


class StaffOrAboveMixin:
    """Mixin for CBVs requiring STAFF, MANAGER, or ADMIN role."""
    permission_classes = [IsAuthenticated, IsStaffOrAbove]


# ---------------------------------------------------------------------------
# Function-based View Decorators
# ---------------------------------------------------------------------------

def admin_required(func):
    """
    Decorator for @api_view functions: requires ADMIN role.

    Usage:
        @api_view(["GET"])
        @admin_required
        def my_view(request): ...
    """
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"status": "error", "message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not _is_admin(request.user):
            return Response(
                {"status": "error", "message": "Admin role required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return func(request, *args, **kwargs)
    return wrapper


def manager_or_admin_required(func):
    """
    Decorator for @api_view functions: requires MANAGER or ADMIN role.
    """
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"status": "error", "message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not _is_at_least_manager(request.user):
            return Response(
                {"status": "error", "message": "Manager or Admin role required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return func(request, *args, **kwargs)
    return wrapper


def staff_required(func):
    """
    Decorator for @api_view functions: requires STAFF, MANAGER, or ADMIN.
    """
    @wraps(func)
    def wrapper(request, *args, **kwargs):
        if not request.user or not request.user.is_authenticated:
            return Response(
                {"status": "error", "message": "Authentication required."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        if not _is_at_least_staff(request.user):
            return Response(
                {"status": "error", "message": "Staff or above role required."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return func(request, *args, **kwargs)
    return wrapper


def owner_or_staff_required(user_field="user"):
    """
    Decorator factory: allows the object owner OR staff+.

    Usage:
        @api_view(["GET"])
        @owner_or_staff_required(user_field="user")
        def my_view(request, pk): ...

    The decorated view must retrieve the object and set request.target_user,
    OR pass the user as a keyword argument named by `user_field`.
    """
    def decorator(func):
        @wraps(func)
        def wrapper(request, *args, **kwargs):
            if not request.user or not request.user.is_authenticated:
                return Response(
                    {"status": "error", "message": "Authentication required."},
                    status=status.HTTP_401_UNAUTHORIZED,
                )
            if _is_at_least_staff(request.user):
                return func(request, *args, **kwargs)
            # Check ownership via request.target_user (set by caller)
            target = getattr(request, "target_user", None)
            if target and target == request.user:
                return func(request, *args, **kwargs)
            return Response(
                {"status": "error", "message": "Permission denied."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# Permission summary for documentation / README
# ---------------------------------------------------------------------------

PERMISSION_MATRIX = """
Role / Action           CUSTOMER   STAFF   MANAGER   ADMIN
─────────────────────────────────────────────────────────────
View products/catalog    ✓         ✓       ✓         ✓
Manage catalog           ✗         ✓       ✓         ✓
View own profile/orders  ✓         ✓       ✓         ✓
View all users           ✗         ✓(read) ✓         ✓
Create staff users       ✗         ✗       ✓         ✓
Change user roles        ✗         ✗       ✗         ✓
Delete users             ✗         ✗       ✗         ✓
System settings          ✗         ✗       ✗         ✓
Guest checkout           (no login needed)
"""
