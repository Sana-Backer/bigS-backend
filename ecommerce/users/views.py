"""
users/views.py

All views for the users app.

Auth
  POST /api/auth/register/            – customer sign-up
  POST /api/auth/login/               – login → JWT tokens
  POST /api/auth/logout/              – blacklist refresh token
  POST /api/auth/token/refresh/       – refresh access token
  POST /api/auth/change-password/     – change own password
  POST /api/auth/forgot-password/     – request reset email
  POST /api/auth/reset-password/      – consume token + set password

Me (own profile)
  GET  /api/auth/me/                  – get own profile
  PUT  /api/auth/me/                  – update own basic info
  GET  /api/auth/me/profile/          – get extended profile
  PUT  /api/auth/me/profile/          – update extended profile

Addresses (own)
  GET    /api/auth/me/addresses/            – list own addresses
  POST   /api/auth/me/addresses/            – add address
  GET    /api/auth/me/addresses/{id}/       – retrieve
  PUT    /api/auth/me/addresses/{id}/       – update
  DELETE /api/auth/me/addresses/{id}/       – delete

Guest
  POST /api/auth/guest/session/       – create guest session
  POST /api/auth/guest/checkout/      – full guest checkout (session + address)

Admin – User Management
  GET    /api/admin/users/                  – list all users [STAFF+]
  POST   /api/admin/users/                  – create user [ADMIN]
  GET    /api/admin/users/{id}/             – user detail [STAFF+]
  PUT    /api/admin/users/{id}/             – update user [MANAGER+]
  DELETE /api/admin/users/{id}/             – deactivate user [ADMIN]
  POST   /api/admin/users/{id}/role/        – change role [ADMIN]
  POST   /api/admin/users/{id}/activate/    – activate/deactivate [MANAGER+]
  POST   /api/admin/staff/                  – create staff user [MANAGER+]
  GET    /api/admin/staff/                  – list staff users [MANAGER+]
  GET    /api/admin/guests/                 – list guest sessions [MANAGER+]
  GET    /api/admin/guests/{id}/            – guest session detail [MANAGER+]
"""

import secrets
import logging

from django.contrib.auth import logout as django_logout
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import User, UserProfile, Address, GuestSession, PasswordResetToken
from .permissions import (
    IsAdminRole, IsManagerOrAdmin, IsStaffOrAbove,
    IsOwnerOrStaffOrAbove, IsSelfOrManagerOrAdmin,
)
from .serializers import (
    RegisterSerializer, LoginSerializer,
    ChangePasswordSerializer, ForgotPasswordSerializer, ResetPasswordSerializer,
    UserMeSerializer, UserMeUpdateSerializer, UserProfileSerializer,
    AddressSerializer, AddressCreateSerializer,
    GuestSessionCreateSerializer, GuestSessionSerializer,
    GuestCheckoutSerializer,
    UserListSerializer, UserDetailSerializer,
    UserCreateSerializer, StaffCreateSerializer,
    UserUpdateSerializer, UserRoleUpdateSerializer, UserDeactivateSerializer,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Response helpers
# ---------------------------------------------------------------------------

def ok(data, message=None, status_code=status.HTTP_200_OK):
    payload = {"status": "success", "data": data}
    if message:
        payload["message"] = message
    return Response(payload, status=status_code)


def created(data, message="Created."):
    return ok(data, message, status.HTTP_201_CREATED)


def no_content(message="Deleted."):
    return Response({"status": "success", "message": message}, status=status.HTTP_204_NO_CONTENT)


def err(message, code=status.HTTP_400_BAD_REQUEST, errors=None):
    payload = {"status": "error", "message": message}
    if errors:
        payload["errors"] = errors
    return Response(payload, status=code)


# ---------------------------------------------------------------------------
# ── AUTH ─────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class RegisterView(APIView):
    """
    POST /api/auth/register/

    Open to all. Creates a CUSTOMER account.

    Request:
      { "email": "alice@example.com", "first_name": "Alice",
        "password": "Str0ng!Pass", "confirm_password": "Str0ng!Pass" }

    Response 201:
      { "status": "success", "message": "Account created.",
        "data": { "access": "...", "refresh": "...", "user": { ... } } }
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = RegisterSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        tokens = _get_tokens(user)
        return created({
            **tokens,
            "user": _basic_user_data(user),
        }, "Account created successfully.")


class LoginView(APIView):
    """
    POST /api/auth/login/

    Request:
      { "email": "alice@example.com", "password": "Str0ng!Pass" }

    Response 200:
      { "access": "...", "refresh": "...", "user": { "id", "email", "role", ... } }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = LoginSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data["user"]
        # Update last login IP
        ip = request.META.get("REMOTE_ADDR")
        User.objects.filter(pk=user.pk).update(last_login_ip=ip)
        tokens = _get_tokens(user)
        return ok({
            **tokens,
            "user": _basic_user_data(user),
        })


class LogoutView(APIView):
    """
    POST /api/auth/logout/

    Blacklists the provided refresh token.
    Requires: { "refresh": "<token>" }
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return err("Refresh token is required.")
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
        except TokenError:
            return err("Invalid or already expired token.")
        return ok({}, "Logged out successfully.")


class ChangePasswordView(APIView):
    """POST /api/auth/change-password/"""
    permission_classes = [IsAuthenticated]

    def post(self, request):
        serializer = ChangePasswordSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok({}, "Password changed. Please log in again.")


class ForgotPasswordView(APIView):
    """
    POST /api/auth/forgot-password/

    Generates a password reset token. In production, send via email.
    For development, the token is returned in the response.

    Request: { "email": "alice@example.com" }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ForgotPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            # Silent success — prevent user enumeration
            return ok({}, "If that email is registered, a reset link has been sent.")

        # Invalidate old tokens
        PasswordResetToken.objects.filter(user=user, is_used=False).update(is_used=True)

        token_str  = secrets.token_urlsafe(32)
        expires_at = timezone.now() + timezone.timedelta(hours=2)
        reset_token = PasswordResetToken.objects.create(
            user=user,
            token=token_str,
            expires_at=expires_at,
        )

        # TODO: send email in production
        # send_password_reset_email(user, token_str)
        logger.info("Password reset token created for %s", email)

        # In production: never return the token; return only the success message
        return ok(
            {"token": token_str, "expires_at": expires_at},  # Remove in production
            "Password reset token generated.",
        )


class ResetPasswordView(APIView):
    """
    POST /api/auth/reset-password/

    Request: { "token": "...", "new_password": "...", "confirm_password": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = ResetPasswordSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok({}, "Password reset successfully. Please log in.")


# ---------------------------------------------------------------------------
# ── ME (own profile) ─────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class MeView(APIView):
    """
    GET  /api/auth/me/  – get own user info
    PUT  /api/auth/me/  – update own basic info (name, phone)
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        serializer = UserMeSerializer(request.user, context={"request": request})
        return ok(serializer.data)

    def put(self, request):
        serializer = UserMeUpdateSerializer(
            request.user, data=request.data, partial=True, context={"request": request}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok(UserMeSerializer(request.user, context={"request": request}).data)


class MyProfileView(APIView):
    """
    GET /api/auth/me/profile/  – extended profile
    PUT /api/auth/me/profile/  – update extended profile
    """
    permission_classes = [IsAuthenticated]

    def _get_profile(self, user):
        profile, _ = UserProfile.objects.get_or_create(user=user)
        return profile

    def get(self, request):
        profile = self._get_profile(request.user)
        return ok(UserProfileSerializer(profile).data)

    def put(self, request):
        profile = self._get_profile(request.user)
        serializer = UserProfileSerializer(profile, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok(serializer.data)


# ---------------------------------------------------------------------------
# ── ADDRESSES (own) ──────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class MyAddressListCreateView(APIView):
    """
    GET  /api/auth/me/addresses/  – list own addresses
    POST /api/auth/me/addresses/  – add a new address
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Address.objects.filter(user=request.user)
        return ok(AddressSerializer(qs, many=True).data)

    @transaction.atomic
    def post(self, request):
        serializer = AddressCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        address = serializer.save(user=request.user)
        return created(AddressSerializer(address).data, "Address added.")


class MyAddressDetailView(APIView):
    """
    GET    /api/auth/me/addresses/{id}/
    PUT    /api/auth/me/addresses/{id}/
    DELETE /api/auth/me/addresses/{id}/
    """
    permission_classes = [IsAuthenticated]

    def _get_address(self, request, id):
        return get_object_or_404(Address, id=id, user=request.user)

    def get(self, request, id):
        return ok(AddressSerializer(self._get_address(request, id)).data)

    def put(self, request, id):
        address = self._get_address(request, id)
        serializer = AddressCreateSerializer(address, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok(AddressSerializer(address).data)

    def delete(self, request, id):
        self._get_address(request, id).delete()
        return no_content("Address deleted.")


# ---------------------------------------------------------------------------
# ── GUEST ────────────────────────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class GuestSessionView(APIView):
    """
    POST /api/auth/guest/session/

    Creates a guest session. Returns session_key for use as X-Guest-Token.

    Request:
      { "email": "guest@example.com", "first_name": "John", "phone": "+91..." }

    Response 201:
      { "session_key": "...", "email": "...", "expires_at": "..." }
    """
    permission_classes = [AllowAny]

    def post(self, request):
        serializer = GuestSessionCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return created(GuestSessionSerializer(session).data, "Guest session created.")


class GuestCheckoutView(APIView):
    """
    POST /api/auth/guest/checkout/

    Single-step guest checkout: creates session + saves address.

    Request:
      {
        "email": "guest@example.com",
        "first_name": "John",
        "phone": "+91...",
        "address": { "full_name": "John Doe", "line1": "...", "city": "...", ... }
      }

    Response 201:
      { "session_key": "...", "email": "...", ... }

    After this call, use session_key as X-Guest-Token to place the order.
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        serializer = GuestCheckoutSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        session = serializer.save()
        return created(GuestSessionSerializer(session).data, "Guest checkout session created.")


class GuestConvertView(APIView):
    """
    POST /api/auth/guest/convert/

    Converts a guest session into a registered account.

    Request (header): X-Guest-Token: <session_key>
    Request body: { "password": "...", "confirm_password": "..." }
    """
    permission_classes = [AllowAny]

    @transaction.atomic
    def post(self, request):
        from django.contrib.auth.password_validation import validate_password
        guest_token = request.headers.get("X-Guest-Token")
        if not guest_token:
            return err("X-Guest-Token header is required.", status.HTTP_400_BAD_REQUEST)

        try:
            session = GuestSession.objects.get(
                session_key=guest_token,
                expires_at__gt=timezone.now(),
                is_converted=False,
            )
        except GuestSession.DoesNotExist:
            return err("Invalid or expired guest session.", status.HTTP_404_NOT_FOUND)

        password = request.data.get("password")
        confirm  = request.data.get("confirm_password")
        if not password or password != confirm:
            return err("Passwords are required and must match.")

        try:
            validate_password(password)
        except Exception as e:
            return err(str(e))

        if User.objects.filter(email=session.email).exists():
            return err("An account with this email already exists. Please log in.")

        user = User.objects.create_user(
            email=session.email,
            first_name=session.first_name,
            last_name=session.last_name,
            phone=session.phone,
            password=password,
        )
        session.convert_to_user(user)
        tokens = _get_tokens(user)
        return created({**tokens, "user": _basic_user_data(user)}, "Account created from guest session.")


# ---------------------------------------------------------------------------
# ── ADMIN: USER MANAGEMENT ───────────────────────────────────────────────────
# ---------------------------------------------------------------------------

class AdminUserListCreateView(APIView):
    """
    GET  /api/admin/users/  – list all users          [STAFF+ read / MANAGER+ write]
    POST /api/admin/users/  – create any user          [ADMIN only]
    """

    def get_permissions(self):
        if self.request.method == "POST":
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated(), IsStaffOrAbove()]

    def get(self, request):
        role_filter = request.query_params.get("role")
        is_active   = request.query_params.get("is_active")
        search      = request.query_params.get("search", "").strip()

        qs = User.objects.select_related("profile").order_by("-date_joined")

        if role_filter:
            qs = qs.filter(role=role_filter)
        if is_active is not None:
            qs = qs.filter(is_active=is_active.lower() == "true")
        if search:
            from django.db.models import Q
            qs = qs.filter(
                Q(email__icontains=search)
                | Q(first_name__icontains=search)
                | Q(last_name__icontains=search)
                | Q(phone__icontains=search)
            )

        # Simple pagination
        from catalog.pagination import StandardResultsPagination
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = UserListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    @transaction.atomic
    def post(self, request):
        serializer = UserCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return created(UserDetailSerializer(user).data, "User created.")


class AdminUserDetailView(APIView):
    """
    GET    /api/admin/users/{id}/  – detail        [STAFF+]
    PUT    /api/admin/users/{id}/  – update        [MANAGER+]
    DELETE /api/admin/users/{id}/  – deactivate    [ADMIN]
    """

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), IsStaffOrAbove()]
        if self.request.method == "DELETE":
            return [IsAuthenticated(), IsAdminRole()]
        return [IsAuthenticated(), IsManagerOrAdmin()]

    def _get_user(self, id):
        return get_object_or_404(User, id=id)

    def get(self, request, id):
        return ok(UserDetailSerializer(self._get_user(id), context={"request": request}).data)

    @transaction.atomic
    def put(self, request, id):
        user = self._get_user(id)
        serializer = UserUpdateSerializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return ok(UserDetailSerializer(user, context={"request": request}).data)

    def delete(self, request, id):
        user = self._get_user(id)
        if user == request.user:
            return err("You cannot deactivate your own account.", status.HTTP_400_BAD_REQUEST)
        user.is_active = False
        user.save(update_fields=["is_active"])
        return no_content("User deactivated.")


class AdminUserRoleView(APIView):
    """
    POST /api/admin/users/{id}/role/
    Body: { "role": "staff" }
    [ADMIN only]
    """
    permission_classes = [IsAuthenticated, IsAdminRole]

    def post(self, request, id):
        target = get_object_or_404(User, id=id)
        if target == request.user:
            return err("You cannot change your own role.")
        serializer = UserRoleUpdateSerializer(
            data=request.data, context={"request": request, "target_user": target}
        )
        serializer.is_valid(raise_exception=True)
        serializer.save(target_user=target)
        return ok(UserDetailSerializer(target).data, f"Role changed to {target.role}.")


class AdminUserActivateView(APIView):
    """
    POST /api/admin/users/{id}/activate/
    Body: { "is_active": true/false, "reason": "..." }
    [MANAGER+]
    """
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def post(self, request, id):
        target = get_object_or_404(User, id=id)
        if target == request.user:
            return err("You cannot deactivate your own account.")
        serializer = UserDeactivateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        target.is_active = serializer.validated_data["is_active"]
        target.save(update_fields=["is_active"])
        action = "activated" if target.is_active else "deactivated"
        logger.info("User %s %s by %s. Reason: %s", target.email, action,
                    request.user.email, serializer.validated_data.get("reason", "—"))
        return ok({"is_active": target.is_active}, f"User {action}.")


class AdminStaffListCreateView(APIView):
    """
    GET  /api/admin/staff/  – list staff users     [MANAGER+]
    POST /api/admin/staff/  – create staff user    [MANAGER+]
    """
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        from users.models import User as UserModel
        qs = User.objects.filter(
            role__in=[UserModel.Role.STAFF, UserModel.Role.MANAGER]
        ).order_by("role", "email")
        return ok(UserListSerializer(qs, many=True).data)

    @transaction.atomic
    def post(self, request):
        serializer = StaffCreateSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        user = serializer.save()
        return created(UserDetailSerializer(user).data, "Staff user created.")


class AdminGuestListView(APIView):
    """
    GET /api/admin/guests/  – list guest sessions  [MANAGER+]
    """
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request):
        qs = GuestSession.objects.order_by("-created_at")
        is_converted = request.query_params.get("is_converted")
        if is_converted is not None:
            qs = qs.filter(is_converted=is_converted.lower() == "true")
        from catalog.pagination import StandardResultsPagination
        paginator = StandardResultsPagination()
        page = paginator.paginate_queryset(qs, request)
        from .serializers import GuestSessionSerializer as GS
        return paginator.get_paginated_response(GS(page, many=True).data)


class AdminGuestDetailView(APIView):
    """
    GET /api/admin/guests/{id}/  [MANAGER+]
    """
    permission_classes = [IsAuthenticated, IsManagerOrAdmin]

    def get(self, request, id):
        session = get_object_or_404(GuestSession, id=id)
        from .serializers import GuestSessionSerializer as GS
        return ok(GS(session).data)


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------

def _get_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {"refresh": str(refresh), "access": str(refresh.access_token)}


def _basic_user_data(user):
    return {
        "id":        str(user.id),
        "email":     user.email,
        "full_name": user.full_name,
        "role":      user.role,
        "is_active": user.is_active,
    }
