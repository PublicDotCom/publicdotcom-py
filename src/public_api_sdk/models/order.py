from datetime import datetime, timezone, timedelta
from decimal import Decimal, ROUND_HALF_UP
from enum import Enum
from typing import List, Optional
from uuid import UUID

from pydantic import (
    AliasChoices,
    BaseModel,
    Field,
    ValidationInfo,
    field_serializer,
    field_validator,
    model_validator,
)

from .instrument_type import InstrumentType


class OrderValidationMixin:
    """Mixin class for shared validations between OrderRequest and PreflightRequest."""

    @field_validator("quantity")
    @classmethod
    def validate_quantity(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None and v <= 0:
            raise ValueError("`quantity` must be greater than 0")
        return v

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, v: Optional[Decimal]) -> Optional[Decimal]:
        if v is not None:
            if v <= 0:
                raise ValueError("amount must be greater than 0")
            # check for more than 2 decimal places
            exponent = v.as_tuple().exponent
            if isinstance(exponent, int) and exponent < -2:
                raise ValueError("`amount` cannot have more than 2 decimal places")
        return v

    @field_validator("limit_price")
    @classmethod
    def validate_limit_price(
        cls, v: Optional[Decimal], info: ValidationInfo
    ) -> Optional[Decimal]:
        if v is not None and info.data.get("order_type"):
            order_type = info.data["order_type"]
            if order_type not in [OrderType.LIMIT, OrderType.STOP_LIMIT]:
                raise ValueError(
                    f"`limit_price` can only be set for `LIMIT` or `STOP_LIMIT` orders, "
                    f"not {order_type.value}"
                )
        return v

    @field_validator("stop_price")
    @classmethod
    def validate_stop_price(
        cls, v: Optional[Decimal], info: ValidationInfo
    ) -> Optional[Decimal]:
        if v is not None and info.data.get("order_type"):
            order_type = info.data["order_type"]
            if order_type not in [OrderType.STOP, OrderType.STOP_LIMIT]:
                raise ValueError(
                    f"`stop_price` can only be set for `STOP` or `STOP_LIMIT` orders, "
                    f"not {order_type.value}"
                )
        return v

    @model_validator(mode="after")
    def validate_quantity_or_amount(self) -> "OrderValidationMixin":
        if hasattr(self, "quantity") and hasattr(self, "amount"):
            if self.quantity is not None and self.amount is not None:
                raise ValueError(
                    "Only one of `quantity` or `amount` can be specified, not both"
                )
            if self.quantity is None and self.amount is None:
                raise ValueError("Either `quantity` or `amount` must be specified")
        return self


class OrderInstrument(BaseModel):
    symbol: str = Field(...)
    type: InstrumentType = Field(...)

    @field_serializer("type")
    def serialize_type(self, value: InstrumentType) -> str:
        return value.value


class OrderSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(str, Enum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"
    STOP = "STOP"
    STOP_LIMIT = "STOP_LIMIT"


class TimeInForce(str, Enum):
    DAY = "DAY"
    GTD = "GTD"


class OpenCloseIndicator(str, Enum):
    OPEN = "OPEN"
    CLOSE = "CLOSE"


class OrderExpiration(BaseModel):
    time_in_force: TimeInForce = Field(..., alias="timeInForce")
    expiration_time: Optional[datetime] = Field(None, alias="expirationTime")


class OrderExpirationRequest(BaseModel):
    model_config = {"populate_by_name": True}
    time_in_force: TimeInForce = Field(
        ...,
        validation_alias=AliasChoices("time_in_force", "timeInForce"),
        serialization_alias="timeInForce",
        description="The time in for the order",
    )
    expiration_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("expiration_time", "expirationTime"),
        serialization_alias="expirationTime",
        description=(
            "The expiration date (UTC). Only used when timeInForce is `GTD`, "
            "cannot be more than 90 days in the future"
        ),
    )

    @model_validator(mode="after")
    def validate_expiration_time(self) -> "OrderExpirationRequest":
        if self.time_in_force == TimeInForce.GTD:
            if self.expiration_time is None:
                raise ValueError(
                    "`expiration_time` is required when `time_in_force` is GTD"
                )
            # check if `expiration_time`` is more than 90 days in the future
            max_future = datetime.now(timezone.utc) + timedelta(days=90)
            # ensure `expiration_time`` has timezone info, default to UTC if naive
            exp_time = self.expiration_time
            # pylint: disable=no-member
            if exp_time.tzinfo is None:
                exp_time = exp_time.replace(tzinfo=timezone.utc)
            if exp_time > max_future:
                raise ValueError(
                    "`expiration_time` cannot be more than 90 days in the future"
                )
        elif self.time_in_force == TimeInForce.DAY:
            if self.expiration_time is not None:
                raise ValueError(
                    "`expiration_time` should not be provided when `time_in_force` is DAY"
                )
        return self

    @field_serializer("time_in_force")
    def serialize_status(self, value: TimeInForce) -> str:
        return value.value

    @field_serializer("expiration_time")
    def serialize_expiration(self, value: Optional[datetime]) -> Optional[str]:
        return (
            value.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            if value
            else None
        )


class PreflightRequest(OrderValidationMixin, BaseModel):
    model_config = {"populate_by_name": True}
    instrument: OrderInstrument = Field(...)
    order_side: OrderSide = Field(
        ...,
        validation_alias=AliasChoices("order_side", "orderSide"),
        serialization_alias="orderSide",
        description=(
            "The Order Side BUY/SELL. For Options also include the `openCloseIndicator`."
        ),
    )
    order_type: OrderType = Field(
        ...,
        validation_alias=AliasChoices("order_type", "orderType"),
        serialization_alias="orderType",
        description="The Type of order",
    )
    expiration: OrderExpirationRequest = Field(
        ..., alias="expiration", description="Expiration date"
    )
    quantity: Optional[Decimal] = Field(
        None,
        description=(
            "The order quantity. Used when buying/selling whole shares (e.g., Decimal(10)) and when selling fractional. (e.g., Decimal(0.12345)). Mutually exclusive with `amount`"
        ),
    )
    amount: Optional[Decimal] = Field(
        None,
        description=(
            "The order amount. Used when buying/selling shares for a specific notional value"
        ),
    )
    limit_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("limit_price", "limitPrice"),
        serialization_alias="limitPrice",
        description="The limit price. Used when `orderType = LIMIT` or `orderType = STOP_LIMIT`",
    )
    stop_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("stop_price", "stopPrice"),
        serialization_alias="stopPrice",
        description="The stop price. Used when `orderType = STOP` or `orderType = STOP_LIMIT`",
    )
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        validation_alias=AliasChoices("open_close_indicator", "openCloseIndicator"),
        serialization_alias="openCloseIndicator",
        description="Used for options only. Indicates if this is BUY to OPEN/CLOSE",
    )

    @field_serializer("order_side")
    def serialize_order_side(self, value: OrderSide) -> str:
        return value.value

    @field_serializer("order_type")
    def serialize_order_type(self, value: OrderType) -> str:
        return value.value

    @field_serializer("quantity")
    def serialize_quantity(self, value: Optional[Decimal]) -> Optional[str]:
        return (
            str(value.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))
            if value is not None
            else None
        )

    @field_serializer("amount", "limit_price", "stop_price")
    def serialize_decimal(self, value: Optional[Decimal]) -> Optional[str]:
        return (
            str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if value is not None
            else None
        )

    @field_serializer("open_close_indicator")
    def serialize_open_close_indicator(
        self, value: Optional[OpenCloseIndicator]
    ) -> Optional[str]:
        return value.value if value else None


class RegulatoryFees(BaseModel):
    sec_fee: Optional[Decimal] = Field(None, alias="secFee")
    taf_fee: Optional[Decimal] = Field(None, alias="tafFee")
    orf_fee: Optional[Decimal] = Field(None, alias="orfFee")
    exchange_fee: Optional[Decimal] = Field(None, alias="exchangeFee")
    occ_fee: Optional[Decimal] = Field(None, alias="occFee")
    cat_fee: Optional[Decimal] = Field(None, alias="catFee")


class OptionType(str, Enum):
    CALL = "CALL"
    PUT = "PUT"


class OptionDetails(BaseModel):
    base_symbol: str = Field(..., alias="baseSymbol")
    type: OptionType = Field(..., alias="type")
    strike_price: Decimal = Field(..., alias="strikePrice")
    option_expire_date: datetime = Field(..., alias="optionExpireDate")


class OptionRebate(BaseModel):
    estimated_option_rebate: Optional[Decimal] = Field(
        None, alias="estimatedOptionRebate"
    )
    option_rebate_percent: Optional[int] = Field(None, alias="optionRebatePercent")
    per_contract_rebate: Optional[Decimal] = Field(None, alias="perContractRebate")


class MarginRequirement(BaseModel):
    long_maintenance_requirement: Optional[Decimal] = Field(
        None, alias="longMaintenanceRequirement"
    )
    long_initial_requirement: Optional[Decimal] = Field(
        None, alias="longInitialRequirement"
    )


class MarginImpact(BaseModel):
    margin_usage_impact: Optional[str] = Field(None, alias="marginUsageImpact")
    initial_margin_requirement: Optional[Decimal] = Field(
        None, alias="initialMarginRequirement"
    )


class PriceIncrement(BaseModel):
    increment_below_3: Optional[Decimal] = Field(None, alias="incrementBelow3")
    increment_above_3: Optional[Decimal] = Field(None, alias="incrementAbove3")
    current_increment: Optional[Decimal] = Field(None, alias="currentIncrement")


class PreflightResponse(BaseModel):
    instrument: OrderInstrument = Field(...)
    cusip: Optional[str] = Field(None)
    root_symbol: Optional[str] = Field(None, alias="rootSymbol")
    root_option_symbol: Optional[str] = Field(None, alias="rootOptionSymbol")
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
    option_details: Optional[OptionDetails] = Field(None, alias="optionDetails")
    estimated_order_rebate: Optional[OptionRebate] = Field(
        None, alias="estimatedOrderRebate"
    )
    margin_requirement: Optional[MarginRequirement] = Field(
        None, alias="marginRequirement"
    )
    margin_impact: Optional[MarginImpact] = Field(None, alias="marginImpact")
    price_increment: Optional[PriceIncrement] = Field(None, alias="priceIncrement")


class OrderRequest(OrderValidationMixin, BaseModel):
    model_config = {"populate_by_name": True}

    order_id: str = Field(
        ...,
        validation_alias=AliasChoices("order_id", "orderId"),
        serialization_alias="orderId",
        description=(
            "The OrderId, a UUID conforming to RFC 4122 (standard 8-4-4-4-12 format, "
            "e.g., 0d2abd8d-3625-4c83-a806-98abf35567cc), must be globally unique over time.\n\n"
            "This value serves as the deduplication key; if reused on the same account, "
            "the operation is idempotent.\n\n"
            "If the order is re-submitted due to a read timeout, do not modify any properties. "
            "If the original request succeeded, altering fields will have no effect."
        ),
    )

    @field_validator("order_id")
    @classmethod
    def validate_order_id_uuid(cls, v: str) -> str:
        try:
            UUID(v, version=4)
        except ValueError as exc:
            raise ValueError(
                f"order_id must be a valid UUID conforming to RFC 4122. Got: {v}"
            ) from exc
        return v

    instrument: OrderInstrument = Field(...)
    order_side: OrderSide = Field(
        ...,
        validation_alias=AliasChoices("order_side", "orderSide"),
        serialization_alias="orderSide",
        description="The Order Side BUY/SELL. For Options also include the `openCloseIndicator`.",
    )
    order_type: OrderType = Field(
        ...,
        validation_alias=AliasChoices("order_type", "orderType"),
        serialization_alias="orderType",
        description="The Type of order",
    )
    expiration: OrderExpirationRequest = Field(
        ..., alias="expiration", description="Expiration date"
    )
    quantity: Optional[Decimal] = Field(
        None,
        description=(
            "The order quantity. Used when buying/selling whole shares (e.g., Decimal(10)) and when selling fractional. (e.g., Decimal(0.12345)). Mutually exclusive with `amount`"
        ),
    )

    amount: Optional[Decimal] = Field(
        None,
        description=(
            "The order amount. Used when buying/selling shares for a specific notional value"
        ),
    )
    limit_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("limit_price", "limitPrice"),
        serialization_alias="limitPrice",
        description="The limit price. Used when `orderType = LIMIT` or `orderType = STOP_LIMIT`",
    )
    stop_price: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("stop_price", "stopPrice"),
        serialization_alias="stopPrice",
        description="The stop price. Used when `orderType = STOP` or `orderType = STOP_LIMIT`",
    )
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        validation_alias=AliasChoices("open_close_indicator", "openCloseIndicator"),
        serialization_alias="openCloseIndicator",
        description="Used for options only. Indicates if this is BUY to OPEN/CLOSE",
    )

    @field_serializer("order_side")
    def serialize_order_side(self, value: OrderSide) -> str:
        return value.value

    @field_serializer("order_type")
    def serialize_order_type(self, value: OrderType) -> str:
        return value.value

    @field_serializer("quantity")
    def serialize_quantity(self, value: Optional[Decimal]) -> Optional[str]:
        return (
            str(value.quantize(Decimal("0.00001"), rounding=ROUND_HALF_UP))
            if value is not None
            else None
        )

    @field_serializer("amount", "limit_price", "stop_price")
    def serialize_decimal(self, value: Optional[Decimal]) -> Optional[str]:
        return (
            str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
            if value is not None
            else None
        )

    @field_serializer("open_close_indicator")
    def serialize_open_close_indicator(
        self, value: Optional[OpenCloseIndicator]
    ) -> Optional[str]:
        return value.value if value else None


class OrderResponse(BaseModel):
    order_id: str = Field(..., alias="orderId")


class OrderStatus(str, Enum):
    NEW = "NEW"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    QUEUED_CANCELLED = "QUEUED_CANCELLED"
    FILLED = "FILLED"
    REJECTED = "REJECTED"
    PENDING_REPLACE = "PENDING_REPLACE"
    PENDING_CANCEL = "PENDING_CANCEL"
    EXPIRED = "EXPIRED"
    REPLACED = "REPLACED"


class LegInstrumentType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"


class LegInstrument(BaseModel):
    symbol: str = Field(...)
    type: LegInstrumentType = Field(...)


class OrderLeg(BaseModel):
    instrument: LegInstrument = Field(...)
    side: OrderSide = Field(...)
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        alias="openCloseIndicator",
        description=(
            "Present if instrument.type = OPTION, used to determine if the leg is "
            "buy-to-open or buy-to-close"
        ),
    )
    ratio_quantity: Optional[int] = Field(
        None,
        alias="ratioQuantity",
        description=(
            "The ratio between legs. Equity legs will typically be 100 shares, "
            "and option legs 1 contract"
        ),
    )


class Order(BaseModel):
    model_config = {"populate_by_name": True}

    order_id: str = Field(
        ...,
        validation_alias=AliasChoices("order_id", "orderId"),
        serialization_alias="orderId",
    )
    instrument: OrderInstrument = Field(...)
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    type: OrderType = Field(...)
    side: OrderSide = Field(...)
    status: OrderStatus = Field(...)
    quantity: Optional[Decimal] = Field(
        None,
        description="Quantity of the order, mutually exclusive with notional value",
    )
    notional_value: Optional[Decimal] = Field(
        None,
        alias="notionalValue",
        description="Notional value (dollar amount) of the order, mutually exclusive with quantity",
    )
    expiration: Optional[OrderExpiration] = Field(None)
    limit_price: Optional[Decimal] = Field(None, alias="limitPrice")
    stop_price: Optional[Decimal] = Field(None, alias="stopPrice")
    closed_at: Optional[datetime] = Field(
        None,
        alias="closedAt",
        description=(
            "The time the order reached a terminal state, like CANCELLED, FILLED, "
            "REJECTED, REPLACED"
        ),
    )
    open_close_indicator: Optional[OpenCloseIndicator] = Field(
        None,
        alias="openCloseIndicator",
        description="Present if the order is a single-leg option order",
    )
    filled_quantity: Optional[Decimal] = Field(
        None,
        alias="filledQuantity",
        description="The filled quantity of the order, present if the order had at least one trade",
    )
    average_price: Optional[Decimal] = Field(
        None,
        alias="averagePrice",
        description="The average price per unit, present if the order had at least one trade",
    )
    legs: Optional[List[OrderLeg]] = Field(
        None,
        alias="legs",
        description="If instrument.type = MULTI_LEG_INSTRUMENT, this contains the list of legs",
    )
    reject_reason: Optional[str] = Field(None, alias="rejectReason")
