from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import (
    BaseModel,
    Field,
    AliasChoices,
    field_serializer,
    field_validator,
    model_validator,
)

from .order import (
    OpenCloseIndicator,
    OrderExpirationRequest,
    OrderInstrument,
    OrderSide,
    OrderType,
    RegulatoryFees,
    MarginRequirement,
    MarginImpact,
    PriceIncrement,
    OptionType,
)
from .quote import Quote


class MultilegValidationMixin:
    """
    Mixin class for shared validations between MultilegOrderRequest and PreflightMultiLegRequest.
    """

    @classmethod
    def validate_order_type_limit_only(cls, v: OrderType) -> OrderType:
        """Validate that only LIMIT orders are allowed for multi-leg orders."""
        if v != OrderType.LIMIT:
            raise ValueError(
                f"Only LIMIT orders are allowed for multi-leg orders, not {v.value}"
            )
        return v

    def validate_legs_common(self) -> None:
        """Common validation for legs in multi-leg orders."""
        if hasattr(self, "legs"):
            leg_count = len(self.legs)
            if leg_count < 2 or leg_count > 6:
                raise ValueError(
                    f"Multi-leg orders must have between 2 and 6 legs, got {leg_count}"
                )
            # count equity legs
            equity_legs = sum(
                1
                for leg in self.legs
                if hasattr(leg, "instrument")
                and hasattr(leg.instrument, "type")
                and leg.instrument.type == LegInstrumentType.EQUITY
            )
            if equity_legs > 1:
                raise ValueError(
                    f"Multi-leg orders can have at most 1 equity leg, got {equity_legs}"
                )


class OptionExpirationsRequest(BaseModel):
    instrument: OrderInstrument = Field(...)


class OptionExpirationsResponse(BaseModel):
    base_symbol: str = Field(
        ...,
        alias="baseSymbol",
        description="The base symbol for which the option expirations belong.",
    )
    expirations: List[str] = Field(
        ...,
        description="List of option expirations for the given symbol.",
    )


class OptionChainRequest(BaseModel):
    model_config = {"populate_by_name": True}

    instrument: OrderInstrument = Field(...)
    expiration_date: str = Field(
        ...,
        validation_alias=AliasChoices("expiration_date", "expirationDate"),
        serialization_alias="expirationDate",
        description="The expiration date of the option chain. Format: YYYY-MM-DD",
    )


class OptionChainResponse(BaseModel):
    base_symbol: str = Field(
        ...,
        alias="baseSymbol",
        description="The base symbol for which the option chain belongs.",
    )
    calls: List[Quote] = Field(
        ...,
        description="List of call quotes for the given option chain.",
    )
    puts: List[Quote] = Field(
        ...,
        description="List of put quotes for the given option chain.",
    )


class LegInstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class LegInstrument(BaseModel):
    symbol: str = Field(...)
    type: LegInstrumentType = Field(...)


class OrderLegRequest(BaseModel):
    instrument: LegInstrument = Field(...)
    side: OrderSide = Field(...)
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        validation_alias=AliasChoices("open_close_indicator", "openCloseIndicator"),
        serialization_alias="openCloseIndicator",
        description=(
            "Present if instrument.type = OPTION, used to determine if the "
            "leg is buy-to-open or buy-to-close"
        ),
    )
    ratio_quantity: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("ratio_quantity", "ratioQuantity"),
        serialization_alias="ratioQuantity",
        description=(
            "The ratio between legs. Equity legs will typically be 100 shares, "
            "and option legs 1 contract"
        ),
    )

    @field_validator("ratio_quantity")
    @classmethod
    def validate_ratio_quantity(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("`ratio_quantity` must be greater than 0")
        return v

    @model_validator(mode="after")
    def validate_open_close_for_options(self) -> "OrderLegRequest":
        """Validate that open_close_indicator is present for OPTION legs."""
        # check if instrument exists and is a LegInstrument instance
        if hasattr(self, "instrument") and isinstance(self.instrument, LegInstrument):
            if hasattr(self.instrument, "type"):
                if self.instrument.type == LegInstrumentType.OPTION:
                    if self.open_close_indicator is None:
                        raise ValueError(
                            "`open_close_indicator` is required for OPTION legs"
                        )
                elif self.instrument.type == LegInstrumentType.EQUITY:
                    if self.open_close_indicator is not None:
                        raise ValueError(
                            "`open_close_indicator` should not be provided for EQUITY legs"
                        )
        return self

    @field_serializer("open_close_indicator")
    def serialize_open_close_indicator(
        self, value: Optional[OpenCloseIndicator]
    ) -> Optional[str]:
        return value.value if value else None


class PreflightMultiLegRequest(MultilegValidationMixin, BaseModel):
    model_config = {"populate_by_name": True}

    order_type: OrderType = Field(
        ...,
        validation_alias=AliasChoices("order_type", "orderType"),
        serialization_alias="orderType",
        description="The order type. Only LIMIT orders are allowed",
    )
    expiration: OrderExpirationRequest = Field(...)
    quantity: Optional[int] = Field(
        None,
        description="The quantity of the spread. Must be greater than 0",
    )
    limit_price: Decimal = Field(
        ...,
        validation_alias=AliasChoices("limit_price", "limitPrice"),
        serialization_alias="limitPrice",
        description="The limit price for the order",
    )
    legs: List[OrderLegRequest] = Field(
        ...,
        description="From 2-6 legs. There can be at most 1 equity leg",
    )

    @field_validator("order_type")
    @classmethod
    def validate_order_type(cls, v: OrderType) -> OrderType:
        return cls.validate_order_type_limit_only(v)

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("`quantity` must be greater than 0")
        return v

    @model_validator(mode="after")
    def validate_legs(self) -> "PreflightMultiLegRequest":
        self.validate_legs_common()
        return self

    @field_serializer("order_type")
    def serialize_order_type(self, value: OrderType) -> str:
        return value.value

    @field_serializer("quantity")
    def serialize_int(self, value: Optional[int]) -> Optional[str]:
        return str(value) if value is not None else None

    @field_serializer("limit_price")
    def serialize_decimal(self, value: Optional[Decimal]) -> Optional[str]:
        return (
            str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if value is not None
            else None
        )


class OptionDetails(BaseModel):
    base_symbol: str = Field(..., alias="baseSymbol")
    type: OptionType = Field(...)
    strike_price: Decimal = Field(..., alias="strikePrice")
    option_expire_date: str = Field(..., alias="optionExpireDate")


class PreflightLegResponse(BaseModel):
    instrument: OrderInstrument = Field(...)
    side: OrderSide = Field(...)
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        alias="openCloseIndicator",
    )
    ratio_quantity: int = Field(..., alias="ratioQuantity")
    option_details: Optional[OptionDetails] = Field(None, alias="optionDetails")


class PreflightMultiLegResponse(BaseModel):
    base_symbol: str = Field(..., alias="baseSymbol")
    strategy_name: Optional[str] = Field(None, alias="strategyName")
    legs: List[PreflightLegResponse] = Field(...)
    estimated_commission: Optional[Decimal] = Field(None, alias="estimatedCommission")
    regulatory_fees: Optional[RegulatoryFees] = Field(None, alias="regulatoryFees")
    estimated_index_option_fee: Optional[Decimal] = Field(
        None, alias="estimatedIndexOptionFee"
    )
    order_value: Decimal = Field(..., alias="orderValue")
    estimated_quantity: Optional[Decimal] = Field(None, alias="estimatedQuantity")
    estimated_cost: Optional[Decimal] = Field(None, alias="estimatedCost")
    buying_power_requirement: Optional[Decimal] = Field(
        None, alias="buyingPowerRequirement"
    )
    estimated_proceeds: Optional[Decimal] = Field(None, alias="estimatedProceeds")
    margin_requirement: Optional[MarginRequirement] = Field(
        None, alias="marginRequirement"
    )
    margin_impact: Optional[MarginImpact] = Field(None, alias="marginImpact")
    price_increment: Optional[PriceIncrement] = Field(None, alias="priceIncrement")


class MultilegOrderRequest(MultilegValidationMixin, BaseModel):
    model_config = {"populate_by_name": True}

    order_id: str = Field(
        ...,
        validation_alias=AliasChoices("order_id", "orderId"),
        serialization_alias="orderId",
        description=(
            "The OrderId, a UUID conforming to RFC 4122 (8-4-4-4-12 format, "
            "e.g., 0d2abd8d-3625-4c83-a806-98abf35567cc), globally unique over "
            "time. Serves as the deduplication key; if reused on the same "
            "account, the operation is idempotent."
        ),
    )
    quantity: int = Field(
        ...,
        description="The quantity of the spread. Must be greater than 0",
    )
    type: OrderType = Field(
        ..., description="The order type. Only LIMIT order are allowed"
    )
    limit_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("limit_price", "limitPrice"),
        serialization_alias="limitPrice",
        description=(
            "The limit price for the order. For debit spreads the limit price "
            "must be positive, for create spreads the limit price is negative"
        ),
    )
    expiration: OrderExpirationRequest = Field(...)
    legs: List[OrderLegRequest] = Field(
        ..., description="From 2-6 legs. There can be at most 1 equity leg"
    )

    @field_validator("order_id")
    @classmethod
    def validate_order_id_uuid(cls, v: str) -> str:
        try:
            UUID(v, version=4)
        except ValueError as exc:
            raise ValueError(
                f"`order_id` must be a valid UUID conforming to RFC 4122. Got: {v}"
            ) from exc
        return v

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: int) -> int:
        if v <= 0:
            raise ValueError("`quantity` must be greater than 0")
        return v

    @field_validator("type")
    @classmethod
    def validate_order_type(cls, v: OrderType) -> OrderType:
        return cls.validate_order_type_limit_only(v)

    @model_validator(mode="after")
    def validate_legs_and_price(self) -> "MultilegOrderRequest":
        self.validate_legs_common()
        return self

    @field_serializer("type")
    def serialize_order_type(self, value: OrderType) -> str:
        return value.value

    @field_serializer("quantity")
    def serialize_int(self, value: Optional[int]) -> Optional[str]:
        return str(value) if value is not None else None

    @field_serializer("limit_price")
    def serialize_decimal(self, value: Optional[Decimal]) -> Optional[str]:
        return (
            str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if value is not None
            else None
        )


class MultilegOrderResult(BaseModel):
    order_id: str = Field(..., alias="orderId")


class OptionGreeks(BaseModel):
    delta: Decimal = Field(
        ...,
        description=(
            "Delta is the theoretical estimate of how much an option's value "
            "may change given a $1 move UP or DOWN in the underlying security. "
            "The Delta values range from -1 to +1, with 0 representing an "
            "option where the premium barely moves relative to price changes "
            "in the underlying stock."
        ),
    )
    gamma: Decimal = Field(
        ...,
        description=(
            "Gamma represents the rate of change between an option's Delta and "
            "the underlying asset's price. Higher Gamma values indicate that "
            "the Delta could change dramatically with even very small price "
            "changes in the underlying stock or fund."
        ),
    )
    theta: Decimal = Field(
        ...,
        description=(
            "Theta represents the rate of change between the option price and "
            "time, or time sensitivity—sometimes known as an option's time "
            "decay. Theta indicates the amount an option's price would "
            "decrease as the time to expiration decreases, all else equal."
        ),
    )
    vega: Decimal = Field(
        ...,
        description=(
            "Vega measures the amount of increase or decrease in an option "
            "premium based on a 1% change in implied volatility."
        ),
    )
    rho: Decimal = Field(
        ...,
        description=(
            "Rho represents the rate of change between an option's value and "
            "a 1% change in the interest rate. This measures sensitivity to "
            "the interest rate."
        ),
    )
    implied_volatility: Decimal = Field(
        ...,
        alias="impliedVolatility",
        description=(
            "Implied volatility (IV) is a theoretical forecast of how volatile "
            "an underlying stock is expected to be in the future."
        ),
    )
