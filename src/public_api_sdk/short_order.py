"""Helpers for short-sale order and preflight requests."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Optional, TYPE_CHECKING
from uuid import uuid4

from .models.instrument_type import InstrumentType
from .models.order import (
    EquityMarketSession,
    OpenCloseIndicator,
    OrderExpirationRequest,
    OrderInstrument,
    OrderRequest,
    OrderSide,
    OrderType,
    PreflightRequest,
    TimeInForce,
)

if TYPE_CHECKING:
    from .models.async_new_order import AsyncNewOrder
    from .models.new_order import NewOrder
    from .models.order import Order
    from .models.portfolio import Portfolio


@dataclass(frozen=True)
class FlattenAndShortResult:
    """Result returned by ``PublicApiClient.flatten_and_go_short``."""

    initial_position_quantity: Decimal
    flatten_order: Optional[NewOrder]
    flatten_filled_order: Optional[Order]
    short_order: NewOrder


@dataclass(frozen=True)
class AsyncFlattenAndShortResult:
    """Result returned by ``AsyncPublicApiClient.flatten_and_go_short``."""

    initial_position_quantity: Decimal
    flatten_order: Optional[AsyncNewOrder]
    flatten_filled_order: Optional[Order]
    short_order: AsyncNewOrder


def _build_short_preflight_request(
    symbol: str,
    quantity: Decimal,
    order_type: OrderType,
    time_in_force: TimeInForce,
    expiration_time: Optional[datetime],
    limit_price: Optional[Decimal],
    stop_price: Optional[Decimal],
    equity_market_session: Optional[EquityMarketSession],
    validate_order: Optional[bool],
) -> PreflightRequest:
    """Build a quantity-only short-sale preflight request.

    Short-sale intent is represented by ``SELL`` plus
    ``openCloseIndicator=OPEN`` in the API.
    """
    return PreflightRequest(
        instrument=OrderInstrument(
            symbol=symbol.strip().upper(),
            type=InstrumentType.EQUITY,
        ),
        order_side=OrderSide.SELL,
        open_close_indicator=OpenCloseIndicator.OPEN,
        order_type=order_type,
        expiration=OrderExpirationRequest(
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        ),
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        equity_market_session=equity_market_session,
        validate_order=validate_order,
    )


def _build_short_order_request(
    symbol: str,
    quantity: Decimal,
    order_type: OrderType,
    time_in_force: TimeInForce,
    expiration_time: Optional[datetime],
    limit_price: Optional[Decimal],
    stop_price: Optional[Decimal],
    equity_market_session: Optional[EquityMarketSession],
    order_id: Optional[str],
) -> OrderRequest:
    """Build a quantity-only short-sale order request.

    Short-sale intent is represented by ``SELL`` plus
    ``openCloseIndicator=OPEN`` in the API. If ``order_id`` is omitted, a
    UUIDv4 idempotency key is generated for the caller.
    """
    return OrderRequest(
        order_id=order_id or str(uuid4()),
        instrument=OrderInstrument(
            symbol=symbol.strip().upper(),
            type=InstrumentType.EQUITY,
        ),
        order_side=OrderSide.SELL,
        open_close_indicator=OpenCloseIndicator.OPEN,
        order_type=order_type,
        expiration=OrderExpirationRequest(
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        ),
        quantity=quantity,
        limit_price=limit_price,
        stop_price=stop_price,
        equity_market_session=equity_market_session,
    )


def _build_flatten_long_order_request(
    symbol: str,
    quantity: Decimal,
    equity_market_session: Optional[EquityMarketSession],
    order_id: Optional[str],
) -> OrderRequest:
    """Build a market order to close an existing long equity position."""
    return OrderRequest(
        order_id=order_id or str(uuid4()),
        instrument=OrderInstrument(
            symbol=symbol.strip().upper(),
            type=InstrumentType.EQUITY,
        ),
        order_side=OrderSide.SELL,
        open_close_indicator=OpenCloseIndicator.CLOSE,
        order_type=OrderType.MARKET,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=quantity,
        equity_market_session=equity_market_session,
    )


def _get_equity_position_quantity(portfolio: Portfolio, symbol: str) -> Decimal:
    """Return the aggregate equity position quantity for ``symbol``."""
    normalized_symbol = symbol.strip().upper()
    quantity = Decimal("0")
    for position in portfolio.positions:
        instrument = position.instrument
        if (
            instrument.symbol.strip().upper() == normalized_symbol
            and instrument.type == InstrumentType.EQUITY
        ):
            quantity += position.quantity
    return quantity
