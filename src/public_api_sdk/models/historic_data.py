from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field


class BarPeriod(str, Enum):
    DAY = "DAY"
    WEEK = "WEEK"
    MONTH = "MONTH"
    QUARTER = "QUARTER"
    HALF_YEAR = "HALF_YEAR"
    YEAR = "YEAR"
    FIVE_YEARS = "FIVE_YEARS"
    YTD = "YTD"
    SINCE_PURCHASE = "SINCE_PURCHASE"


class BarAggregation(str, Enum):
    ONE_MINUTE = "ONE_MINUTE"
    FIVE_MINUTES = "FIVE_MINUTES"
    TEN_MINUTES = "TEN_MINUTES"
    FIFTEEN_MINUTES = "FIFTEEN_MINUTES"
    THIRTY_MINUTES = "THIRTY_MINUTES"
    ONE_HOUR = "ONE_HOUR"
    ONE_DAY = "ONE_DAY"
    ONE_WEEK = "ONE_WEEK"
    ONE_MONTH = "ONE_MONTH"
    THREE_MONTHS = "THREE_MONTHS"
    SIX_MONTHS = "SIX_MONTHS"
    ONE_YEAR = "ONE_YEAR"


class Bar(BaseModel):
    model_config = {"populate_by_name": True}

    timestamp: str = Field(..., description="Bar timestamp.")
    open: Decimal = Field(..., description="Opening price for the bar interval.")
    close: Decimal = Field(..., description="Closing price for the bar interval.")
    high: Decimal = Field(..., description="Highest price during the bar interval.")
    low: Decimal = Field(..., description="Lowest price during the bar interval.")
    value: Decimal = Field(..., description="Value of the bar.")
    volume: Decimal = Field(..., description="Volume traded during the bar interval.")
    gain_amount: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("gain_amount", "gainAmount"),
        serialization_alias="gainAmount",
        description="Gain in dollars relative to the reference price.",
    )
    gain_percentage: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("gain_percentage", "gainPercentage"),
        serialization_alias="gainPercentage",
        description="Gain as a percentage relative to the reference price.",
    )


class LastSessionClose(BaseModel):
    model_config = {"populate_by_name": True}

    close: Decimal = Field(..., description="Closing price of the last session.")
    close_date: str = Field(
        ...,
        validation_alias=AliasChoices("close_date", "closeDate"),
        serialization_alias="closeDate",
        description="Date of the last session close (YYYY-MM-DD).",
    )
    change: Optional[Decimal] = Field(
        None, description="Change vs. the prior session close."
    )
    percent_change: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("percent_change", "percentChange"),
        serialization_alias="percentChange",
        description="Percent change vs. the prior session close.",
    )


class MarketSessionBars(BaseModel):
    model_config = {"populate_by_name": True}

    expected_bars: int = Field(
        ...,
        validation_alias=AliasChoices("expected_bars", "expectedBars"),
        serialization_alias="expectedBars",
        description="Number of bars expected for the session.",
    )
    bars: List[Bar] = Field(..., description="List of bars for the session.")


class BarsResponse(BaseModel):
    model_config = {"populate_by_name": True}

    symbol: str = Field(..., description="The symbol the bar data belongs to.")
    period: str = Field(..., description="The requested period.")
    total_expected_bars: int = Field(
        ...,
        validation_alias=AliasChoices("total_expected_bars", "totalExpectedBars"),
        serialization_alias="totalExpectedBars",
        description="Total expected bars across all sessions.",
    )
    previous_close_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("previous_close_price", "previousClosePrice"),
        serialization_alias="previousClosePrice",
    )
    total_gain_loss: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("total_gain_loss", "totalGainLoss"),
        serialization_alias="totalGainLoss",
    )
    total_gain_loss_percentage: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices(
            "total_gain_loss_percentage", "totalGainLossPercentage"
        ),
        serialization_alias="totalGainLossPercentage",
    )
    pre_market: MarketSessionBars = Field(
        ...,
        validation_alias=AliasChoices("pre_market", "preMarket"),
        serialization_alias="preMarket",
        description="Pre-market session bars.",
    )
    regular_market: MarketSessionBars = Field(
        ...,
        validation_alias=AliasChoices("regular_market", "regularMarket"),
        serialization_alias="regularMarket",
        description="Regular market session bars.",
    )
    after_market: MarketSessionBars = Field(
        ...,
        validation_alias=AliasChoices("after_market", "afterMarket"),
        serialization_alias="afterMarket",
        description="After-hours session bars.",
    )
    last_regular_trading_session_close: Optional[LastSessionClose] = Field(
        None,
        validation_alias=AliasChoices(
            "last_regular_trading_session_close", "lastRegularTradingSessionClose"
        ),
        serialization_alias="lastRegularTradingSessionClose",
    )
