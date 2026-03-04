"""Async strategy preflight helpers for common vertical spread structures.

Async counterpart to :mod:`strategy_preflight`. All methods are coroutines
and must be ``await``ed.

Usage::

    result = await client.strategy_preflight.credit_spread(
        symbol="AAPL",
        option_type=OptionType.CALL,
        expiration_date="2025-12-19",
        sell_strike=Decimal("190"),
        buy_strike=Decimal("195"),
        quantity=1,
        limit_price=Decimal("2.50"),
    )
"""

from datetime import datetime
from decimal import Decimal
from typing import Awaitable, Callable, Optional

from .models.option import (
    PreflightMultiLegRequest,
    PreflightMultiLegResponse,
)
from .models.order import (
    OptionType,
    TimeInForce,
)
from .strategy_preflight import _build_osi, _make_credit_spread_request, _make_debit_spread_request

AsyncPreflightFunc = Callable[
    [PreflightMultiLegRequest, Optional[str]], Awaitable[PreflightMultiLegResponse]
]


class AsyncStrategyPreflight:
    """Async strategy-level preflight helpers for common vertical spread structures.

    Accessed via ``client.strategy_preflight`` on :class:`AsyncPublicApiClient`.
    Each method is a coroutine that builds the appropriate
    :class:`PreflightMultiLegRequest` and delegates to the client's
    ``perform_multi_leg_preflight_calculation``.
    """

    def __init__(self, preflight_func: AsyncPreflightFunc) -> None:
        self._preflight = preflight_func

    async def credit_spread(
        self,
        symbol: str,
        option_type: OptionType,
        expiration_date: str,
        sell_strike: Decimal,
        buy_strike: Decimal,
        quantity: int,
        limit_price: Decimal,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Estimate the cost/impact of a vertical credit spread.

        Sells the closer-to-the-money option and buys the further
        out-of-the-money option as protection.

        - **CALL credit spread (Bear Call Spread):** ``sell_strike < buy_strike``
          Profits if the underlying stays *below* ``sell_strike`` at expiry.
        - **PUT credit spread (Bull Put Spread):** ``sell_strike > buy_strike``
          Profits if the underlying stays *above* ``sell_strike`` at expiry.

        Args:
            symbol: Underlying ticker symbol (e.g. ``"AAPL"``).
            option_type: ``OptionType.CALL`` or ``OptionType.PUT``.
            expiration_date: Option expiration date as ``"YYYY-MM-DD"``.
            sell_strike: The strike to sell (generates the credit).
            buy_strike: The strike to buy (caps maximum loss).
            quantity: Number of spread contracts.
            limit_price: Minimum net credit to accept (positive value,
                e.g. ``Decimal("2.50")`` for a $2.50 per-share credit).
            time_in_force: ``DAY`` or ``GTD`` (default ``DAY``).
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Returns:
            :class:`PreflightMultiLegResponse` with estimated credit,
            commission, and buying power impact.
        """
        request = _make_credit_spread_request(
            symbol=symbol,
            option_type=option_type,
            expiration_date=expiration_date,
            sell_strike=sell_strike,
            buy_strike=buy_strike,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        )
        return await self._preflight(request, account_id)

    async def debit_spread(
        self,
        symbol: str,
        option_type: OptionType,
        expiration_date: str,
        buy_strike: Decimal,
        sell_strike: Decimal,
        quantity: int,
        limit_price: Decimal,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Estimate the cost/impact of a vertical debit spread.

        Buys the closer-to-the-money option and sells the further
        out-of-the-money option to offset the net cost.

        - **CALL debit spread (Bull Call Spread):** ``buy_strike < sell_strike``
          Profits if the underlying rises *above* ``sell_strike`` at expiry.
        - **PUT debit spread (Bear Put Spread):** ``buy_strike > sell_strike``
          Profits if the underlying falls *below* ``sell_strike`` at expiry.

        Args:
            symbol: Underlying ticker symbol (e.g. ``"AAPL"``).
            option_type: ``OptionType.CALL`` or ``OptionType.PUT``.
            expiration_date: Option expiration date as ``"YYYY-MM-DD"``.
            buy_strike: The strike to buy (main directional position).
            sell_strike: The strike to sell (reduces net cost).
            quantity: Number of spread contracts.
            limit_price: Maximum net debit to pay (positive value,
                e.g. ``Decimal("3.00")`` for a $3.00 per-share debit).
            time_in_force: ``DAY`` or ``GTD`` (default ``DAY``).
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Returns:
            :class:`PreflightMultiLegResponse` with estimated cost,
            commission, and buying power impact.
        """
        request = _make_debit_spread_request(
            symbol=symbol,
            option_type=option_type,
            expiration_date=expiration_date,
            buy_strike=buy_strike,
            sell_strike=sell_strike,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        )
        return await self._preflight(request, account_id)
