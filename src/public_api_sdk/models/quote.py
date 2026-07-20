from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field

from .order import OrderInstrument


class QuoteRequest(BaseModel):
    """Request body for `POST /marketdata/{accountId}/quotes`."""

    model_config = {"populate_by_name": True}

    instruments: List[OrderInstrument] = Field(
        ..., description="List of instruments to retrieve quotes for."
    )


class QuoteOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    UNKNOWN = "UNKNOWN"


class GreekValues(BaseModel):
    """The Greek values for an option. All fields are optional per the API contract."""

    model_config = {"populate_by_name": True}

    delta: Optional[Decimal] = Field(
        None,
        description=(
            "Delta is the theoretical estimate of how much an option's value may"
            " change given a $1 move UP or DOWN in the underlying security."
        ),
    )
    gamma: Optional[Decimal] = Field(
        None,
        description=(
            "Gamma represents the rate of change between an option's Delta and"
            " the underlying asset's price."
        ),
    )
    theta: Optional[Decimal] = Field(
        None,
        description=(
            "Theta represents the rate of change between the option price and"
            " time — an option's time decay."
        ),
    )
    vega: Optional[Decimal] = Field(
        None,
        description=(
            "Vega measures the amount of increase or decrease in an option"
            " premium based on a 1% change in implied volatility."
        ),
    )
    rho: Optional[Decimal] = Field(
        None,
        description=(
            "Rho represents the rate of change between an option's value and a"
            " 1% change in the interest rate."
        ),
    )
    implied_volatility: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("implied_volatility", "impliedVolatility"),
        serialization_alias="impliedVolatility",
        description=(
            "Implied volatility (IV) is a theoretical forecast of how volatile"
            " an underlying stock is expected to be in the future."
        ),
    )


class OneDayChange(BaseModel):
    """One-day price change data for a quote.

    Values are provided by the data source (e.g., Xignite) and may differ from
    simple subtraction of current price minus previous close due to corporate
    actions, stock splits, or other adjustments.
    """

    model_config = {"populate_by_name": True}

    change: Optional[Decimal] = Field(
        None, description="The one-day price change in dollars."
    )
    percent_change: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("percent_change", "percentChange"),
        serialization_alias="percentChange",
        description="The one-day price change as a percentage.",
    )


class QuoteOptionDetails(BaseModel):
    """Option-specific details for a quote: greeks, strike price, and mid price."""

    model_config = {"populate_by_name": True}

    greeks: Optional[GreekValues] = Field(None)
    strike_price: Decimal = Field(
        ...,
        validation_alias=AliasChoices("strike_price", "strikePrice"),
        serialization_alias="strikePrice",
        description="The strike price for the option contract.",
    )
    mid_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("mid_price", "midPrice"),
        serialization_alias="midPrice",
        description=(
            "The mid price (average of bid and ask) for the option contract."
            " Null if bid/ask data is not available."
        ),
    )


class BondDetails(BaseModel):
    """Bond-specific details for a quote. All fields optional per the contract."""

    model_config = {"populate_by_name": True}

    ask_min_size: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("ask_min_size", "askMinSize"),
        serialization_alias="askMinSize",
        description="Minimum trade size for asks in par value.",
    )
    bid_min_size: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("bid_min_size", "bidMinSize"),
        serialization_alias="bidMinSize",
        description="Minimum trade size for bids in par value.",
    )
    ask_markup: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("ask_markup", "askMarkup"),
        serialization_alias="askMarkup",
        description="Ask markup percentage.",
    )
    bid_markup: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("bid_markup", "bidMarkup"),
        serialization_alias="bidMarkup",
        description="Bid markup percentage.",
    )
    suggested_buy_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("suggested_buy_price", "suggestedBuyPrice"),
        serialization_alias="suggestedBuyPrice",
        description="Suggested buy price for this bond.",
    )
    suggested_sell_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("suggested_sell_price", "suggestedSellPrice"),
        serialization_alias="suggestedSellPrice",
        description="Suggested sell price for this bond.",
    )
    min_buy_amount: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("min_buy_amount", "minBuyAmount"),
        serialization_alias="minBuyAmount",
        description="Minimum buy amount in dollars.",
    )
    min_buy_increment_amount: Optional[str] = Field(
        None,
        validation_alias=AliasChoices(
            "min_buy_increment_amount", "minBuyIncrementAmount"
        ),
        serialization_alias="minBuyIncrementAmount",
        description="Minimum buy increment amount in dollars.",
    )


class Quote(BaseModel):
    model_config = {"populate_by_name": True}

    instrument: OrderInstrument = Field(...)
    outcome: QuoteOutcome = Field(
        ...,
        description="The outcome status of the quote request.",
    )
    last: Optional[Decimal] = Field(
        None,
        description=(
            "The last traded price of the instrument. Can be null if no trades"
            " have occurred."
        ),
    )
    last_timestamp: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("last_timestamp", "lastTimestamp"),
        serialization_alias="lastTimestamp",
        description=(
            "Timestamp of when the last trade occurred. Can be null if no trades"
            " have occurred."
        ),
    )
    bid: Optional[Decimal] = Field(
        None,
        description=(
            "The current bid price (sell-side price) in the market. Can be null if"
            " no bid exists."
        ),
    )
    bid_size: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("bid_size", "bidSize"),
        serialization_alias="bidSize",
        description=(
            "Number of shares, contracts, or units available at the given bid price."
        ),
    )
    bid_timestamp: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("bid_timestamp", "bidTimestamp"),
        serialization_alias="bidTimestamp",
        description=(
            "Timestamp of when the bid price was last updated. Can be null if no bid"
            " exists."
        ),
    )
    ask: Optional[Decimal] = Field(
        None,
        description=(
            "The current ask price (buy-side price) in the market. Can be null if no"
            " ask exists."
        ),
    )
    ask_size: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("ask_size", "askSize"),
        serialization_alias="askSize",
        description=(
            "Number of shares, contracts, or units available at the given ask price."
        ),
    )
    ask_timestamp: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("ask_timestamp", "askTimestamp"),
        serialization_alias="askTimestamp",
        description=(
            "Timestamp of when the ask price was last updated. Can be null if no ask"
            " exists."
        ),
    )
    volume: Optional[int] = Field(
        None,
        description=("The total volume traded on the date of the last trade."),
    )
    open_interest: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("open_interest", "openInterest"),
        serialization_alias="openInterest",
        description=(
            "The total number of options contracts that are not closed or delivered"
            " on a particular day."
        ),
    )
    previous_close: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("previous_close", "previousClose"),
        serialization_alias="previousClose",
        description="The previous day's close price from the last trading session.",
    )
    one_day_change: Optional[OneDayChange] = Field(
        None,
        validation_alias=AliasChoices("one_day_change", "oneDayChange"),
        serialization_alias="oneDayChange",
        description="One-day price change data (dollars and percent).",
    )
    option_details: Optional[QuoteOptionDetails] = Field(
        None,
        validation_alias=AliasChoices("option_details", "optionDetails"),
        serialization_alias="optionDetails",
        description="Option-specific details: greeks, strike price, and mid price.",
    )
    bond_details: Optional[BondDetails] = Field(
        None,
        validation_alias=AliasChoices("bond_details", "bondDetails"),
        serialization_alias="bondDetails",
        description="Bond-specific details: markup, min size, and suggested prices.",
    )
