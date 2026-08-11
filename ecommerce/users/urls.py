"""
users/urls.py

Mount in root urls.py:
    path("api/", include("users.urls")),

Full URL map
------------
Auth
  POST  api/auth/register/
  POST  api/auth/login/
  POST  api/auth/logout/
  POST  api/auth/token/refresh/
  POST  api/auth/change-password/
  POST  api/auth/forgot-password/
  POST  api/auth/reset-password/

Me
  GET   api/auth/me/
  PUT   api/auth/me/
  GET   api/auth/me/profile/
  PUT   api/auth/me/profile/

Addresses (own)
  GET   api/auth/me/addresses/
  POST  api/auth/me/addresses/
  GET   api/auth/me/addresses/{id}/
  PUT   api/auth/me/addresses/{id}/
  DEL   api/auth/me/addresses/{id}/

Guest
  POST  api/auth/guest/session/
  POST  api/auth/guest/checkout/
  POST  api/auth/guest/convert/

Admin – User Management
  GET   api/admin/users/                    [STAFF+ read]
  POST  api/admin/users/                    [ADMIN]
  GET   api/admin/users/{id}/               [STAFF+]
  PUT   api/admin/users/{id}/               [MANAGER+]
  DEL   api/admin/users/{id}/               [ADMIN]
  POST  api/admin/users/{id}/role/          [ADMIN]
  POST  api/admin/users/{id}/activate/      [MANAGER+]
  GET   api/admin/staff/                    [MANAGER+]
  POST  api/admin/staff/                    [MANAGER+]
  GET   api/admin/guests/                   [MANAGER+]
  GET   api/admin/guests/{id}/              [MANAGER+]
"""

from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from . import views

urlpatterns = [

    # ── Auth ──────────────────────────────────────────────────────────────
    path("auth/register/",          views.RegisterView.as_view(),       name="auth-register"),
    path("auth/login/",             views.LoginView.as_view(),          name="auth-login"),
    path("auth/logout/",            views.LogoutView.as_view(),         name="auth-logout"),
    path("auth/token/refresh/",     TokenRefreshView.as_view(),         name="auth-token-refresh"),
    path("auth/change-password/",   views.ChangePasswordView.as_view(), name="auth-change-password"),
    path("auth/forgot-password/",   views.ForgotPasswordView.as_view(), name="auth-forgot-password"),
    path("auth/reset-password/",    views.ResetPasswordView.as_view(),  name="auth-reset-password"),

    # ── Me ────────────────────────────────────────────────────────────────
    path("auth/me/",                views.MeView.as_view(),             name="auth-me"),
    path("auth/me/profile/",        views.MyProfileView.as_view(),      name="auth-me-profile"),

    # ── Addresses (own) ───────────────────────────────────────────────────
    path("auth/me/addresses/",           views.MyAddressListCreateView.as_view(), name="auth-address-list"),
    path("auth/me/addresses/<uuid:id>/", views.MyAddressDetailView.as_view(),     name="auth-address-detail"),

    # ── Guest ─────────────────────────────────────────────────────────────
    path("auth/guest/session/",     views.GuestSessionView.as_view(),   name="guest-session"),
    path("auth/guest/checkout/",    views.GuestCheckoutView.as_view(),  name="guest-checkout"),
    path("auth/guest/convert/",     views.GuestConvertView.as_view(),   name="guest-convert"),

    # ── Admin – User Management ───────────────────────────────────────────
    path("admin/users/",                         views.AdminUserListCreateView.as_view(),  name="admin-user-list"),
    path("admin/users/<uuid:id>/",               views.AdminUserDetailView.as_view(),      name="admin-user-detail"),
    path("admin/users/<uuid:id>/role/",          views.AdminUserRoleView.as_view(),        name="admin-user-role"),
    path("admin/users/<uuid:id>/activate/",      views.AdminUserActivateView.as_view(),    name="admin-user-activate"),

    # ── Admin – Staff ─────────────────────────────────────────────────────
    path("admin/staff/",                         views.AdminStaffListCreateView.as_view(), name="admin-staff-list"),

    # ── Admin – Guests ────────────────────────────────────────────────────
    path("admin/guests/",                        views.AdminGuestListView.as_view(),       name="admin-guest-list"),
    path("admin/guests/<uuid:id>/",              views.AdminGuestDetailView.as_view(),     name="admin-guest-detail"),
]
