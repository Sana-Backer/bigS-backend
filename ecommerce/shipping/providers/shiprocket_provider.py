"""
shipping/providers/shiprocket_provider.py

Thin wrapper around the Shiprocket REST API (https://apiv2.shiprocket.in).

This is the ONLY module in the project allowed to read SHIPROCKET_EMAIL
/ SHIPROCKET_PASSWORD from settings or talk to the Shiprocket HTTP API
directly — everything else (services.py, views.py) calls the functions
below, never `requests` or the settings values directly. This mirrors
payments/providers/razorpay_provider.py's role for Razorpay.

Token caching & expiry
-----------------------
Shiprocket's `/auth/login` endpoint returns a bearer token valid for a
fixed window (documented as ~10 days). Logging in on every single API
call would be wasteful and would eventually get the account rate
limited, so the token is cached via Django's cache framework
(`django.core.cache.cache`) under SHIPROCKET_TOKEN_CACHE_KEY, with a
timeout of SHIPROCKET_TOKEN_TTL_SECONDS (kept comfortably shorter than
Shiprocket's real expiry so this app always refreshes a little early
rather than getting caught out by clock drift).

If a request nonetheless comes back 401 (token expired/revoked
server-side sooner than expected), `_request()` clears the cached
token and retries exactly once with a freshly fetched one — so token
expiry is handled transparently without ever surfacing a stale-token
error to the caller.
"""

import logging

import requests
from django.conf import settings
from django.core.cache import cache

from ..exceptions import ShiprocketAPIError, ShiprocketAuthenticationFailed

logger = logging.getLogger("shipping")

DEFAULT_BASE_URL = "https://apiv2.shiprocket.in/v1/external"
DEFAULT_TOKEN_TTL_SECONDS = 9 * 24 * 60 * 60  # 9 days — under Shiprocket's ~10 day expiry
REQUEST_TIMEOUT_SECONDS = 15


def _base_url() -> str:
    return getattr(settings, "SHIPROCKET_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _token_cache_key() -> str:
    return getattr(settings, "SHIPROCKET_TOKEN_CACHE_KEY", "shiprocket:auth_token")


def _token_ttl_seconds() -> int:
    return getattr(settings, "SHIPROCKET_TOKEN_TTL_SECONDS", DEFAULT_TOKEN_TTL_SECONDS)


# ---------------------------------------------------------------------------
# Authentication / token caching
# ---------------------------------------------------------------------------

def _login() -> str:
    """
    Calls POST /auth/login with SHIPROCKET_EMAIL / SHIPROCKET_PASSWORD
    and returns the bearer token. Never called directly by services.py
    — always go through get_token().
    """
    email = getattr(settings, "SHIPROCKET_EMAIL", "")
    password = getattr(settings, "SHIPROCKET_PASSWORD", "")
    if not email or not password:
        raise ShiprocketAuthenticationFailed(
            "SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD must be configured."
        )

    try:
        response = requests.post(
            f"{_base_url()}/auth/login",
            json={"email": email, "password": password},
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ShiprocketAuthenticationFailed(str(exc)) from exc

    if response.status_code != 200:
        raise ShiprocketAuthenticationFailed(
            f"Shiprocket login failed with status {response.status_code}."
        )

    token = (response.json() or {}).get("token")
    if not token:
        raise ShiprocketAuthenticationFailed("Shiprocket login response did not include a token.")
    return token


def get_token(force_refresh: bool = False) -> str:
    """
    Returns a cached Shiprocket bearer token, logging in only if there
    isn't one cached (or force_refresh=True). This is the single choke
    point for token caching + expiry handling described in the module
    docstring.
    """
    cache_key = _token_cache_key()
    if not force_refresh:
        cached = cache.get(cache_key)
        if cached:
            return cached

    token = _login()
    cache.set(cache_key, token, timeout=_token_ttl_seconds())
    return token


def invalidate_token():
    """Drops the cached token, forcing the next call to re-authenticate."""
    cache.delete(_token_cache_key())


# ---------------------------------------------------------------------------
# Generic authenticated request (handles 401 -> refresh -> retry once)
# ---------------------------------------------------------------------------

def _request(method: str, path: str, *, params=None, json_body=None, retry_on_auth_failure=True):
    token = get_token()
    headers = {"Authorization": f"Bearer {token}"}

    try:
        response = requests.request(
            method,
            f"{_base_url()}{path}",
            headers=headers,
            params=params,
            json=json_body,
            timeout=REQUEST_TIMEOUT_SECONDS,
        )
    except requests.RequestException as exc:
        raise ShiprocketAPIError(str(exc)) from exc

    if response.status_code == 401 and retry_on_auth_failure:
        # Token expired/revoked earlier than our cached TTL assumed —
        # refresh once and retry exactly once, transparently.
        invalidate_token()
        return _request(method, path, params=params, json_body=json_body, retry_on_auth_failure=False)

    if response.status_code >= 400:
        detail = _extract_error_detail(response)
        raise ShiprocketAPIError(f"Shiprocket API error ({response.status_code}): {detail}")

    try:
        return response.json()
    except ValueError as exc:
        raise ShiprocketAPIError("Shiprocket returned a non-JSON response.") from exc


def _extract_error_detail(response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(data, dict):
        return str(data.get("message") or data.get("errors") or data)[:300]
    return str(data)[:300]


# ---------------------------------------------------------------------------
# Serviceability
# ---------------------------------------------------------------------------

def check_serviceability(*, pickup_postcode: str, delivery_postcode: str, weight, cod: bool = False) -> dict:
    return _request(
        "GET",
        "/courier/serviceability/",
        params={
            "pickup_postcode": pickup_postcode,
            "delivery_postcode": delivery_postcode,
            "weight": str(weight),
            "cod": 1 if cod else 0,
        },
    )


# ---------------------------------------------------------------------------
# Orders / shipments
# ---------------------------------------------------------------------------

def create_order(payload: dict) -> dict:
    """Creates a Shiprocket order (POST /orders/create/adhoc)."""
    return _request("POST", "/orders/create/adhoc", json_body=payload)


def assign_awb(*, shipment_id: str, courier_id: str = None) -> dict:
    body = {"shipment_id": shipment_id}
    if courier_id:
        body["courier_id"] = courier_id
    return _request("POST", "/courier/assign/awb", json_body=body)


def generate_label(shipment_ids: list) -> dict:
    return _request("POST", "/courier/generate/label", json_body={"shipment_id": shipment_ids})


def generate_manifest(shipment_ids: list) -> dict:
    return _request("POST", "/manifests/generate", json_body={"shipment_id": shipment_ids})


def track_by_awb(awb_code: str) -> dict:
    return _request("GET", f"/courier/track/awb/{awb_code}")


def track_by_shipment_id(shipment_id: str) -> dict:
    return _request("GET", f"/courier/track/shipment/{shipment_id}")


def cancel_order(shiprocket_order_ids: list) -> dict:
    return _request("POST", "/orders/cancel", json_body={"ids": shiprocket_order_ids})
