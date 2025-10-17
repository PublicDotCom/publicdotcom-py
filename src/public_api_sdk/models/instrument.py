from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field

from .instrument_type import InstrumentType
from .order import OrderInstrument


class Trading(str, Enum):
    BUY_AND_SELL = "BUY_AND_SELL"
    LIQUIDATION_ONLY = "LIQUIDATION_ONLY"
    DISABLED = "DISABLED"


class Instrument(BaseModel):
    instrument: OrderInstrument = Field(...)
    trading: Trading = Field(...)
    fractional_trading: Trading = Field(..., alias="fractionalTrading")
    option_trading: Trading = Field(..., alias="optionTrading")
    option_spread_trading: Trading = Field(..., alias="optionSpreadTrading")


class InstrumentsRequest(BaseModel):
    model_config = {"populate_by_name": True}

    type_filter: Optional[List[InstrumentType]] = Field(
        None,
        validation_alias=AliasChoices("type_filter", "typeFilter"),
        serialization_alias="typeFilter",
        description="optional set of security types to filter by",
    )
    trading_filter: Optional[List[Trading]] = Field(
        None,
        validation_alias=AliasChoices("trading_filter", "tradingFilter"),
        serialization_alias="tradingFilter",
        description="optional set of trading statuses to filter by",
    )
    fractional_trading_filter: Optional[List[Trading]] = Field(
        None,
        validation_alias=AliasChoices(
            "fractional_trading_filter", "fractionalTradingFilter"
        ),
        serialization_alias="fractionalTradingFilter",
        description="optional set of fractional trading statuses to filter by",
    )
    option_trading_filter: Optional[List[Trading]] = Field(
        None,
        validation_alias=AliasChoices("option_trading_filter", "optionTradingFilter"),
        serialization_alias="optionTradingFilter",
        description="optional set of option trading statuses to filter by",
    )
    option_spread_trading_filter: Optional[List[Trading]] = Field(
        None,
        validation_alias=AliasChoices(
            "option_spread_trading_filter", "optionSpreadTradingFilter"
        ),
        serialization_alias="optionSpreadTradingFilter",
        description="optional set of option spread trading statuses to filter by",
    )


class InstrumentsResponse(BaseModel):
    instruments: List[Instrument] = Field(...)
