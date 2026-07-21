"""Models for the option strategy-quote endpoint.

Response models (`QuoteSpecificDetail`, `BondQuoteDetail`, `SignedQuote`,
`StrategyLegInstrumentDto`, `StrategyLegDto`, `StrategyQuoteDto`) map to the
spec's `com.matadorapp.shared.customerordergateway.dto.*` and
`com.hellopublic.trading.core.quote.*` schemas and follow the plain
`Field(..., alias="camelCase")` response convention.

`StrategyOrderLeg` (the spec's `OrderLeg`, renamed to avoid colliding with the
response-side `OrderLeg` in order.py) and `StrategyQuoteRequest` are REQUEST
models and follow the request convention used elsewhere in the SDK:
`populate_by_name=True`, per-field `validation_alias=AliasChoices(...)` /
`serialization_alias=...`, and `@field_serializer` to stringify enums.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field, field_serializer

from .order import OpenCloseIndicator, OptionType, OrderSide, UptickRule

# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class QuoteSpecificDetail(BaseModel):
    """Base for quote-specific details, keyed by the `type` discriminator."""

    type: str = Field(...)


class BondQuoteDetail(QuoteSpecificDetail):
    """Bond-specific quote details (markup / min size)."""

    ask_min_size: Optional[str] = Field(None, alias="askMinSize")
    bid_min_size: Optional[str] = Field(None, alias="bidMinSize")
    ask_markup: Optional[str] = Field(None, alias="askMarkup")
    bid_markup: Optional[str] = Field(None, alias="bidMarkup")


class SignedQuote(BaseModel):
    """A signed quote for a single instrument, as attached to a strategy leg."""

    symbol: str = Field(..., description="The symbol identifying the instrument.")
    last: Optional[Decimal] = Field(
        None, description="The last trade for this instrument."
    )
    bid: Optional[Decimal] = Field(
        None, description="The last bid price for this instrument."
    )
    bid_size: Optional[Decimal] = Field(
        None,
        alias="bidSize",
        description="The number of units available at the given bid price.",
    )
    ask: Optional[Decimal] = Field(
        None, description="The last ask price for this instrument."
    )
    ask_size: Optional[Decimal] = Field(
        None,
        alias="askSize",
        description="The number of units available at the given ask price.",
    )
    timestamp: datetime = Field(
        ...,
        description="The timestamp when the server returned this message.",
    )
    signature: str = Field(
        ...,
        description=(
            "A hash of the properties, to make sure the app does not change any"
            " of the data when posting back the quote during order creation."
        ),
    )
    collar_percentage: Optional[Decimal] = Field(None, alias="collarPercentage")
    buy_collar: Optional[Decimal] = Field(None, alias="buyCollar")
    sell_collar: Optional[Decimal] = Field(None, alias="sellCollar")
    open_interest: Optional[int] = Field(
        None,
        alias="openInterest",
        description=(
            "The total number of options contracts that are not closed or"
            " delivered on a particular day. Null for non-option quotes."
        ),
    )
    bid_collar: Optional[Decimal] = Field(None, alias="bidCollar")
    ask_collar: Optional[Decimal] = Field(None, alias="askCollar")
    detail: Optional[BondQuoteDetail] = Field(
        None,
        description="Additional quote-specific details (e.g. bond markup).",
    )
    trading_halted: Optional[bool] = Field(
        None,
        alias="tradingHalted",
        description="Indicates if trading is currently halted on the symbol.",
    )
    uptick_rule: Optional[UptickRule] = Field(None, alias="uptickRule")


class StrategyLegInstrumentDto(BaseModel):
    """Defines the instrument for a strategy leg."""

    symbol: str = Field(..., description="Instrument symbol.")
    base_symbol: Optional[str] = Field(
        None,
        alias="baseSymbol",
        description="Base symbol. Only available for option legs.",
    )
    type: Optional[OptionType] = Field(
        None, description="Type of option. Only available for option legs."
    )
    strike_price: Optional[Decimal] = Field(
        None,
        alias="strikePrice",
        description="Option strike price. Only available for option legs.",
    )
    expiration_date: Optional[str] = Field(
        None,
        alias="expirationDate",
        description="Option expiration date (YYYY-MM-DD). Only for option legs.",
    )


class StrategyLegDto(BaseModel):
    """A single leg of a strategy quote, with its instrument and signed quote."""

    instrument: StrategyLegInstrumentDto = Field(...)
    side: OrderSide = Field(..., description="Order side for the leg.")
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        alias="openCloseIndicator",
        description="Open/close indicator for the leg. Null for the equity leg.",
    )
    ratio_quantity: int = Field(
        ..., alias="ratioQuantity", description="Ratio quantity for the leg."
    )
    quote: Optional[SignedQuote] = Field(None)


class DebitCredit(str, Enum):
    """Whether a strategy is a debit or credit strategy."""

    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    UNDECIDED = "UNDECIDED"


class StrategyQuoteDto(BaseModel):
    """Quote for a multi-leg strategy."""

    debit_credit: Optional[DebitCredit] = Field(
        None,
        alias="debitCredit",
        description=(
            "Flag to determine if the strategy is a debit or credit strategy."
            " UNDECIDED is returned when the spread straddles $0.00."
        ),
    )
    strategy_legs: List[StrategyLegDto] = Field(
        ..., alias="strategyLegs", description="Legs and their quotes."
    )
    equity_quote: Optional[StrategyLegDto] = Field(None, alias="equityQuote")
    price: Decimal = Field(..., description="Strategy price.")
    bid: Decimal = Field(..., description="Strategy bid (same value as price).")
    ask: Decimal = Field(..., description="Strategy ask.")
    mark: Optional[Decimal] = Field(None, description="Mark price, average of bid/ask.")
    strategy_name: str = Field(
        ..., alias="strategyName", description="Name of the strategy."
    )
    expiration_date: Optional[str] = Field(
        None,
        alias="expirationDate",
        description=(
            "Strategy expiration date (YYYY-MM-DD). Null if legs expire on"
            " different dates or an equity leg is part of the strategy."
        ),
    )


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class StrategyOrderLeg(BaseModel):
    """Leg definition for a strategy-quote request.

    Maps to the spec's `com.matadorapp.shared.customerordergateway.dto.OrderLeg`
    (renamed to avoid colliding with the response `OrderLeg` in order.py).
    """

    model_config = {"populate_by_name": True}

    symbol: str = Field(..., description="Symbol for the leg.")
    side: OrderSide = Field(..., description="Side for the leg.")
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        validation_alias=AliasChoices("open_close_indicator", "openCloseIndicator"),
        serialization_alias="openCloseIndicator",
        description="Position effect for the leg. Null for the equity leg.",
    )
    ratio_quantity: int = Field(
        ...,
        validation_alias=AliasChoices("ratio_quantity", "ratioQuantity"),
        serialization_alias="ratioQuantity",
        description="Ratio quantity for the leg.",
    )

    @field_serializer("side")
    def serialize_side(self, value: OrderSide) -> str:
        return value.value

    @field_serializer("open_close_indicator")
    def serialize_open_close_indicator(
        self, value: Optional[OpenCloseIndicator]
    ) -> Optional[str]:
        return value.value if value else None


class StrategyQuoteRequest(BaseModel):
    """Request body for `POST .../strategy-details/quote`."""

    model_config = {"populate_by_name": True}

    base_symbol: str = Field(
        ...,
        validation_alias=AliasChoices("base_symbol", "baseSymbol"),
        serialization_alias="baseSymbol",
        description="Base symbol for the strategy.",
    )
    option_legs: List[StrategyOrderLeg] = Field(
        ...,
        validation_alias=AliasChoices("option_legs", "optionLegs"),
        serialization_alias="optionLegs",
        description="Option legs for the order.",
    )
    equity_leg: Optional[StrategyOrderLeg] = Field(
        None,
        validation_alias=AliasChoices("equity_leg", "equityLeg"),
        serialization_alias="equityLeg",
        description="Optional equity leg for the strategy.",
    )
