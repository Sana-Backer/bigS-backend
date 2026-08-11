"""
users/serializers.py

All DRF serializers for the users app.

Serializer map
--------------
Auth / Registration
  RegisterSerializer          – new customer sign-up
  LoginSerializer             – email + password → tokens
  TokenRefreshSerializer      – alias (simplejwt handles this)
  ChangePasswordSerializer    – authenticated password change
  ForgotPasswordSerializer    – request reset email
  ResetPasswordSerializer     – consume token + set new password

Profile & Address
  UserProfileSerializer       – read/update own profile
  AddressSerializer           – CRUD for saved addresses
  AddressCreateSerializer     – write-only version

Guest
  GuestSessionSerializer      – initiate / read guest session
  GuestCheckoutSerializer     – full guest checkout payload

User Management (staff/admin)
  UserListSerializer          – lightweight list
  UserDetailSerializer        – full read including profile
  UserCreateSerializer        – admin creates a user
  UserUpdateSerializer        – admin/manager updates user
  StaffCreateSerializer       – admin/manager creates staff
  UserRoleUpdateSerializer    – admin changes role
"""

import secrets
from django.contrib.auth import authenticate
from django.contrib.auth.password_validation import validate_password
from django.utils import timezone
from rest_framework import serializers
from rest_framework_simplejwt.tokens import RefreshToken

from .models import User, UserProfile, Address, GuestSession, GuestAddress, PasswordResetToken


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_tokens(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access":  str(refresh.access_token),
    }


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

class RegisterSerializer(serializers.Serializer):
    """
    New customer registration.

    Example request:
    {
        "email": "alice@example.com",
        "first_name": "Alice",
        "last_name": "Smith",
        "phone": "+919876543210",
        "password": "Str0ng!Pass",
        "confirm_password": "Str0ng!Pass",
        "newsletter_subscribed": false
    }
    """
    email            = serializers.EmailField()
    first_name       = serializers.CharField(max_length=150)
    last_name        = serializers.CharField(max_length=150, required=False, default="")
    phone            = serializers.CharField(max_length=17, required=False, allow_blank=True)
    password         = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)
    newsletter_subscribed = serializers.BooleanField(default=False)

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("An account with this email already exists.")
        return value.lower()

    def validate(self, data):
        if data["password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(data["password"])
        return data

    def create(self, validated_data):
        validated_data.pop("confirm_password")
        newsletter = validated_data.pop("newsletter_subscribed", False)
        user = User.objects.create_user(**validated_data)
        # Profile is created by signal; update newsletter pref
        if hasattr(user, "profile"):
            user.profile.newsletter_subscribed = newsletter
            user.profile.save(update_fields=["newsletter_subscribed"])
        return user


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

class LoginSerializer(serializers.Serializer):
    """
    Example request:
    { "email": "alice@example.com", "password": "Str0ng!Pass" }

    Example response:
    {
        "access": "eyJ...",
        "refresh": "eyJ...",
        "user": { "id": "...", "email": "...", "role": "customer", "full_name": "Alice Smith" }
    }
    """
    email    = serializers.EmailField()
    password = serializers.CharField(write_only=True)

    def validate(self, data):
        user = authenticate(username=data["email"].lower(), password=data["password"])
        if not user:
            raise serializers.ValidationError("Invalid email or password.")
        if not user.is_active:
            raise serializers.ValidationError("This account has been deactivated.")
        data["user"] = user
        return data


# ---------------------------------------------------------------------------
# Change Password
# ---------------------------------------------------------------------------

class ChangePasswordSerializer(serializers.Serializer):
    current_password = serializers.CharField(write_only=True)
    new_password     = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate_current_password(self, value):
        user = self.context["request"].user
        if not user.check_password(value):
            raise serializers.ValidationError("Current password is incorrect.")
        return value

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        validate_password(data["new_password"])
        return data

    def save(self):
        user = self.context["request"].user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        return user


# ---------------------------------------------------------------------------
# Forgot / Reset Password
# ---------------------------------------------------------------------------

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()

    def validate_email(self, value):
        # Silently succeed even if email not found (prevent user enumeration)
        return value.lower()


class ResetPasswordSerializer(serializers.Serializer):
    token            = serializers.CharField()
    new_password     = serializers.CharField(write_only=True, min_length=8)
    confirm_password = serializers.CharField(write_only=True)

    def validate(self, data):
        if data["new_password"] != data["confirm_password"]:
            raise serializers.ValidationError({"confirm_password": "Passwords do not match."})
        try:
            token_obj = PasswordResetToken.objects.select_related("user").get(token=data["token"])
        except PasswordResetToken.DoesNotExist:
            raise serializers.ValidationError({"token": "Invalid or expired reset token."})
        if not token_obj.is_valid:
            raise serializers.ValidationError({"token": "This reset token has expired or already been used."})
        validate_password(data["new_password"])
        data["token_obj"] = token_obj
        return data

    def save(self):
        token_obj = self.validated_data["token_obj"]
        user = token_obj.user
        user.set_password(self.validated_data["new_password"])
        user.save(update_fields=["password"])
        token_obj.consume()
        return user


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------

class UserProfileSerializer(serializers.ModelSerializer):
    """Read + update own profile."""

    class Meta:
        model = UserProfile
        fields = [
            "avatar", "bio", "gender", "date_of_birth",
            "newsletter_subscribed", "sms_notifications",
            "total_orders", "total_spent",
            "is_email_verified", "email_verified_at",
        ]
        read_only_fields = ["total_orders", "total_spent", "is_email_verified", "email_verified_at"]


class UserMeSerializer(serializers.ModelSerializer):
    """
    Full 'me' endpoint — user + profile nested.
    """
    profile    = UserProfileSerializer(read_only=True)
    full_name  = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id", "email", "first_name", "last_name", "phone",
            "role", "is_active", "date_joined", "full_name",
            "profile",
        ]
        read_only_fields = ["id", "email", "role", "is_active", "date_joined"]

    def get_full_name(self, obj):
        return obj.full_name


class UserMeUpdateSerializer(serializers.ModelSerializer):
    """Allows user to update their own basic info."""

    class Meta:
        model = User
        fields = ["first_name", "last_name", "phone"]


# ---------------------------------------------------------------------------
# Address
# ---------------------------------------------------------------------------

class AddressSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Address
        fields = [
            "id", "label", "address_type",
            "full_name", "phone",
            "line1", "line2", "city", "state", "postal_code", "country",
            "is_default",
            "created_at", "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class AddressCreateSerializer(serializers.ModelSerializer):
    class Meta:
        model  = Address
        fields = [
            "label", "address_type",
            "full_name", "phone",
            "line1", "line2", "city", "state", "postal_code", "country",
            "is_default",
        ]


# ---------------------------------------------------------------------------
# Guest
# ---------------------------------------------------------------------------

class GuestSessionCreateSerializer(serializers.Serializer):
    """
    Initiate a guest session.

    Example request:
    {
        "email": "guest@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "phone": "+919876543210"
    }

    Response includes the session_key to use as X-Guest-Token header.
    """
    email      = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name  = serializers.CharField(max_length=150, required=False, default="")
    phone      = serializers.CharField(max_length=17, required=False, allow_blank=True)

    def create(self, validated_data):
        session_key = secrets.token_urlsafe(32)
        expires_at  = timezone.now() + timezone.timedelta(hours=24)
        request     = self.context.get("request")
        ip          = request.META.get("REMOTE_ADDR") if request else None
        ua          = request.META.get("HTTP_USER_AGENT", "") if request else ""
        session = GuestSession.objects.create(
            session_key=session_key,
            expires_at=expires_at,
            ip_address=ip,
            user_agent=ua,
            **validated_data,
        )
        return session


class GuestSessionSerializer(serializers.ModelSerializer):
    class Meta:
        model  = GuestSession
        fields = [
            "id", "session_key", "email", "first_name", "last_name", "phone",
            "is_converted", "expires_at", "created_at",
        ]
        read_only_fields = fields


class GuestAddressSerializer(serializers.ModelSerializer):
    class Meta:
        model  = GuestAddress
        fields = [
            "id", "address_type",
            "full_name", "phone",
            "line1", "line2", "city", "state", "postal_code", "country",
        ]
        read_only_fields = ["id"]


class GuestCheckoutSerializer(serializers.Serializer):
    """
    Full guest checkout payload — validates contact + address in one shot.

    Example request:
    {
        "email": "guest@example.com",
        "first_name": "John",
        "last_name": "Doe",
        "phone": "+919876543210",
        "address": {
            "full_name": "John Doe",
            "line1": "123 Main St",
            "city": "Mumbai",
            "state": "Maharashtra",
            "postal_code": "400001",
            "country": "India"
        }
    }
    """
    email      = serializers.EmailField()
    first_name = serializers.CharField(max_length=150)
    last_name  = serializers.CharField(max_length=150, required=False, default="")
    phone      = serializers.CharField(max_length=17, required=False, allow_blank=True)
    address    = GuestAddressSerializer()

    def create(self, validated_data):
        address_data = validated_data.pop("address")
        session_key  = secrets.token_urlsafe(32)
        expires_at   = timezone.now() + timezone.timedelta(hours=24)
        request      = self.context.get("request")
        ip           = request.META.get("REMOTE_ADDR") if request else None
        ua           = request.META.get("HTTP_USER_AGENT", "") if request else ""

        session = GuestSession.objects.create(
            session_key=session_key,
            expires_at=expires_at,
            ip_address=ip,
            user_agent=ua,
            **validated_data,
        )
        GuestAddress.objects.create(guest=session, **address_data)
        return session


# ---------------------------------------------------------------------------
# User Management  (staff / admin views)
# ---------------------------------------------------------------------------

class UserListSerializer(serializers.ModelSerializer):
    """Lightweight user list for admin/manager views."""
    full_name = serializers.SerializerMethodField()

    class Meta:
        model  = User
        fields = [
            "id", "email", "full_name", "first_name", "last_name",
            "phone", "role", "is_active", "date_joined",
        ]

    def get_full_name(self, obj):
        return obj.full_name


class UserDetailSerializer(serializers.ModelSerializer):
    """Full user detail for admin/manager views including profile."""
    profile   = UserProfileSerializer(read_only=True)
    full_name = serializers.SerializerMethodField()
    addresses = AddressSerializer(many=True, read_only=True)

    class Meta:
        model  = User
        fields = [
            "id", "email", "full_name", "first_name", "last_name",
            "phone", "role", "is_active", "is_staff",
            "date_joined", "last_login_ip",
            "profile", "addresses",
            "created_at", "updated_at",
        ]

    def get_full_name(self, obj):
        return obj.full_name


class UserCreateSerializer(serializers.ModelSerializer):
    """Admin creates any user with specified role."""
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model  = User
        fields = [
            "email", "first_name", "last_name", "phone",
            "role", "is_active", "password",
        ]

    def validate_email(self, value):
        if User.objects.filter(email__iexact=value).exists():
            raise serializers.ValidationError("A user with this email already exists.")
        return value.lower()

    def validate_password(self, value):
        validate_password(value)
        return value

    def create(self, validated_data):
        password = validated_data.pop("password")
        role = validated_data.get("role", User.Role.CUSTOMER)
        is_staff = role in (User.Role.STAFF, User.Role.MANAGER, User.Role.ADMIN)
        user = User(**validated_data, is_staff=is_staff)
        user.set_password(password)
        user.save()
        return user


class StaffCreateSerializer(UserCreateSerializer):
    """Manager/Admin creates a staff user. Role limited to STAFF."""

    def validate_role(self, value):
        # Managers can only create STAFF; Admins can create STAFF or MANAGER
        request_user = self.context["request"].user
        from users.models import User as UserModel
        if request_user.role == UserModel.Role.MANAGER:
            if value not in (UserModel.Role.STAFF,):
                raise serializers.ValidationError(
                    "Managers can only create Staff accounts."
                )
        return value


class UserUpdateSerializer(serializers.ModelSerializer):
    """Admin/Manager updates a user's basic info (not password, not role)."""

    class Meta:
        model  = User
        fields = ["first_name", "last_name", "phone", "is_active"]


class UserRoleUpdateSerializer(serializers.Serializer):
    """Admin-only: change a user's role."""
    role = serializers.ChoiceField(choices=User.Role.choices)

    def validate_role(self, value):
        target_user = self.context.get("target_user")
        if target_user and target_user.is_superuser:
            raise serializers.ValidationError("Cannot change a superuser's role.")
        return value

    def save(self, target_user):
        from users.models import User as UserModel
        target_user.role = self.validated_data["role"]
        target_user.is_staff = target_user.role in (
            UserModel.Role.STAFF, UserModel.Role.MANAGER, UserModel.Role.ADMIN
        )
        target_user.save(update_fields=["role", "is_staff", "updated_at"])
        return target_user


class UserDeactivateSerializer(serializers.Serializer):
    """Admin deactivates/reactivates a user."""
    is_active = serializers.BooleanField()
    reason    = serializers.CharField(max_length=500, required=False, allow_blank=True)
