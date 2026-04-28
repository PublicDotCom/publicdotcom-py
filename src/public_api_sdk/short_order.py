"""Helpers for short-sale order and preflight requests."""

from datetime import datetime
from decimal import Decimal
from typing import Optional
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
