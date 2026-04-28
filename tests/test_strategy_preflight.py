"""Tests for StrategyPreflight, AsyncStrategyPreflight, and helpers."""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID

import pytest

from public_api_sdk.models.option import (
    LegInstrumentType,
    MultilegOrderRequest,
    OpenCloseIndicator,
    PreflightMultiLegRequest,
    PreflightMultiLegResponse,
)
from public_api_sdk.models.order import (
    OptionType,
    OrderSide,
    OrderType,
    TimeInForce,
)
from public_api_sdk.strategy_preflight import (
    StrategyPreflight,
    _SpreadKind,
    _build_osi,
    _build_two_leg_spread_order_request,
    _build_two_leg_spread_request,
    _make_credit_spread_request,
    _make_debit_spread_request,
    _parse_osi,
    _validate_two_leg_spread,
)
from public_api_sdk.async_strategy_preflight import AsyncStrategyPreflight

VALID_ORDER_ID = "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# _build_osi
# ---------------------------------------------------------------------------


class TestBuildOsi:
    def test_call_option(self) -> None:
        osi = _build_osi("AAPL", "2025-12-19", OptionType.CALL, Decimal("190"))
        assert osi == "AAPL251219C00190000"

    def test_put_option(self) -> None:
        osi = _build_osi("AAPL", "2025-12-19", OptionType.PUT, Decimal("190"))
        assert osi == "AAPL251219P00190000"

    def test_symbol_uppercased(self) -> None:
        osi = _build_osi("aapl", "2025-12-19", OptionType.CALL, Decimal("190"))
        assert osi.startswith("AAPL")

    def test_fractional_strike(self) -> None:
        # $190.50 → 190500 → zero-padded to 8 digits: 00190500
        osi = _build_osi("AAPL", "2025-12-19", OptionType.CALL, Decimal("190.50"))
        assert osi == "AAPL251219C00190500"

    def test_small_strike(self) -> None:
        # $5.00 → 5000 → 00005000
        osi = _build_osi("SPY", "2025-06-20", OptionType.PUT, Decimal("5"))
        assert osi == "SPY250620P00005000"

    def test_large_strike(self) -> None:
        # $1000.00 → 1000000 → 01000000
        osi = _build_osi("TSLA", "2025-01-17", OptionType.CALL, Decimal("1000"))
        assert osi == "TSLA250117C01000000"

    def test_date_formatting(self) -> None:
        osi = _build_osi("SPY", "2025-01-03", OptionType.CALL, Decimal("100"))
        # Year=25, Month=01, Day=03
        assert osi == "SPY250103C00100000"

    def test_rounding_half_up(self) -> None:
        # $190.0005 → 190000.5 → rounds to 190001 → 00190001
        osi = _build_osi("AAPL", "2025-12-19", OptionType.CALL, Decimal("190.0005"))
        assert osi == "AAPL251219C00190001"


# ---------------------------------------------------------------------------
# _build_osi — invalid date format
# ---------------------------------------------------------------------------


class TestBuildOsiValidation:
    def test_invalid_date_format_raises(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _build_osi("AAPL", "19-12-2025", OptionType.CALL, Decimal("190"))

    def test_completely_bad_date_raises(self) -> None:
        with pytest.raises(ValueError, match="YYYY-MM-DD"):
            _build_osi("AAPL", "not-a-date", OptionType.CALL, Decimal("190"))


# ---------------------------------------------------------------------------
# _make_credit_spread_request
# ---------------------------------------------------------------------------


class TestMakeCreditSpreadRequest:
    def _build(self, **kwargs) -> PreflightMultiLegRequest:
        defaults = dict(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
        )
        defaults.update(kwargs)
        return _make_credit_spread_request(**defaults)

    def test_order_type_is_limit(self) -> None:
        req = self._build()
        assert req.order_type == OrderType.LIMIT

    def test_quantity_and_limit_price(self) -> None:
        # The API requires a negative limit_price for credit spreads;
        # the caller passes a positive value and the builder negates it.
        req = self._build(quantity=3, limit_price=Decimal("1.75"))
        assert req.quantity == 3
        assert req.limit_price == Decimal("-1.75")

    def test_two_legs(self) -> None:
        req = self._build()
        assert len(req.legs) == 2

    def test_first_leg_is_sell(self) -> None:
        req = self._build()
        assert req.legs[0].side == OrderSide.SELL

    def test_second_leg_is_buy(self) -> None:
        req = self._build()
        assert req.legs[1].side == OrderSide.BUY

    def test_sell_leg_osi(self) -> None:
        req = self._build(sell_strike=Decimal("190"))
        assert req.legs[0].instrument.symbol == "AAPL251219C00190000"

    def test_buy_leg_osi(self) -> None:
        req = self._build(buy_strike=Decimal("195"))
        assert req.legs[1].instrument.symbol == "AAPL251219C00195000"

    def test_put_credit_spread(self) -> None:
        req = self._build(
            option_type=OptionType.PUT,
            sell_strike=Decimal("185"),
            buy_strike=Decimal("180"),
        )
        assert req.legs[0].instrument.symbol == "AAPL251219P00185000"
        assert req.legs[1].instrument.symbol == "AAPL251219P00180000"

    def test_open_close_indicator_is_open(self) -> None:
        req = self._build()
        for leg in req.legs:
            assert leg.open_close_indicator == OpenCloseIndicator.OPEN

    def test_ratio_quantity_is_one(self) -> None:
        req = self._build()
        for leg in req.legs:
            assert leg.ratio_quantity == 1

    def test_instrument_type_is_option(self) -> None:
        req = self._build()
        for leg in req.legs:
            assert leg.instrument.type == LegInstrumentType.OPTION

    def test_time_in_force_passed_through(self) -> None:
        exp_time = datetime(2025, 12, 19, 16, 0, tzinfo=timezone.utc)
        req = self._build(time_in_force=TimeInForce.GTD, expiration_time=exp_time)
        assert req.expiration.time_in_force == TimeInForce.GTD
        assert req.expiration.expiration_time == exp_time


# ---------------------------------------------------------------------------
# _make_credit_spread_request — validation
# ---------------------------------------------------------------------------


class TestCreditSpreadValidation:
    def _base(self, **kwargs):
        defaults = dict(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
        )
        defaults.update(kwargs)
        return _make_credit_spread_request(**defaults)

    def test_zero_limit_price_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            self._base(limit_price=Decimal("0"))

    def test_negative_limit_price_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            self._base(limit_price=Decimal("-1.00"))

    def test_call_equal_strikes_raises(self) -> None:
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            self._base(sell_strike=Decimal("190"), buy_strike=Decimal("190"))

    def test_call_inverted_strikes_raises(self) -> None:
        # sell_strike > buy_strike is wrong for a CALL credit spread
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            self._base(sell_strike=Decimal("195"), buy_strike=Decimal("190"))

    def test_put_equal_strikes_raises(self) -> None:
        with pytest.raises(ValueError, match="sell_strike > buy_strike"):
            self._base(
                option_type=OptionType.PUT,
                sell_strike=Decimal("185"),
                buy_strike=Decimal("185"),
            )

    def test_put_inverted_strikes_raises(self) -> None:
        # sell_strike < buy_strike is wrong for a PUT credit spread
        with pytest.raises(ValueError, match="sell_strike > buy_strike"):
            self._base(
                option_type=OptionType.PUT,
                sell_strike=Decimal("180"),
                buy_strike=Decimal("185"),
            )

    def test_valid_call_credit_spread_passes(self) -> None:
        req = self._base(sell_strike=Decimal("190"), buy_strike=Decimal("195"))
        assert req.legs[0].side == OrderSide.SELL

    def test_valid_put_credit_spread_passes(self) -> None:
        req = self._base(
            option_type=OptionType.PUT,
            sell_strike=Decimal("185"),
            buy_strike=Decimal("180"),
        )
        assert req.legs[0].side == OrderSide.SELL


# ---------------------------------------------------------------------------
# _make_debit_spread_request
# ---------------------------------------------------------------------------


class TestMakeDebitSpreadRequest:
    def _build(self, **kwargs) -> PreflightMultiLegRequest:
        defaults = dict(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            buy_strike=Decimal("190"),
            sell_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("3.00"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
        )
        defaults.update(kwargs)
        return _make_debit_spread_request(**defaults)

    def test_order_type_is_limit(self) -> None:
        req = self._build()
        assert req.order_type == OrderType.LIMIT

    def test_first_leg_is_buy(self) -> None:
        req = self._build()
        assert req.legs[0].side == OrderSide.BUY

    def test_second_leg_is_sell(self) -> None:
        req = self._build()
        assert req.legs[1].side == OrderSide.SELL

    def test_buy_leg_osi(self) -> None:
        req = self._build(buy_strike=Decimal("190"))
        assert req.legs[0].instrument.symbol == "AAPL251219C00190000"

    def test_sell_leg_osi(self) -> None:
        req = self._build(sell_strike=Decimal("195"))
        assert req.legs[1].instrument.symbol == "AAPL251219C00195000"

    def test_put_debit_spread(self) -> None:
        req = self._build(
            option_type=OptionType.PUT,
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
        )
        assert req.legs[0].instrument.symbol == "AAPL251219P00185000"
        assert req.legs[1].instrument.symbol == "AAPL251219P00180000"

    def test_open_close_indicator_is_open(self) -> None:
        req = self._build()
        for leg in req.legs:
            assert leg.open_close_indicator == OpenCloseIndicator.OPEN

    def test_ratio_quantity_is_one(self) -> None:
        req = self._build()
        for leg in req.legs:
            assert leg.ratio_quantity == 1


# ---------------------------------------------------------------------------
# _make_debit_spread_request — validation
# ---------------------------------------------------------------------------


class TestDebitSpreadValidation:
    def _base(self, **kwargs):
        defaults = dict(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            buy_strike=Decimal("190"),
            sell_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("3.00"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
        )
        defaults.update(kwargs)
        return _make_debit_spread_request(**defaults)

    def test_zero_limit_price_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            self._base(limit_price=Decimal("0"))

    def test_negative_limit_price_raises(self) -> None:
        with pytest.raises(ValueError, match="positive"):
            self._base(limit_price=Decimal("-1.00"))

    def test_call_equal_strikes_raises(self) -> None:
        with pytest.raises(ValueError, match="buy_strike < sell_strike"):
            self._base(buy_strike=Decimal("190"), sell_strike=Decimal("190"))

    def test_call_inverted_strikes_raises(self) -> None:
        # buy_strike > sell_strike is wrong for a CALL debit spread
        with pytest.raises(ValueError, match="buy_strike < sell_strike"):
            self._base(buy_strike=Decimal("195"), sell_strike=Decimal("190"))

    def test_put_equal_strikes_raises(self) -> None:
        with pytest.raises(ValueError, match="buy_strike > sell_strike"):
            self._base(
                option_type=OptionType.PUT,
                buy_strike=Decimal("185"),
                sell_strike=Decimal("185"),
            )

    def test_put_inverted_strikes_raises(self) -> None:
        # buy_strike < sell_strike is wrong for a PUT debit spread
        with pytest.raises(ValueError, match="buy_strike > sell_strike"):
            self._base(
                option_type=OptionType.PUT,
                buy_strike=Decimal("180"),
                sell_strike=Decimal("185"),
            )

    def test_valid_call_debit_spread_passes(self) -> None:
        req = self._base(buy_strike=Decimal("190"), sell_strike=Decimal("195"))
        assert req.legs[0].side == OrderSide.BUY

    def test_valid_put_debit_spread_passes(self) -> None:
        req = self._base(
            option_type=OptionType.PUT,
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
        )
        assert req.legs[0].side == OrderSide.BUY


# ---------------------------------------------------------------------------
# StrategyPreflight (sync)
# ---------------------------------------------------------------------------


class TestStrategyPreflightSync:
    def setup_method(self) -> None:
        self.mock_response = MagicMock(spec=PreflightMultiLegResponse)
        self.preflight_func = MagicMock(return_value=self.mock_response)
        self.sp = StrategyPreflight(preflight_func=self.preflight_func)

    def test_credit_spread_calls_preflight(self) -> None:
        result = self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        self.preflight_func.assert_called_once()
        assert result is self.mock_response

    def test_credit_spread_passes_request_and_account_id(self) -> None:
        self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
            account_id="ACC123",
        )
        call_args = self.preflight_func.call_args
        request = call_args[0][0]
        account_id = call_args[0][1]
        assert isinstance(request, PreflightMultiLegRequest)
        assert account_id == "ACC123"

    def test_credit_spread_default_account_id_is_none(self) -> None:
        self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        assert self.preflight_func.call_args[0][1] is None

    def test_credit_spread_call_leg_order(self) -> None:
        self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        request: PreflightMultiLegRequest = self.preflight_func.call_args[0][0]
        assert request.legs[0].side == OrderSide.SELL
        assert request.legs[1].side == OrderSide.BUY

    def test_debit_spread_calls_preflight(self) -> None:
        result = self.sp.debit_spread(
            symbol="AAPL",
            option_type=OptionType.PUT,
            expiration_date="2025-12-19",
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
            quantity=2,
            limit_price=Decimal("3.00"),
        )
        self.preflight_func.assert_called_once()
        assert result is self.mock_response

    def test_debit_spread_passes_account_id(self) -> None:
        self.sp.debit_spread(
            symbol="AAPL",
            option_type=OptionType.PUT,
            expiration_date="2025-12-19",
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
            quantity=1,
            limit_price=Decimal("3.00"),
            account_id="ACC456",
        )
        assert self.preflight_func.call_args[0][1] == "ACC456"

    def test_debit_spread_put_leg_order(self) -> None:
        self.sp.debit_spread(
            symbol="AAPL",
            option_type=OptionType.PUT,
            expiration_date="2025-12-19",
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
            quantity=1,
            limit_price=Decimal("3.00"),
        )
        request: PreflightMultiLegRequest = self.preflight_func.call_args[0][0]
        assert request.legs[0].side == OrderSide.BUY
        assert request.legs[1].side == OrderSide.SELL

    def test_gtd_expiration_passed_through(self) -> None:
        exp_time = datetime(2025, 12, 19, 16, 0, tzinfo=timezone.utc)
        self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.GTD,
            expiration_time=exp_time,
        )
        request: PreflightMultiLegRequest = self.preflight_func.call_args[0][0]
        assert request.expiration.time_in_force == TimeInForce.GTD
        assert request.expiration.expiration_time == exp_time


# ---------------------------------------------------------------------------
# AsyncStrategyPreflight
# ---------------------------------------------------------------------------


class TestAsyncStrategyPreflight:
    def setup_method(self) -> None:
        self.mock_response = MagicMock(spec=PreflightMultiLegResponse)
        self.preflight_func = AsyncMock(return_value=self.mock_response)
        self.sp = AsyncStrategyPreflight(preflight_func=self.preflight_func)

    @pytest.mark.asyncio
    async def test_credit_spread_calls_preflight(self) -> None:
        result = await self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        self.preflight_func.assert_awaited_once()
        assert result is self.mock_response

    @pytest.mark.asyncio
    async def test_credit_spread_passes_request_and_account_id(self) -> None:
        await self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
            account_id="ACC789",
        )
        call_args = self.preflight_func.call_args
        request = call_args[0][0]
        account_id = call_args[0][1]
        assert isinstance(request, PreflightMultiLegRequest)
        assert account_id == "ACC789"

    @pytest.mark.asyncio
    async def test_credit_spread_leg_order(self) -> None:
        await self.sp.credit_spread(
            symbol="AAPL",
            option_type=OptionType.CALL,
            expiration_date="2025-12-19",
            sell_strike=Decimal("190"),
            buy_strike=Decimal("195"),
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        request: PreflightMultiLegRequest = self.preflight_func.call_args[0][0]
        assert request.legs[0].side == OrderSide.SELL
        assert request.legs[1].side == OrderSide.BUY

    @pytest.mark.asyncio
    async def test_debit_spread_calls_preflight(self) -> None:
        result = await self.sp.debit_spread(
            symbol="AAPL",
            option_type=OptionType.PUT,
            expiration_date="2025-12-19",
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
            quantity=1,
            limit_price=Decimal("3.00"),
        )
        self.preflight_func.assert_awaited_once()
        assert result is self.mock_response

    @pytest.mark.asyncio
    async def test_debit_spread_passes_account_id(self) -> None:
        await self.sp.debit_spread(
            symbol="AAPL",
            option_type=OptionType.PUT,
            expiration_date="2025-12-19",
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
            quantity=1,
            limit_price=Decimal("3.00"),
            account_id="ACC000",
        )
        assert self.preflight_func.call_args[0][1] == "ACC000"

    @pytest.mark.asyncio
    async def test_debit_spread_leg_order(self) -> None:
        await self.sp.debit_spread(
            symbol="AAPL",
            option_type=OptionType.PUT,
            expiration_date="2025-12-19",
            buy_strike=Decimal("185"),
            sell_strike=Decimal("180"),
            quantity=1,
            limit_price=Decimal("3.00"),
        )
        request: PreflightMultiLegRequest = self.preflight_func.call_args[0][0]
        assert request.legs[0].side == OrderSide.BUY
        assert request.legs[1].side == OrderSide.SELL


# ---------------------------------------------------------------------------
# OSI-direct two-leg spread helpers (`_parse_osi` / `_validate_two_leg_spread`
# / `_build_two_leg_spread_request`) — backing the four
# `client.preflight_*_spread` methods.
# ---------------------------------------------------------------------------


class TestParseOsi:
    def test_call_basic(self) -> None:
        p = _parse_osi("AAPL251219C00190000")
        assert p.symbol == "AAPL"
        assert p.expiration_date == "2025-12-19"
        assert p.option_type == OptionType.CALL
        assert p.strike == Decimal("190")

    def test_put_basic(self) -> None:
        p = _parse_osi("AAPL251219P00185000")
        assert p.option_type == OptionType.PUT
        assert p.strike == Decimal("185")

    def test_fractional_strike(self) -> None:
        p = _parse_osi("AAPL251219C00190500")  # $190.500
        assert p.strike == Decimal("190.500")

    def test_lowercase_input_uppercased(self) -> None:
        p = _parse_osi("aapl251219c00190000")
        assert p.symbol == "AAPL"
        assert p.option_type == OptionType.CALL

    def test_whitespace_stripped(self) -> None:
        p = _parse_osi("  AAPL251219C00190000  ")
        assert p.symbol == "AAPL"

    def test_short_symbol(self) -> None:
        p = _parse_osi("F250620C00010000")
        assert p.symbol == "F"
        assert p.strike == Decimal("10")

    def test_invalid_format_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid OSI symbol"):
            _parse_osi("not-a-real-osi")

    def test_missing_strike_raises(self) -> None:
        with pytest.raises(ValueError, match="Invalid OSI symbol"):
            _parse_osi("AAPL251219C")

    def test_invalid_month_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            _parse_osi("AAPL251319C00190000")  # MM=13

    def test_invalid_day_raises(self) -> None:
        with pytest.raises(ValueError, match="out of range"):
            _parse_osi("AAPL251232C00190000")  # DD=32

    def test_unknown_option_char_rejected(self) -> None:
        with pytest.raises(ValueError, match="Invalid OSI symbol"):
            _parse_osi("AAPL251219X00190000")


class TestValidateTwoLegSpread:
    def test_call_credit_valid(self) -> None:
        sell, buy = _validate_two_leg_spread(
            "AAPL251219C00190000",
            "AAPL251219C00195000",
            _SpreadKind.CALL_CREDIT,
        )
        assert sell.strike == Decimal("190")
        assert buy.strike == Decimal("195")

    def test_call_debit_valid(self) -> None:
        _validate_two_leg_spread(
            "AAPL251219C00200000",
            "AAPL251219C00195000",
            _SpreadKind.CALL_DEBIT,
        )

    def test_put_credit_valid(self) -> None:
        _validate_two_leg_spread(
            "AAPL251219P00185000",
            "AAPL251219P00180000",
            _SpreadKind.PUT_CREDIT,
        )

    def test_put_debit_valid(self) -> None:
        _validate_two_leg_spread(
            "AAPL251219P00180000",
            "AAPL251219P00185000",
            _SpreadKind.PUT_DEBIT,
        )

    def test_different_underlyings_rejected(self) -> None:
        with pytest.raises(ValueError, match="same underlying ticker"):
            _validate_two_leg_spread(
                "AAPL251219C00190000",
                "MSFT251219C00195000",
                _SpreadKind.CALL_CREDIT,
            )

    def test_different_expirations_rejected(self) -> None:
        with pytest.raises(ValueError, match="same expiration date"):
            _validate_two_leg_spread(
                "AAPL251219C00190000",
                "AAPL260116C00195000",
                _SpreadKind.CALL_CREDIT,
            )

    def test_call_credit_with_put_legs_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be CALL"):
            _validate_two_leg_spread(
                "AAPL251219P00190000",
                "AAPL251219P00195000",
                _SpreadKind.CALL_CREDIT,
            )

    def test_put_debit_with_call_legs_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be PUT"):
            _validate_two_leg_spread(
                "AAPL251219C00180000",
                "AAPL251219C00185000",
                _SpreadKind.PUT_DEBIT,
            )

    def test_call_credit_wrong_strike_order_rejected(self) -> None:
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            _validate_two_leg_spread(
                "AAPL251219C00195000",
                "AAPL251219C00190000",
                _SpreadKind.CALL_CREDIT,
            )

    def test_call_debit_wrong_strike_order_rejected(self) -> None:
        with pytest.raises(ValueError, match="buy_strike < sell_strike"):
            _validate_two_leg_spread(
                "AAPL251219C00190000",
                "AAPL251219C00195000",
                _SpreadKind.CALL_DEBIT,
            )

    def test_put_credit_wrong_strike_order_rejected(self) -> None:
        with pytest.raises(ValueError, match="sell_strike > buy_strike"):
            _validate_two_leg_spread(
                "AAPL251219P00180000",
                "AAPL251219P00185000",
                _SpreadKind.PUT_CREDIT,
            )

    def test_put_debit_wrong_strike_order_rejected(self) -> None:
        with pytest.raises(ValueError, match="buy_strike > sell_strike"):
            _validate_two_leg_spread(
                "AAPL251219P00185000",
                "AAPL251219P00180000",
                _SpreadKind.PUT_DEBIT,
            )

    def test_equal_strikes_rejected(self) -> None:
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            _validate_two_leg_spread(
                "AAPL251219C00190000",
                "AAPL251219C00190000",
                _SpreadKind.CALL_CREDIT,
            )


class TestBuildTwoLegSpreadRequest:
    def test_credit_spread_negates_limit_price(self) -> None:
        req = _build_two_leg_spread_request(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            kind=_SpreadKind.CALL_CREDIT,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            validate_order=None,
        )
        assert req.limit_price == Decimal("-2.50")

    def test_debit_spread_keeps_positive_limit_price(self) -> None:
        req = _build_two_leg_spread_request(
            sell_contract_osi="AAPL251219C00200000",
            buy_contract_osi="AAPL251219C00195000",
            kind=_SpreadKind.CALL_DEBIT,
            quantity=1,
            limit_price=Decimal("3.00"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            validate_order=None,
        )
        assert req.limit_price == Decimal("3.00")

    def test_negative_limit_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a positive value"):
            _build_two_leg_spread_request(
                sell_contract_osi="AAPL251219C00190000",
                buy_contract_osi="AAPL251219C00195000",
                kind=_SpreadKind.CALL_CREDIT,
                quantity=1,
                limit_price=Decimal("-1.00"),
                time_in_force=TimeInForce.DAY,
                expiration_time=None,
                validate_order=None,
            )

    def test_zero_limit_price_rejected(self) -> None:
        with pytest.raises(ValueError, match="must be a positive value"):
            _build_two_leg_spread_request(
                sell_contract_osi="AAPL251219C00190000",
                buy_contract_osi="AAPL251219C00195000",
                kind=_SpreadKind.CALL_CREDIT,
                quantity=1,
                limit_price=Decimal("0"),
                time_in_force=TimeInForce.DAY,
                expiration_time=None,
                validate_order=None,
            )

    def test_legs_carry_correct_sides_and_open_close(self) -> None:
        req = _build_two_leg_spread_request(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            kind=_SpreadKind.CALL_CREDIT,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            validate_order=None,
        )
        sell_leg, buy_leg = req.legs
        assert sell_leg.side == OrderSide.SELL
        assert sell_leg.open_close_indicator == OpenCloseIndicator.OPEN
        assert sell_leg.instrument.type == LegInstrumentType.OPTION
        assert sell_leg.instrument.symbol == "AAPL251219C00190000"
        assert buy_leg.side == OrderSide.BUY
        assert buy_leg.open_close_indicator == OpenCloseIndicator.OPEN
        assert buy_leg.instrument.symbol == "AAPL251219C00195000"

    def test_validate_order_passed_through(self) -> None:
        req = _build_two_leg_spread_request(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            kind=_SpreadKind.CALL_CREDIT,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            validate_order=False,
        )
        assert req.validate_order is False

    def test_uppercases_osi_in_legs(self) -> None:
        req = _build_two_leg_spread_request(
            sell_contract_osi="aapl251219c00190000",
            buy_contract_osi="aapl251219c00195000",
            kind=_SpreadKind.CALL_CREDIT,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            validate_order=None,
        )
        assert req.legs[0].instrument.symbol == "AAPL251219C00190000"
        assert req.legs[1].instrument.symbol == "AAPL251219C00195000"


# ---------------------------------------------------------------------------
# _build_two_leg_spread_order_request
# ---------------------------------------------------------------------------


class TestBuildTwoLegSpreadOrderRequest:
    def test_credit_spread_negates_limit_price(self) -> None:
        req = _build_two_leg_spread_order_request(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            kind=_SpreadKind.CALL_CREDIT,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            order_id=VALID_ORDER_ID,
        )
        assert isinstance(req, MultilegOrderRequest)
        assert req.order_id == VALID_ORDER_ID
        assert req.type == OrderType.LIMIT
        assert req.limit_price == Decimal("-2.50")
        assert req.legs[0].side == OrderSide.SELL
        assert req.legs[1].side == OrderSide.BUY

    def test_debit_spread_keeps_positive_limit_price(self) -> None:
        req = _build_two_leg_spread_order_request(
            sell_contract_osi="AAPL251219C00200000",
            buy_contract_osi="AAPL251219C00195000",
            kind=_SpreadKind.CALL_DEBIT,
            quantity=1,
            limit_price=Decimal("3.00"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            order_id=VALID_ORDER_ID,
        )
        assert req.limit_price == Decimal("3.00")

    def test_generates_order_id_when_omitted(self) -> None:
        req = _build_two_leg_spread_order_request(
            sell_contract_osi="AAPL251219P00185000",
            buy_contract_osi="AAPL251219P00180000",
            kind=_SpreadKind.PUT_CREDIT,
            quantity=1,
            limit_price=Decimal("1.20"),
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            order_id=None,
        )
        assert UUID(req.order_id).version == 4

    def test_invalid_strike_order_raises(self) -> None:
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            _build_two_leg_spread_order_request(
                sell_contract_osi="AAPL251219C00195000",
                buy_contract_osi="AAPL251219C00190000",
                kind=_SpreadKind.CALL_CREDIT,
                quantity=1,
                limit_price=Decimal("2.50"),
                time_in_force=TimeInForce.DAY,
                expiration_time=None,
                order_id=VALID_ORDER_ID,
            )


# ---------------------------------------------------------------------------
# Client.preflight_*_spread integration — sync
# ---------------------------------------------------------------------------


class TestSpreadPreflightClientSync:
    def setup_method(self) -> None:
        from public_api_sdk.public_api_client import PublicApiClient

        self.mock_response = MagicMock(spec=PreflightMultiLegResponse)
        self.client = MagicMock()
        self.client.perform_multi_leg_preflight_calculation = MagicMock(
            return_value=self.mock_response
        )
        # Bind the real bound methods to our MagicMock so the SDK code runs.
        for name in (
            "preflight_call_credit_spread",
            "preflight_call_debit_spread",
            "preflight_put_credit_spread",
            "preflight_put_debit_spread",
        ):
            setattr(
                self.client,
                name,
                getattr(PublicApiClient, name).__get__(self.client),
            )

    def test_call_credit_spread_dispatches(self) -> None:
        result = self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        assert result is self.mock_response
        request, account_id = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("-2.50")
        assert request.legs[0].side == OrderSide.SELL
        assert request.legs[0].instrument.symbol == "AAPL251219C00190000"
        assert account_id is None

    def test_call_debit_spread_keeps_positive_limit_price(self) -> None:
        self.client.preflight_call_debit_spread(
            sell_contract_osi="AAPL251219C00200000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("3.00"),
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("3.00")

    def test_put_credit_spread_negates(self) -> None:
        self.client.preflight_put_credit_spread(
            sell_contract_osi="AAPL251219P00185000",
            buy_contract_osi="AAPL251219P00180000",
            quantity=1,
            limit_price=Decimal("1.20"),
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("-1.20")

    def test_put_debit_spread_keeps_positive(self) -> None:
        self.client.preflight_put_debit_spread(
            sell_contract_osi="AAPL251219P00180000",
            buy_contract_osi="AAPL251219P00185000",
            quantity=1,
            limit_price=Decimal("2.10"),
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("2.10")

    def test_account_id_passes_through(self) -> None:
        self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            account_id="ACC123",
        )
        _, account_id = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert account_id == "ACC123"

    def test_validate_order_passes_through(self) -> None:
        self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            validate_order=False,
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.validate_order is False

    def test_invalid_strike_order_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            self.client.preflight_call_credit_spread(
                sell_contract_osi="AAPL251219C00195000",
                buy_contract_osi="AAPL251219C00190000",
                quantity=1,
                limit_price=Decimal("2.50"),
            )
        self.client.perform_multi_leg_preflight_calculation.assert_not_called()

    def test_mismatched_underlying_raises(self) -> None:
        with pytest.raises(ValueError, match="same underlying ticker"):
            self.client.preflight_call_credit_spread(
                sell_contract_osi="AAPL251219C00190000",
                buy_contract_osi="MSFT251219C00195000",
                quantity=1,
                limit_price=Decimal("2.50"),
            )

    def test_gtd_with_expiration_time(self) -> None:
        exp = datetime.now(timezone.utc) + timedelta(days=30)
        self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.GTD,
            expiration_time=exp,
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.expiration.time_in_force == TimeInForce.GTD
        assert request.expiration.expiration_time == exp


# ---------------------------------------------------------------------------
# Client.place_*_spread integration — sync
# ---------------------------------------------------------------------------


class TestSpreadPlacementClientSync:
    def setup_method(self) -> None:
        from public_api_sdk.public_api_client import PublicApiClient

        self.mock_order = MagicMock()
        self.client = MagicMock()
        self.client.place_multileg_order = MagicMock(return_value=self.mock_order)
        for name in (
            "place_call_credit_spread",
            "place_call_debit_spread",
            "place_put_credit_spread",
            "place_put_debit_spread",
        ):
            setattr(
                self.client,
                name,
                getattr(PublicApiClient, name).__get__(self.client),
            )

    def test_call_credit_spread_dispatches(self) -> None:
        result = self.client.place_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            order_id=VALID_ORDER_ID,
        )
        assert result is self.mock_order
        request, account_id = self.client.place_multileg_order.call_args[0]
        assert isinstance(request, MultilegOrderRequest)
        assert request.order_id == VALID_ORDER_ID
        assert request.limit_price == Decimal("-2.50")
        assert request.legs[0].instrument.symbol == "AAPL251219C00190000"
        assert account_id is None

    def test_call_debit_spread_keeps_positive_limit_price(self) -> None:
        self.client.place_call_debit_spread(
            sell_contract_osi="AAPL251219C00200000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("3.00"),
            order_id=VALID_ORDER_ID,
        )
        request, _ = self.client.place_multileg_order.call_args[0]
        assert request.limit_price == Decimal("3.00")

    def test_put_credit_spread_negates(self) -> None:
        self.client.place_put_credit_spread(
            sell_contract_osi="AAPL251219P00185000",
            buy_contract_osi="AAPL251219P00180000",
            quantity=1,
            limit_price=Decimal("1.20"),
            order_id=VALID_ORDER_ID,
        )
        request, _ = self.client.place_multileg_order.call_args[0]
        assert request.limit_price == Decimal("-1.20")

    def test_auto_order_id_and_account_id(self) -> None:
        self.client.place_put_debit_spread(
            sell_contract_osi="AAPL251219P00180000",
            buy_contract_osi="AAPL251219P00185000",
            quantity=1,
            limit_price=Decimal("2.10"),
            account_id="ACC123",
        )
        request, account_id = self.client.place_multileg_order.call_args[0]
        assert UUID(request.order_id).version == 4
        assert request.limit_price == Decimal("2.10")
        assert account_id == "ACC123"

    def test_invalid_strike_order_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="sell_strike < buy_strike"):
            self.client.place_call_credit_spread(
                sell_contract_osi="AAPL251219C00195000",
                buy_contract_osi="AAPL251219C00190000",
                quantity=1,
                limit_price=Decimal("2.50"),
                order_id=VALID_ORDER_ID,
            )
        self.client.place_multileg_order.assert_not_called()


# ---------------------------------------------------------------------------
# Client.preflight_*_spread integration — async
# ---------------------------------------------------------------------------


class TestSpreadPreflightClientAsync:
    def setup_method(self) -> None:
        from public_api_sdk.async_public_api_client import AsyncPublicApiClient

        self.mock_response = MagicMock(spec=PreflightMultiLegResponse)
        self.client = MagicMock()
        self.client.perform_multi_leg_preflight_calculation = AsyncMock(
            return_value=self.mock_response
        )
        for name in (
            "preflight_call_credit_spread",
            "preflight_call_debit_spread",
            "preflight_put_credit_spread",
            "preflight_put_debit_spread",
        ):
            setattr(
                self.client,
                name,
                getattr(AsyncPublicApiClient, name).__get__(self.client),
            )

    @pytest.mark.asyncio
    async def test_call_credit_spread_async(self) -> None:
        result = await self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
        )
        assert result is self.mock_response
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("-2.50")

    @pytest.mark.asyncio
    async def test_put_debit_spread_async(self) -> None:
        await self.client.preflight_put_debit_spread(
            sell_contract_osi="AAPL251219P00180000",
            buy_contract_osi="AAPL251219P00185000",
            quantity=2,
            limit_price=Decimal("2.10"),
            validate_order=False,
            account_id="ACC123",
        )
        request, account_id = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("2.10")
        assert request.validate_order is False
        assert account_id == "ACC123"

    @pytest.mark.asyncio
    async def test_call_debit_spread_async(self) -> None:
        await self.client.preflight_call_debit_spread(
            sell_contract_osi="AAPL251219C00200000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("3.00"),
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("3.00")

    @pytest.mark.asyncio
    async def test_put_credit_spread_async(self) -> None:
        await self.client.preflight_put_credit_spread(
            sell_contract_osi="AAPL251219P00185000",
            buy_contract_osi="AAPL251219P00180000",
            quantity=1,
            limit_price=Decimal("1.20"),
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.limit_price == Decimal("-1.20")

    @pytest.mark.asyncio
    async def test_account_id_passes_through_async(self) -> None:
        await self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            account_id="ACC456",
        )
        _, account_id = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert account_id == "ACC456"

    @pytest.mark.asyncio
    async def test_validate_order_passes_through_async(self) -> None:
        await self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            validate_order=False,
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.validate_order is False

    @pytest.mark.asyncio
    async def test_mismatched_underlying_raises_async(self) -> None:
        with pytest.raises(ValueError, match="same underlying ticker"):
            await self.client.preflight_call_credit_spread(
                sell_contract_osi="AAPL251219C00190000",
                buy_contract_osi="MSFT251219C00195000",
                quantity=1,
                limit_price=Decimal("2.50"),
            )
        self.client.perform_multi_leg_preflight_calculation.assert_not_called()

    @pytest.mark.asyncio
    async def test_gtd_with_expiration_time_async(self) -> None:
        exp = datetime.now(timezone.utc) + timedelta(days=30)
        await self.client.preflight_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.GTD,
            expiration_time=exp,
        )
        request, _ = (
            self.client.perform_multi_leg_preflight_calculation.call_args[0]
        )
        assert request.expiration.time_in_force == TimeInForce.GTD
        assert request.expiration.expiration_time == exp

    @pytest.mark.asyncio
    async def test_invalid_strike_order_raises_locally(self) -> None:
        with pytest.raises(ValueError, match="buy_strike < sell_strike"):
            await self.client.preflight_call_debit_spread(
                sell_contract_osi="AAPL251219C00195000",
                buy_contract_osi="AAPL251219C00200000",
                quantity=1,
                limit_price=Decimal("3.00"),
            )
        self.client.perform_multi_leg_preflight_calculation.assert_not_called()


# ---------------------------------------------------------------------------
# Client.place_*_spread integration — async
# ---------------------------------------------------------------------------


class TestSpreadPlacementClientAsync:
    def setup_method(self) -> None:
        from public_api_sdk.async_public_api_client import AsyncPublicApiClient

        self.mock_order = MagicMock()
        self.client = MagicMock()
        self.client.place_multileg_order = AsyncMock(return_value=self.mock_order)
        for name in (
            "place_call_credit_spread",
            "place_call_debit_spread",
            "place_put_credit_spread",
            "place_put_debit_spread",
        ):
            setattr(
                self.client,
                name,
                getattr(AsyncPublicApiClient, name).__get__(self.client),
            )

    @pytest.mark.asyncio
    async def test_call_credit_spread_async(self) -> None:
        result = await self.client.place_call_credit_spread(
            sell_contract_osi="AAPL251219C00190000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("2.50"),
            order_id=VALID_ORDER_ID,
        )
        assert result is self.mock_order
        request, _ = self.client.place_multileg_order.call_args[0]
        assert isinstance(request, MultilegOrderRequest)
        assert request.order_id == VALID_ORDER_ID
        assert request.limit_price == Decimal("-2.50")

    @pytest.mark.asyncio
    async def test_put_debit_spread_async(self) -> None:
        await self.client.place_put_debit_spread(
            sell_contract_osi="AAPL251219P00180000",
            buy_contract_osi="AAPL251219P00185000",
            quantity=2,
            limit_price=Decimal("2.10"),
            account_id="ACC123",
        )
        request, account_id = self.client.place_multileg_order.call_args[0]
        assert UUID(request.order_id).version == 4
        assert request.limit_price == Decimal("2.10")
        assert account_id == "ACC123"

    @pytest.mark.asyncio
    async def test_call_debit_spread_async(self) -> None:
        await self.client.place_call_debit_spread(
            sell_contract_osi="AAPL251219C00200000",
            buy_contract_osi="AAPL251219C00195000",
            quantity=1,
            limit_price=Decimal("3.00"),
            order_id=VALID_ORDER_ID,
        )
        request, _ = self.client.place_multileg_order.call_args[0]
        assert request.limit_price == Decimal("3.00")

    @pytest.mark.asyncio
    async def test_put_credit_spread_async(self) -> None:
        await self.client.place_put_credit_spread(
            sell_contract_osi="AAPL251219P00185000",
            buy_contract_osi="AAPL251219P00180000",
            quantity=1,
            limit_price=Decimal("1.20"),
            order_id=VALID_ORDER_ID,
        )
        request, _ = self.client.place_multileg_order.call_args[0]
        assert request.limit_price == Decimal("-1.20")

    @pytest.mark.asyncio
    async def test_invalid_strike_order_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="buy_strike < sell_strike"):
            await self.client.place_call_debit_spread(
                sell_contract_osi="AAPL251219C00195000",
                buy_contract_osi="AAPL251219C00200000",
                quantity=1,
                limit_price=Decimal("3.00"),
                order_id=VALID_ORDER_ID,
            )
        self.client.place_multileg_order.assert_not_called()
