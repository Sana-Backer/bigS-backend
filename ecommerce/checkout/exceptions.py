from rest_framework import status
from rest_framework.exceptions import APIException


class AddressRequired(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A billing and shipping address are required to check out."
    default_code = "address_required"


class AddressNotFound(APIException):
    status_code = status.HTTP_404_NOT_FOUND
    default_detail = "The selected address could not be found."
    default_code = "address_not_found"


class GuestEmailRequired(APIException):
    status_code = status.HTTP_400_BAD_REQUEST
    default_detail = "A guest email address is required to check out as a guest."
    default_code = "guest_email_required"
