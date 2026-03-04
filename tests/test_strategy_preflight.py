"""Tests for StrategyPreflight, AsyncStrategyPreflight, and helpers."""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from public_api_sdk.models.option import (
    LegInstrumentType,
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
    _build_osi,
    _make_credit_spread_request,
    _make_debit_spread_request,
)
from public_api_sdk.async_strategy_preflight import AsyncStrategyPreflight


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
