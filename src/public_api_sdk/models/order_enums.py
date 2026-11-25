"""Enums shared by the order request and response models.

They live in their own module so :mod:`public_api_sdk.models._lenient` can
build lenient annotations from them without importing ``order.py`` (which
imports ``_lenient``). Import them from :mod:`public_api_sdk.models.order` or
the package root as before; that is still their public home.
"""

from enum import Enum


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"

    def __str__(self) -> str:
        return str(self.value)


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"
    MARKET_ON_CLOSE = "MARKET_ON_CLOSE"
    LIMIT_ON_CLOSE = "LIMIT_ON_CLOSE"
    TRAILING_STOP = "TRAILING_STOP"
    """Response only: the trailing stop-loss leg of a BRACKET or OTO order.
    Placed through ``StopLoss`` on the bracket, never as a standalone order."""
    TRAILING_STOP_LIMIT = "TRAILING_STOP_LIMIT"
    """Response only: like ``TRAILING_STOP``, with a limit offset."""

    def __str__(self) -> str:
        return str(self.value)


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTD = "GTD"

    def __str__(self) -> str:
        return str(self.value)


class OpenCloseIndicator(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"

    def __str__(self) -> str:
        return str(self.value)


class EquityMarketSession(str, Enum):
    CORE = "CORE"
    EXTENDED = "EXTENDED"
    TWENTY_FOUR_HOURS = "TWENTY_FOUR_HOURS"

    def __str__(self) -> str:
        return str(self.value)


class LegInstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"

    def __str__(self) -> str:
        return str(self.value)


class TrailingStopType(str, Enum):
    """How a trailing stop's trail is expressed."""

    AMOUNT = "AMOUNT"
    """A fixed dollar amount below (sell) or above (buy) the watermark."""
    PERCENTAGE = "PERCENTAGE"
    """A fraction of the watermark: a value of 0.05 trails by 5%."""

    def __str__(self) -> str:
        return str(self.value)
