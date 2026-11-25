"""Lenient enum annotations for response models.

The API adds enum values without notice (new order types, sessions, account
types). A strict enum field fails validation on a value the SDK does not know
yet, and with it the whole response: one unfamiliar order breaks
``get_portfolio`` or ``search_orders``. Response models therefore annotate
their enum fields with these types: a known value still becomes the enum
member, an unknown one is kept as its raw string.

Request models stay strict, so the SDK never sends a value it doesn't know.
"""

from enum import Enum
from typing import Any, Callable, Type, TypeVar, Union

from pydantic import BeforeValidator
from typing_extensions import Annotated

from .account import AccountType
from .instrument_type import InstrumentType
from .order_enums import (
    EquityMarketSession,
    LegInstrumentType,
    OpenCloseIndicator,
    OrderSide,
    OrderType,
    TimeInForce,
    TrailingStopType,
)

_E = TypeVar("_E", bound=Enum)


def _lenient(enum_cls: Type[_E]) -> Callable[[Any], Any]:
    """Coerce a known value to ``enum_cls`` and leave an unknown one as is."""

    def _coerce(value: Any) -> Any:
        if isinstance(value, str) and not isinstance(value, Enum):
            try:
                return enum_cls(value)
            except ValueError:
                return value
        return value

    return _coerce


def enum_value(value: Union[Enum, str]) -> str:
    """The wire value of a lenient enum field, whether it is a member or a
    raw string."""
    return str(value.value) if isinstance(value, Enum) else value


LenientOrderType = Annotated[
    Union[OrderType, str], BeforeValidator(_lenient(OrderType))
]
LenientOrderSide = Annotated[
    Union[OrderSide, str], BeforeValidator(_lenient(OrderSide))
]
LenientInstrumentType = Annotated[
    Union[InstrumentType, str], BeforeValidator(_lenient(InstrumentType))
]
LenientLegInstrumentType = Annotated[
    Union[LegInstrumentType, str], BeforeValidator(_lenient(LegInstrumentType))
]
LenientTimeInForce = Annotated[
    Union[TimeInForce, str], BeforeValidator(_lenient(TimeInForce))
]
LenientMarketSession = Annotated[
    Union[EquityMarketSession, str], BeforeValidator(_lenient(EquityMarketSession))
]
LenientOpenCloseIndicator = Annotated[
    Union[OpenCloseIndicator, str], BeforeValidator(_lenient(OpenCloseIndicator))
]
LenientTrailingStopType = Annotated[
    Union[TrailingStopType, str], BeforeValidator(_lenient(TrailingStopType))
]
LenientAccountType = Annotated[
    Union[AccountType, str], BeforeValidator(_lenient(AccountType))
]
