"""Strategy preflight helpers for common vertical spread structures.

Wraps ``perform_multi_leg_preflight_calculation`` so callers describe a
strategy in financial terms (symbol, strikes, direction) rather than
building ``PreflightMultiLegRequest`` and OSI symbols by hand.

Usage::

    result = client.strategy_preflight.credit_spread(
        symbol="AAPL",
        option_type=OptionType.CALL,        # Bear Call Spread
        expiration_date="2025-12-19",
        sell_strike=Decimal("190"),
        buy_strike=Decimal("195"),
        quantity=1,
        limit_price=Decimal("2.50"),
    )
    print(f"Net credit: ${result.estimated_cost}")
"""

import re
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal
from enum import Enum
from typing import Callable, Optional, Tuple
from uuid import uuid4

from .models.option import (
    LegInstrument,
    LegInstrumentType,
    MultilegOrderRequest,
    OrderLegRequest,
    PreflightMultiLegRequest,
    PreflightMultiLegResponse,
)
from .models.order import (
    OpenCloseIndicator,
    OrderExpirationRequest,
    OrderSide,
    OrderType,
    OptionType,
    TimeInForce,
)

PreflightFunc = Callable[
    [PreflightMultiLegRequest, Optional[str]], PreflightMultiLegResponse
]


def _build_osi(
    symbol: str,
    expiration_date: str,
    option_type: OptionType,
    strike: Decimal,
) -> str:
    """Build an OSI-format option symbol.

    Args:
        symbol: Underlying ticker (e.g. "AAPL")
        expiration_date: Expiration in "YYYY-MM-DD" format
        option_type: OptionType.CALL or OptionType.PUT
        strike: Strike price (e.g. Decimal("190.00"))

    Returns:
        OSI symbol string, e.g. "AAPL251219C00190000"

    Raises:
        ValueError: If expiration_date is not in "YYYY-MM-DD" format.
    """
    opt_char = "C" if option_type == OptionType.CALL else "P"
    try:
        date = datetime.strptime(expiration_date, "%Y-%m-%d")
    except ValueError:
        raise ValueError(
            f"expiration_date must be in 'YYYY-MM-DD' format (e.g. '2025-12-19'); "
            f"got {expiration_date!r}."
        )
    strike_units = int(
        (strike * 1000).to_integral_value(rounding=ROUND_HALF_UP)
    )
    return f"{symbol.upper()}{date.strftime('%y%m%d')}{opt_char}{strike_units:08d}"


def _make_credit_spread_request(
    symbol: str,
    option_type: OptionType,
    expiration_date: str,
    sell_strike: Decimal,
    buy_strike: Decimal,
    quantity: int,
    limit_price: Decimal,
    time_in_force: TimeInForce,
    expiration_time: Optional[datetime],
) -> PreflightMultiLegRequest:
    """Build the PreflightMultiLegRequest for a vertical credit spread.

    The API requires a negative limit_price for credit spreads.  Callers pass
    a positive value representing the minimum credit they want to receive; this
    function negates it before building the request.

    Raises:
        ValueError: If limit_price is not positive, or if strikes are equal or
            in the wrong order for the given option_type.
    """
    if limit_price <= 0:
        raise ValueError(
            f"limit_price must be a positive value representing the minimum credit "
            f"to accept (e.g. Decimal('2.50') for a $2.50 per-share credit); "
            f"got {limit_price}."
        )
    if option_type == OptionType.CALL:
        if sell_strike >= buy_strike:
            raise ValueError(
                f"CALL credit spread (Bear Call Spread) requires sell_strike < buy_strike "
                f"— sell the lower/closer-to-money strike and buy the higher/further OTM "
                f"strike for protection "
                f"(got sell_strike={sell_strike}, buy_strike={buy_strike})."
            )
    else:
        if sell_strike <= buy_strike:
            raise ValueError(
                f"PUT credit spread (Bull Put Spread) requires sell_strike > buy_strike "
                f"— sell the higher/closer-to-money strike and buy the lower/further OTM "
                f"strike for protection "
                f"(got sell_strike={sell_strike}, buy_strike={buy_strike})."
            )
    sell_osi = _build_osi(symbol, expiration_date, option_type, sell_strike)
    buy_osi = _build_osi(symbol, expiration_date, option_type, buy_strike)
    return PreflightMultiLegRequest(
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        ),
        quantity=quantity,
        limit_price=-limit_price,
        legs=[
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=sell_osi, type=LegInstrumentType.OPTION
                ),
                side=OrderSide.SELL,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=buy_osi, type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
        ],
    )


def _make_debit_spread_request(
    symbol: str,
    option_type: OptionType,
    expiration_date: str,
    buy_strike: Decimal,
    sell_strike: Decimal,
    quantity: int,
    limit_price: Decimal,
    time_in_force: TimeInForce,
    expiration_time: Optional[datetime],
) -> PreflightMultiLegRequest:
    """Build the PreflightMultiLegRequest for a vertical debit spread.

    Raises:
        ValueError: If limit_price is not positive, or if strikes are equal or
            in the wrong order for the given option_type.
    """
    if limit_price <= 0:
        raise ValueError(
            f"limit_price must be a positive value representing the maximum debit "
            f"to pay (e.g. Decimal('3.00') for a $3.00 per-share debit); "
            f"got {limit_price}."
        )
    if option_type == OptionType.CALL:
        if buy_strike >= sell_strike:
            raise ValueError(
                f"CALL debit spread (Bull Call Spread) requires buy_strike < sell_strike "
                f"— buy the lower/closer-to-money strike and sell the higher/further OTM "
                f"strike to cap the cost "
                f"(got buy_strike={buy_strike}, sell_strike={sell_strike})."
            )
    else:
        if buy_strike <= sell_strike:
            raise ValueError(
                f"PUT debit spread (Bear Put Spread) requires buy_strike > sell_strike "
                f"— buy the higher/closer-to-money strike and sell the lower/further OTM "
                f"strike to cap the cost "
                f"(got buy_strike={buy_strike}, sell_strike={sell_strike})."
            )
    buy_osi = _build_osi(symbol, expiration_date, option_type, buy_strike)
    sell_osi = _build_osi(symbol, expiration_date, option_type, sell_strike)
    return PreflightMultiLegRequest(
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        ),
        quantity=quantity,
        limit_price=limit_price,
        legs=[
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=buy_osi, type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=sell_osi, type=LegInstrumentType.OPTION
                ),
                side=OrderSide.SELL,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
        ],
    )


# ---------------------------------------------------------------------------
# OSI-symbol-based two-leg spread helpers
#
# Used by `client.preflight_call_credit_spread` and the three sibling methods.
# Callers pass OSI symbols directly (typically obtained from `get_option_chain`)
# rather than describing the spread by symbol + strikes.
# ---------------------------------------------------------------------------

# OSI option-symbol format: SYMBOL(1-6 letters) + YYMMDD + C|P + STRIKE(8 digits,
# 3 implied decimals). Example: "AAPL251219C00190000".
_OSI_RE = re.compile(r"^([A-Z]{1,6})(\d{6})([CP])(\d{8})$")


class _SpreadKind(Enum):
    """Internal tag for the four vertical spread strategies."""

    CALL_CREDIT = "CALL_CREDIT"
    CALL_DEBIT = "CALL_DEBIT"
    PUT_CREDIT = "PUT_CREDIT"
    PUT_DEBIT = "PUT_DEBIT"


class _ParsedOSI:
    """Parsed components of an OSI option symbol."""

    __slots__ = ("symbol", "expiration_date", "option_type", "strike")

    def __init__(
        self,
        symbol: str,
        expiration_date: str,
        option_type: OptionType,
        strike: Decimal,
    ) -> None:
        self.symbol = symbol
        self.expiration_date = expiration_date
        self.option_type = option_type
        self.strike = strike


def _parse_osi(osi: str) -> _ParsedOSI:
    """Parse an OSI option symbol into its components.

    Args:
        osi: OSI symbol, e.g. ``"AAPL251219C00190000"``. Whitespace is stripped
            and letters are upper-cased before matching.

    Returns:
        ``_ParsedOSI`` with ``symbol``, ``expiration_date`` (YYYY-MM-DD),
        ``option_type``, and ``strike``.

    Raises:
        ValueError: If ``osi`` does not match the OSI format, or the embedded
            month/day are out of range.
    """
    cleaned = osi.strip().upper()
    match = _OSI_RE.match(cleaned)
    if not match:
        raise ValueError(
            f"Invalid OSI symbol: {osi!r}. Expected format SYMBOL(1-6 letters) + "
            f"YYMMDD + C|P + 8-digit strike (e.g. 'AAPL251219C00190000')."
        )
    symbol, yymmdd, opt_char, strike_str = match.groups()
    yy = int(yymmdd[0:2])
    mm = int(yymmdd[2:4])
    dd = int(yymmdd[4:6])
    if not (1 <= mm <= 12 and 1 <= dd <= 31):
        raise ValueError(
            f"Invalid expiration in OSI symbol {osi!r}: month={mm:02d} day={dd:02d} "
            f"out of range."
        )
    expiration_date = f"{2000 + yy:04d}-{mm:02d}-{dd:02d}"
    option_type = OptionType.CALL if opt_char == "C" else OptionType.PUT
    # 8-digit strike with 3 implied decimals (e.g. "00190000" -> 190.000).
    strike = Decimal(strike_str) / Decimal(1000)
    return _ParsedOSI(symbol, expiration_date, option_type, strike)


def _validate_two_leg_spread(
    sell_contract_osi: str,
    buy_contract_osi: str,
    kind: _SpreadKind,
) -> Tuple[_ParsedOSI, _ParsedOSI]:
    """Parse and validate two OSI symbols for a vertical spread.

    Checks (in order):
      1. Both OSI symbols parse.
      2. Same underlying ticker.
      3. Same expiration date.
      4. Both legs are the option type expected for the strategy
         (CALL for call spreads, PUT for put spreads).
      5. Strike ordering matches the strategy direction.

    Returns the parsed sell + buy legs.

    Raises:
        ValueError: On any of the above failures, with a message that explains
            which constraint was violated.
    """
    sell = _parse_osi(sell_contract_osi)
    buy = _parse_osi(buy_contract_osi)

    if sell.symbol != buy.symbol:
        raise ValueError(
            f"Both legs must share the same underlying ticker; got "
            f"sell={sell.symbol!r}, buy={buy.symbol!r}."
        )
    if sell.expiration_date != buy.expiration_date:
        raise ValueError(
            f"Both legs must share the same expiration date; got "
            f"sell={sell.expiration_date}, buy={buy.expiration_date}."
        )

    expected_type = (
        OptionType.CALL
        if kind in (_SpreadKind.CALL_CREDIT, _SpreadKind.CALL_DEBIT)
        else OptionType.PUT
    )
    if sell.option_type != expected_type or buy.option_type != expected_type:
        raise ValueError(
            f"Both legs must be {expected_type.value} for this strategy; got "
            f"sell={sell.option_type.value}, buy={buy.option_type.value}."
        )

    if kind is _SpreadKind.CALL_CREDIT:
        if not (sell.strike < buy.strike):
            raise ValueError(
                f"CALL credit spread (Bear Call Spread) requires "
                f"sell_strike < buy_strike; got sell={sell.strike}, buy={buy.strike}."
            )
    elif kind is _SpreadKind.CALL_DEBIT:
        if not (buy.strike < sell.strike):
            raise ValueError(
                f"CALL debit spread (Bull Call Spread) requires "
                f"buy_strike < sell_strike; got buy={buy.strike}, sell={sell.strike}."
            )
    elif kind is _SpreadKind.PUT_CREDIT:
        if not (sell.strike > buy.strike):
            raise ValueError(
                f"PUT credit spread (Bull Put Spread) requires "
                f"sell_strike > buy_strike; got sell={sell.strike}, buy={buy.strike}."
            )
    elif kind is _SpreadKind.PUT_DEBIT:
        if not (buy.strike > sell.strike):
            raise ValueError(
                f"PUT debit spread (Bear Put Spread) requires "
                f"buy_strike > sell_strike; got buy={buy.strike}, sell={sell.strike}."
            )

    return sell, buy


def _build_two_leg_spread_request(
    sell_contract_osi: str,
    buy_contract_osi: str,
    kind: _SpreadKind,
    quantity: int,
    limit_price: Decimal,
    time_in_force: TimeInForce,
    expiration_time: Optional[datetime],
    validate_order: Optional[bool],
) -> PreflightMultiLegRequest:
    """Validate the two legs and construct a ``PreflightMultiLegRequest``.

    ``limit_price`` is always passed as a positive value. The SDK signs it
    based on the strategy: credit spreads negate it (the API expects negative
    for net credit), debit spreads keep it positive.

    Raises:
        ValueError: If ``limit_price <= 0`` or any spread-validation rule
            (see :func:`_validate_two_leg_spread`) fails.
    """
    if limit_price <= 0:
        raise ValueError(
            f"limit_price must be a positive value; the SDK signs it for "
            f"credit vs. debit spreads automatically. Got {limit_price}."
        )

    _validate_two_leg_spread(sell_contract_osi, buy_contract_osi, kind)

    is_credit = kind in (_SpreadKind.CALL_CREDIT, _SpreadKind.PUT_CREDIT)
    signed_limit_price = -limit_price if is_credit else limit_price

    return PreflightMultiLegRequest(
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        ),
        quantity=quantity,
        limit_price=signed_limit_price,
        legs=[
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=sell_contract_osi.strip().upper(),
                    type=LegInstrumentType.OPTION,
                ),
                side=OrderSide.SELL,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=buy_contract_osi.strip().upper(),
                    type=LegInstrumentType.OPTION,
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
        ],
        validate_order=validate_order,
    )


def _build_two_leg_spread_order_request(
    sell_contract_osi: str,
    buy_contract_osi: str,
    kind: _SpreadKind,
    quantity: int,
    limit_price: Decimal,
    time_in_force: TimeInForce,
    expiration_time: Optional[datetime],
    order_id: Optional[str],
) -> MultilegOrderRequest:
    """Validate the two legs and construct a ``MultilegOrderRequest``.

    Mirrors :func:`_build_two_leg_spread_request`, but returns the request
    shape used for live multi-leg order placement. If ``order_id`` is omitted,
    a UUIDv4 idempotency key is generated for the caller.
    """
    if limit_price <= 0:
        raise ValueError(
            f"limit_price must be a positive value; the SDK signs it for "
            f"credit vs. debit spreads automatically. Got {limit_price}."
        )

    _validate_two_leg_spread(sell_contract_osi, buy_contract_osi, kind)

    is_credit = kind in (_SpreadKind.CALL_CREDIT, _SpreadKind.PUT_CREDIT)
    signed_limit_price = -limit_price if is_credit else limit_price

    return MultilegOrderRequest(
        order_id=order_id or str(uuid4()),
        type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(
            time_in_force=time_in_force,
            expiration_time=expiration_time,
        ),
        quantity=quantity,
        limit_price=signed_limit_price,
        legs=[
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=sell_contract_osi.strip().upper(),
                    type=LegInstrumentType.OPTION,
                ),
                side=OrderSide.SELL,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol=buy_contract_osi.strip().upper(),
                    type=LegInstrumentType.OPTION,
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
        ],
    )


class StrategyPreflight:
    """Strategy-level preflight helpers for common vertical spread structures.

    Accessed via ``client.strategy_preflight``. Each method builds the
    appropriate :class:`PreflightMultiLegRequest` and delegates to the
    client's ``perform_multi_leg_preflight_calculation``.
    """

    def __init__(self, preflight_func: PreflightFunc) -> None:
        self._preflight = preflight_func

    def credit_spread(
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
                For CALLs this must be *less than* ``buy_strike``.
                For PUTs this must be *greater than* ``buy_strike``.
            buy_strike: The strike to buy (caps maximum loss).
            quantity: Number of spread contracts.
            limit_price: Minimum net credit to accept (positive value,
                e.g. ``Decimal("2.50")`` for a $2.50 per-share credit).
                The sign is handled automatically — always pass a positive number.
            time_in_force: ``DAY`` or ``GTD`` (default ``DAY``).
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Returns:
            :class:`PreflightMultiLegResponse` with estimated credit,
            commission, and buying power impact.

        Raises:
            ValueError: If ``limit_price`` is not positive, if the strikes
                are equal, or if their order contradicts the strategy type
                (e.g. CALL credit spread with ``sell_strike >= buy_strike``).
            ValueError: If no account ID is available.
            ValidationError: If the API rejects the request (HTTP 400) — e.g.
                invalid symbol, unsupported expiration, or insufficient buying power.
            AuthenticationError: If the API key or token is invalid (HTTP 401).
            APIError: For any other API error.
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
        return self._preflight(request, account_id)

    def debit_spread(
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
                For CALLs this must be *less than* ``sell_strike``.
                For PUTs this must be *greater than* ``sell_strike``.
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

        Raises:
            ValueError: If ``limit_price`` is not positive, if the strikes
                are equal, or if their order contradicts the strategy type
                (e.g. CALL debit spread with ``buy_strike >= sell_strike``).
            ValueError: If no account ID is available.
            ValidationError: If the API rejects the request (HTTP 400).
            AuthenticationError: If the API key or token is invalid (HTTP 401).
            APIError: For any other API error.
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
        return self._preflight(request, account_id)
