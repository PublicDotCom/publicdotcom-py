from decimal import Decimal
from enum import Enum
from typing import Any, List, Optional, Union

from pydantic import AliasChoices, BaseModel, Field, model_validator

from .instrument_type import InstrumentType
from .order import OrderInstrument, ShortingAvailability

# `ShortingAvailability` is imported from order.py so it's shared with the
# ShortSelling model used in preflight responses. Re-exported from this module
# so existing callers importing from `public_api_sdk.models.instrument` keep
# working.


class TradingPermission(str, Enum):
    """Trading permission for an instrument or instrument capability.

    Used as the value type for `Instrument.trading`, `fractional_trading`,
    `option_trading`, and `option_spread_trading`.
    """

    BUY_AND_SELL = "BUY_AND_SELL"
    LIQUIDATION_ONLY = "LIQUIDATION_ONLY"
    DISABLED = "DISABLED"


# Backwards-compatible alias.
Trading = TradingPermission
"""Deprecated alias for `TradingPermission`. Will be removed in a future release."""


class CryptoInstrumentDetails(BaseModel):
    """Details specific to crypto instruments."""

    model_config = {"populate_by_name": True}

    payload_type: str = Field(
        ...,
        validation_alias=AliasChoices("payload_type", "payloadType"),
        serialization_alias="payloadType",
    )
    crypto_quantity_precision: Optional[int] = Field(
        None,
        validation_alias=AliasChoices(
            "crypto_quantity_precision", "cryptoQuantityPrecision"
        ),
        serialization_alias="cryptoQuantityPrecision",
    )
    crypto_price_precision: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("crypto_price_precision", "cryptoPricePrecision"),
        serialization_alias="cryptoPricePrecision",
    )
    tradable_in_new_york: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("tradable_in_new_york", "tradableInNewYork"),
        serialization_alias="tradableInNewYork",
    )


class BondInstrumentDetails(BaseModel):
    """Details specific to bond instruments."""

    model_config = {"populate_by_name": True}

    payload_type: str = Field(
        ...,
        validation_alias=AliasChoices("payload_type", "payloadType"),
        serialization_alias="payloadType",
    )
    has_outstanding: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("has_outstanding", "hasOutstanding"),
        serialization_alias="hasOutstanding",
    )


# `instrumentDetails` is a polymorphic payload keyed by `payloadType`. Dispatch
# is handled by `Instrument._dispatch_instrument_details` below, which inspects
# `payloadType` (case-insensitive) to pick the right variant. Callers should
# branch on `payload_type` or `isinstance()`.
InstrumentDetails = Union[BondInstrumentDetails, CryptoInstrumentDetails]


class OptionPriceIncrement(BaseModel):
    """Price increments for option contracts (below and above $3)."""

    model_config = {"populate_by_name": True}

    increment_below_3: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("increment_below_3", "incrementBelow3"),
        serialization_alias="incrementBelow3",
    )
    increment_above_3: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("increment_above_3", "incrementAbove3"),
        serialization_alias="incrementAbove3",
    )


class Instrument(BaseModel):
    model_config = {"populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _dispatch_instrument_details(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        details = data.get("instrumentDetails", data.get("instrument_details"))
        if not isinstance(details, dict):
            return data
        payload_type = details.get("payloadType", details.get("payload_type", ""))
        lowered = str(payload_type).lower()
        if "crypto" in lowered:
            data["instrumentDetails"] = CryptoInstrumentDetails(**details)
        elif "bond" in lowered:
            data["instrumentDetails"] = BondInstrumentDetails(**details)
        return data

    instrument: OrderInstrument = Field(...)
    trading: TradingPermission = Field(...)
    fractional_trading: TradingPermission = Field(
        ...,
        validation_alias=AliasChoices("fractional_trading", "fractionalTrading"),
        serialization_alias="fractionalTrading",
    )
    option_trading: TradingPermission = Field(
        ...,
        validation_alias=AliasChoices("option_trading", "optionTrading"),
        serialization_alias="optionTrading",
    )
    option_spread_trading: TradingPermission = Field(
        ...,
        validation_alias=AliasChoices("option_spread_trading", "optionSpreadTrading"),
        serialization_alias="optionSpreadTrading",
    )
    instrument_details: Optional[InstrumentDetails] = Field(
        None,
        validation_alias=AliasChoices("instrument_details", "instrumentDetails"),
        serialization_alias="instrumentDetails",
        description=(
            "Polymorphic details keyed by `payloadType`. One of"
            " `BondInstrumentDetails` or `CryptoInstrumentDetails`."
        ),
    )
    shorting_availability: Optional[ShortingAvailability] = Field(
        None,
        validation_alias=AliasChoices("shorting_availability", "shortingAvailability"),
        serialization_alias="shortingAvailability",
        description="Short-selling availability for this instrument.",
    )
    hard_to_borrow_percentage_rate: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices(
            "hard_to_borrow_percentage_rate", "hardToBorrowPercentageRate"
        ),
        serialization_alias="hardToBorrowPercentageRate",
        description="Hard-to-borrow rate as a percentage value.",
    )
    option_contract_price_increments: Optional[OptionPriceIncrement] = Field(
        None,
        validation_alias=AliasChoices(
            "option_contract_price_increments", "optionContractPriceIncrements"
        ),
        serialization_alias="optionContractPriceIncrements",
        description="Price increments for option contracts on this instrument.",
    )


class InstrumentsRequest(BaseModel):
    model_config = {"populate_by_name": True}

    type_filter: Optional[List[InstrumentType]] = Field(
        None,
        validation_alias=AliasChoices("type_filter", "typeFilter"),
        serialization_alias="typeFilter",
        description="optional set of security types to filter by",
    )
    trading_filter: Optional[List[TradingPermission]] = Field(
        None,
        validation_alias=AliasChoices("trading_filter", "tradingFilter"),
        serialization_alias="tradingFilter",
        description="optional set of trading statuses to filter by",
    )
    fractional_trading_filter: Optional[List[TradingPermission]] = Field(
        None,
        validation_alias=AliasChoices(
            "fractional_trading_filter", "fractionalTradingFilter"
        ),
        serialization_alias="fractionalTradingFilter",
        description="optional set of fractional trading statuses to filter by",
    )
    option_trading_filter: Optional[List[TradingPermission]] = Field(
        None,
        validation_alias=AliasChoices("option_trading_filter", "optionTradingFilter"),
        serialization_alias="optionTradingFilter",
        description="optional set of option trading statuses to filter by",
    )
    option_spread_trading_filter: Optional[List[TradingPermission]] = Field(
        None,
        validation_alias=AliasChoices(
            "option_spread_trading_filter", "optionSpreadTradingFilter"
        ),
        serialization_alias="optionSpreadTradingFilter",
        description="optional set of option spread trading statuses to filter by",
    )


class InstrumentsResponse(BaseModel):
    instruments: List[Instrument] = Field(...)
