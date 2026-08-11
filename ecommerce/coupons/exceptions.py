from rest_framework import status
from rest_framework.exceptions import APIException


class CouponNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "Coupon not found."
    default_code = "coupon_not_found"


class CouponNotActive(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This coupon is not currently active."
    default_code = "coupon_not_active"


class CouponNotValidYet(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This coupon is not valid yet."
    default_code = "coupon_not_valid_yet"


class CouponMinimumNotMet(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "Cart does not meet the minimum order amount for this coupon."
    default_code = "coupon_minimum_not_met"


class CouponUsageLimitExceeded(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This coupon has reached its usage limit."
    default_code = "coupon_usage_limit_exceeded"


class CouponUserLimitExceeded(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "You have already used this coupon the maximum number of times."
    default_code = "coupon_user_limit_exceeded"


class CouponAlreadyApplied(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "A coupon is already applied to this cart. Remove it before applying another."
    default_code = "coupon_already_applied"


class NoCouponApplied(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "No coupon is currently applied to this cart."
    default_code = "no_coupon_applied"
