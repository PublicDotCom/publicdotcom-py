"""Models for the account WebSocket stream (order and trade channels).

The stream pushes the state of a user's orders and trades as they change. Its
payloads differ from the REST shapes: a streamed order carries ``version``,
``accountNumber``, ``effective``/``editable``/``cancellable`` and the
request-side ``session`` vocabulary, and has no ``trades``; a streamed trade
carries ``orderId``, ``accountNumber`` and a ``status``. They therefore get
their own models rather than reusing :class:`~public_api_sdk.models.order.Order`
and :class:`~public_api_sdk.models.order.Trade`.

The API adds fields, enum values, event types and channels without notice, so
these models are deliberately tolerant: unknown fields are ignored, and an
enum value the SDK does not know yet is kept as its raw string instead of
failing validation.
"""

import logging
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Union

from pydantic import BaseModel, Field

# Enum fields that keep an unrecognised value as the raw string; shared with
# the REST response models.
from ._lenient import (
    LenientInstrumentType,
    LenientLegInstrumentType,
    LenientMarketSession,
    LenientOpenCloseIndicator,
    LenientOrderSide,
    LenientOrderType,
    LenientTimeInForce,
)
from .order import OrderStatus, TrailingStop


class StreamChannel(str, Enum):
    """A channel of the account stream."""

    ORDER = "order"
    """The complete state of an order every time it changes."""
    TRADE = "trade"
    """Each execution (fill) of an order, and its cancellation if taken back."""

    def __str__(self) -> str:
        return str(self.value)


class TradeStatus(str, Enum):
    """The status of a streamed trade."""

    NEW = "NEW"
    """The trade was recorded."""
    CANCELLED = "CANCELLED"
    """The trade was taken back: it did not happen, reverse its effect."""
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API statuses

    @classmethod
    def _missing_(cls, value: object) -> "TradeStatus":
        logging.getLogger(__name__).warning(
            "Unrecognised TradeStatus %r — defaulting to UNKNOWN. "
            "Update the SDK to get the correct status name.",
            value,
        )
        return cls.UNKNOWN

    def __str__(self) -> str:
        return str(self.value)


class StreamInstrument(BaseModel):
    """The instrument of a streamed order or trade.

    ``symbol`` is the plain symbol, with no suffix (``BTC``, not ``BTC-CRYPTO``).
    """

    symbol: str = Field(...)
    type: LenientInstrumentType = Field(...)


class StreamOrderExpiration(BaseModel):
    model_config = {"populate_by_name": True}

    time_in_force: Optional[LenientTimeInForce] = Field(
        None, alias="timeInForce"
    )
    expiration_time: Optional[datetime] = Field(
        None,
        alias="expirationTime",
        description="Set when time_in_force is GTD",
    )


StreamTrailingStop = TrailingStop
"""The trail of a streamed trailing stop order; the same model as the REST
:class:`~public_api_sdk.models.order.TrailingStop`."""


class StreamLegInstrument(BaseModel):
    symbol: str = Field(...)
    type: LenientLegInstrumentType = Field(...)


class StreamOrderLeg(BaseModel):
    model_config = {"populate_by_name": True}

    instrument: StreamLegInstrument = Field(...)
    side: LenientOrderSide = Field(...)
    open_close_indicator: Optional[LenientOpenCloseIndicator] = Field(
        None, alias="openCloseIndicator"
    )
    ratio_quantity: Optional[int] = Field(
        None, alias="ratioQuantity"
    )


class StreamOrder(BaseModel):
    """An order as pushed on the ``order`` channel.

    This is the complete order after a change, not a difference with the
    previous event. ``version`` increases with every change: keep the order
    with the highest version per ``order_id``. The stream already drops events
    whose version is not newer than one it delivered (see the
    ``deduplicate`` option of the stream).
    """

    model_config = {"populate_by_name": True}

    order_id: str = Field(..., alias="orderId")
    account_number: str = Field(..., alias="accountNumber")
    version: int = Field(..., description="Increases with every change of the order")
    instrument: StreamInstrument = Field(...)
    type: LenientOrderType = Field(...)
    side: LenientOrderSide = Field(...)
    status: OrderStatus = Field(...)
    quantity: Optional[Decimal] = Field(
        None, description="For orders placed by quantity; exclusive with notional_value"
    )
    notional_value: Optional[Decimal] = Field(
        None,
        alias="notionalValue",
        description="For orders placed by amount; exclusive with quantity",
    )
    expiration: Optional[StreamOrderExpiration] = Field(None)
    limit_price: Optional[Decimal] = Field(None, alias="limitPrice")
    stop_price: Optional[Decimal] = Field(None, alias="stopPrice")
    trailing_stop: Optional[StreamTrailingStop] = Field(
        None, alias="trailingStop"
    )
    high_watermark: Optional[Decimal] = Field(
        None,
        alias="highWatermark",
        description="The best price a trailing stop currently trails",
    )
    session: Optional[LenientMarketSession] = Field(
        None, description="For equity orders: CORE, EXTENDED or TWENTY_FOUR_HOURS"
    )
    open_close_indicator: Optional[LenientOpenCloseIndicator] = Field(
        None, alias="openCloseIndicator"
    )
    filled_quantity: Optional[Decimal] = Field(
        None, alias="filledQuantity"
    )
    average_price: Optional[Decimal] = Field(
        None, alias="averagePrice"
    )
    fees: Optional[Decimal] = Field(
        None, description="Fees charged on the order's executions so far"
    )
    commission: Optional[Decimal] = Field(
        None, description="Commission charged on the order's executions so far"
    )
    rebate: Optional[Decimal] = Field(
        None, description="Rebate paid on the order's executions so far"
    )
    legs: Optional[List[StreamOrderLeg]] = Field(None)
    bracket_id: Optional[str] = Field(
        None,
        alias="bracketId",
        description="For bracket orders: the order_id of the entry order",
    )
    reject_reason: Optional[str] = Field(
        None, alias="rejectReason"
    )
    effective: Optional[bool] = Field(
        None,
        description=(
            "Whether the order is working. False while it waits for another "
            "order to fill, like the exits of a bracket before the entry fills."
        ),
    )
    editable: Optional[bool] = Field(None)
    cancellable: Optional[bool] = Field(None)
    created_at: Optional[datetime] = Field(None, alias="createdAt")
    last_modified: Optional[datetime] = Field(
        None, alias="lastModified"
    )
    edited_at: Optional[datetime] = Field(None, alias="editedAt")

    @property
    def is_final(self) -> bool:
        """True when the order reached a final status (filled, cancelled,
        rejected or expired) and will not change again."""
        return self.status in _FINAL_ORDER_STATUSES


_FINAL_ORDER_STATUSES = frozenset(
    {
        OrderStatus.FILLED,
        OrderStatus.CANCELLED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }
)


class StreamTrade(BaseModel):
    """A trade (one execution) as pushed on the ``trade`` channel.

    A trade is published with status ``NEW`` when it is recorded, and again
    with the same ``trade_id`` and status ``CANCELLED`` if it is taken back.
    Keep the latest frame per ``trade_id``.
    """

    model_config = {"populate_by_name": True}

    trade_id: str = Field(..., alias="tradeId")
    order_id: Optional[str] = Field(
        None,
        alias="orderId",
        description="None for trades without an order, like allocations",
    )
    original_trade_id: Optional[str] = Field(
        None,
        alias="originalTradeId",
        description="The trade this trade corrects, if it is a correction",
    )
    account_number: str = Field(..., alias="accountNumber")
    status: TradeStatus = Field(...)
    instrument: StreamInstrument = Field(...)
    quantity: Decimal = Field(..., description="Quantity traded; side gives the direction")
    price: Decimal = Field(..., description="Price per share or contract")
    side: LenientOrderSide = Field(...)
    timestamp: datetime = Field(..., description="When the trade happened")
    market_identification_code: Optional[str] = Field(
        None,
        alias="marketIdentificationCode",
        description="ISO 10383 MIC of the execution venue, if reported",
    )
    fees: Optional[Decimal] = Field(None, description="Fees charged on this trade")
    commission: Optional[Decimal] = Field(
        None, description="Commission charged on this trade"
    )
    rebate: Optional[Decimal] = Field(None, description="Rebate paid on this trade")


class OrderUpdateEvent(BaseModel):
    """An ``ORDER_UPDATE`` frame of the ``order`` channel."""

    channel: str = Field(StreamChannel.ORDER.value)
    type: str = Field("ORDER_UPDATE")
    timestamp: Optional[datetime] = Field(
        None,
        description=(
            "When the frame was sent. Not when the order changed: that is "
            "order.last_modified."
        ),
    )
    order: StreamOrder = Field(...)


class TradeEvent(BaseModel):
    """A ``TRADE`` frame of the ``trade`` channel."""

    channel: str = Field(StreamChannel.TRADE.value)
    type: str = Field("TRADE")
    timestamp: Optional[datetime] = Field(
        None,
        description=(
            "When the frame was sent. Not when the trade happened: that is "
            "trade.timestamp."
        ),
    )
    trade: StreamTrade = Field(...)


class StreamConnectedEvent(BaseModel):
    """The stream connected, for the first time or after a reconnect.

    Nothing is replayed after a disconnect, so this is the moment to load the
    current state from the REST API (``get_portfolio`` for open orders,
    ``search_orders`` for recent orders and their trades). Events that arrive
    while you load it are held for you and delivered afterwards.
    """

    account_ids: List[str] = Field(..., description="The accountIds subscribed to")
    channels: List[str] = Field(..., description="The channels subscribed to")
    is_reconnect: bool = Field(
        ..., description="False on the first connect, True on every later one"
    )
    connected_at: datetime = Field(...)


class StreamDisconnectedEvent(BaseModel):
    """The connection closed or a connection attempt failed.

    Connections are closed routinely (after 10 idle minutes, after 2 hours at
    the latest, on deployments), so this is normal; the stream reconnects on
    its own unless ``will_reconnect`` is False.
    """

    close_code: Optional[int] = Field(
        None, description="The WebSocket close code, if the connection was open"
    )
    reason: str = Field("", description="Close reason or error description")
    status_code: Optional[int] = Field(
        None, description="The HTTP status of a rejected handshake"
    )
    will_reconnect: bool = Field(...)
    reconnect_in: Optional[float] = Field(
        None, description="Seconds until the next connection attempt"
    )


StreamEvent = Union[
    OrderUpdateEvent, TradeEvent, StreamConnectedEvent, StreamDisconnectedEvent
]
"""Everything an async stream yields."""
