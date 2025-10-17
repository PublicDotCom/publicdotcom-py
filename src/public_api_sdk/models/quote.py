from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field, AliasChoices

from .order import OrderInstrument


class QuoteOutcome(str, Enum):
    SUCCESS = "SUCCESS"
    UNKNOWN = "UNKNOWN"


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
