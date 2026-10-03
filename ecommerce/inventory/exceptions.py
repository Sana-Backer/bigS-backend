"""inventory/exceptions.py"""


class InventoryError(Exception):
    """Base class for expected, user-facing inventory problems (HTTP 400)."""


class InsufficientStockError(InventoryError):
    """A movement would take stock below zero."""
