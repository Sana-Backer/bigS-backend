from rest_framework import status
from rest_framework.exceptions import APIException


class ProductAlreadyInWishlist(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "This product is already in your wishlist."
    default_code = "product_already_in_wishlist"


class ProductNotAvailable(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "This product is not currently available."
    default_code = "product_not_available"
