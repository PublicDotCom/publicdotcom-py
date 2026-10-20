"""Helpers for trading recurring event-contract markets (e.g. 15-minute windows).

Shared by :class:`PublicApiClient` and :class:`AsyncPublicApiClient`: building
the requests and picking results, with no I/O of their own.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import ROUND_CEILING, Decimal
from typing import Iterable, Optional, Union
from uuid import uuid4

from .models.event_contract import (
    EventContract,
    EventDetails,
    EventFrequency,
    EventOutcome,
    EventOutcomeState,
    EventSortingMode,
    EventSummary,
    EventSummaryFilters,
    EventSummaryRequest,
)
from .models.instrument_type import InstrumentType
from .models.order import (
    OrderExpirationRequest,
    OrderInstrument,
    OrderRequest,
    OrderSide,
    OrderType,
    PreflightRequest,
    TimeInForce,
)

_CENT = Decimal("0.01")

DEFAULT_EVENT_POLL_INTERVAL = 30.0
"""Seconds between checks in ``wait_for_current_event``."""

DEFAULT_SETTLEMENT_POLL_INTERVAL = 20.0
"""Seconds between checks in ``wait_for_settlement``."""


# --- Current event ----------------------------------------------------------


def _normalize_series(series: str) -> str:
    if not series or not series.strip():
        raise ValueError("series is required")
    return series.strip().upper()


def _build_current_event_request(
    frequency: EventFrequency,
    category: Optional[str],
    subcategory: Optional[str],
) -> EventSummaryRequest:
    """Open events of one frequency, soonest expiration first."""
    return EventSummaryRequest(
        sorting_mode=EventSortingMode.EXPIRATION,
        category=category,
        subcategory=subcategory,
        display_resolved_events=False,
        filters=EventSummaryFilters(frequencies=[frequency]),
    )


def _pick_current_event(
    events: Iterable[EventSummary], series: str, now: datetime
) -> Optional[EventSummary]:
    """The unresolved event of ``series`` that resolves soonest after ``now``.

    Events whose resolution time has passed are skipped: the API keeps listing
    a window as unresolved for a few minutes after it closes.
    """
    candidates = [
        event
        for event in events
        if event.series == series
        and not event.resolved
        and event.resolution_time is not None
        and _as_utc(event.resolution_time) > now
    ]
    return min(candidates, key=lambda e: _as_utc(e.resolution_time), default=None)


def _as_utc(value: Optional[datetime]) -> datetime:
    assert value is not None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --- Buying contracts -------------------------------------------------------


def _event_contract_limit_price(
    contract: Union[EventContract, str],
    limit_price: Optional[Union[Decimal, float, str]],
) -> Decimal:
    """The limit price for buying ``contract``.

    An explicit ``limit_price`` must be in whole cents. Without one, the
    contract's ask is used, rounded *up* to a whole cent: asks can carry
    tenths of a cent but orders are priced in cents, and rounding down would
    price the order below the ask.
    """
    if limit_price is not None:
        price = Decimal(str(limit_price))
        if price != price.quantize(_CENT):
            raise ValueError(f"limit_price must be in whole cents, got {price}")
    elif isinstance(contract, str):
        raise ValueError("limit_price is required when contract is a symbol")
    elif contract.ask is None:
        raise ValueError(f"{contract.symbol} has no ask; pass limit_price")
    else:
        price = contract.ask.quantize(_CENT, rounding=ROUND_CEILING)
    if not Decimal("0") < price < Decimal("1"):
        raise ValueError(f"limit_price must be between 0.01 and 0.99, got {price}")
    return price


def _event_contract_quantity(quantity: Union[Decimal, int]) -> Decimal:
    """``quantity`` as a Decimal; the API takes at most 2 decimal places."""
    value = Decimal(quantity)
    if value != value.quantize(_CENT):
        raise ValueError(f"quantity can have at most 2 decimal places, got {value}")
    return value


def _event_contract_symbol(contract: Union[EventContract, str]) -> str:
    symbol = contract if isinstance(contract, str) else contract.symbol
    if not symbol or not symbol.strip():
        raise ValueError("contract symbol is required")
    return symbol.strip()


def _build_event_contract_buy_preflight(
    contract: Union[EventContract, str],
    quantity: Union[Decimal, int],
    limit_price: Optional[Union[Decimal, float, str]],
) -> PreflightRequest:
    return PreflightRequest(
        instrument=OrderInstrument(
            symbol=_event_contract_symbol(contract),
            type=InstrumentType.EVENTCONTRACT,
        ),
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        limit_price=_event_contract_limit_price(contract, limit_price),
        quantity=_event_contract_quantity(quantity),
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
    )


def _build_event_contract_buy_order(
    contract: Union[EventContract, str],
    quantity: Union[Decimal, int],
    limit_price: Optional[Union[Decimal, float, str]],
    order_id: Optional[str],
) -> OrderRequest:
    """A DAY limit buy; ``order_id`` defaults to a fresh UUIDv4."""
    return OrderRequest(
        order_id=order_id or str(uuid4()),
        instrument=OrderInstrument(
            symbol=_event_contract_symbol(contract),
            type=InstrumentType.EVENTCONTRACT,
        ),
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        limit_price=_event_contract_limit_price(contract, limit_price),
        quantity=_event_contract_quantity(quantity),
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
    )


# --- Settlement -------------------------------------------------------------


def _settlement_outcome(
    details: EventDetails, outcome_id: Optional[str]
) -> EventOutcome:
    """The outcome to watch: ``outcome_id``, or the event's only outcome."""
    if outcome_id is None:
        if details.outcome is None:
            raise ValueError(
                f"{details.event_symbol} has {len(details.outcomes)} outcomes; "
                "pass outcome_id"
            )
        return details.outcome
    for outcome in details.outcomes:
        if outcome.outcome_id == outcome_id:
            return outcome
    raise ValueError(f"{details.event_symbol} has no outcome {outcome_id!r}")


def _is_settled(outcome: EventOutcome) -> bool:
    return outcome.state == EventOutcomeState.STATE_SETTLED
