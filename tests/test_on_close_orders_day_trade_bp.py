"""Tests for the 2026-10-29 spec delta — on-close order types, day-trade buying
power, trade venue MIC, event-outcome floor strike and the bracket stop-loss."""

from decimal import Decimal
from typing import Any, Dict

import pytest
from pydantic import ValidationError

from public_api_sdk.models.event_contract import EventOutcome
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.order import (
    CancelAndReplaceRequest,
    Order,
    OrderClass,
    OrderExpirationRequest,
    OrderInstrument,
    OrderRequest,
    OrderSide,
    OrderType,
    OrderV2,
    PreflightRequest,
    StopLoss,
    TimeInForce,
    Trade,
)
from public_api_sdk.models.portfolio import BuyingPower, Portfolio

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"
OTHER_UUID = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"


def _order(**overrides: Any) -> OrderRequest:
    kwargs: Dict[str, Any] = {
        "order_id": VALID_UUID,
        "instrument": OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        "order_side": OrderSide.BUY,
        "order_type": OrderType.MARKET_ON_CLOSE,
        "expiration": OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        "quantity": Decimal("10"),
    }
    kwargs.update(overrides)
    return OrderRequest(**kwargs)


def _preflight(**overrides: Any) -> PreflightRequest:
    kwargs: Dict[str, Any] = {
        "instrument": OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        "order_side": OrderSide.BUY,
        "order_type": OrderType.MARKET_ON_CLOSE,
        "expiration": OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        "quantity": Decimal("10"),
    }
    kwargs.update(overrides)
    return PreflightRequest(**kwargs)


class TestOnCloseOrderTypes:
    def test_enum_values(self) -> None:
        assert OrderType.MARKET_ON_CLOSE.value == "MARKET_ON_CLOSE"
        assert OrderType.LIMIT_ON_CLOSE.value == "LIMIT_ON_CLOSE"
        assert OrderType("MARKET_ON_CLOSE") is OrderType.MARKET_ON_CLOSE
        assert OrderType("LIMIT_ON_CLOSE") is OrderType.LIMIT_ON_CLOSE

    def test_market_on_close_order_serializes(self) -> None:
        dumped = _order().model_dump(by_alias=True, exclude_none=True)
        assert dumped["orderType"] == "MARKET_ON_CLOSE"
        assert "limitPrice" not in dumped

    def test_limit_on_close_accepts_limit_price(self) -> None:
        dumped = _order(
            order_type=OrderType.LIMIT_ON_CLOSE, limit_price=Decimal("227.5")
        ).model_dump(by_alias=True, exclude_none=True)
        assert dumped["orderType"] == "LIMIT_ON_CLOSE"
        assert dumped["limitPrice"] == "227.50"

    def test_market_on_close_rejects_limit_price(self) -> None:
        with pytest.raises(ValidationError, match="LIMIT_ON_CLOSE"):
            _order(limit_price=Decimal("227.50"))

    @pytest.mark.parametrize(
        "order_type", [OrderType.MARKET_ON_CLOSE, OrderType.LIMIT_ON_CLOSE]
    )
    def test_on_close_rejects_stop_price(self, order_type: OrderType) -> None:
        with pytest.raises(ValidationError, match="stop_price"):
            _order(order_type=order_type, stop_price=Decimal("200"))

    def test_preflight_accepts_on_close_types(self) -> None:
        assert (
            _preflight().model_dump(by_alias=True, exclude_none=True)["orderType"]
            == "MARKET_ON_CLOSE"
        )
        dumped = _preflight(
            order_type=OrderType.LIMIT_ON_CLOSE, limit_price=Decimal("1.234")
        ).model_dump(by_alias=True, exclude_none=True)
        assert dumped["orderType"] == "LIMIT_ON_CLOSE"
        assert dumped["limitPrice"] == "1.23"

    def test_cancel_and_replace_accepts_on_close_types(self) -> None:
        request = CancelAndReplaceRequest(
            order_id=VALID_UUID,
            request_id=OTHER_UUID,
            order_type=OrderType.LIMIT_ON_CLOSE,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("5"),
            limit_price=Decimal("228"),
        )
        dumped = request.model_dump(by_alias=True, exclude_none=True)
        assert dumped["orderType"] == "LIMIT_ON_CLOSE"
        assert dumped["limitPrice"] == "228.00"

    @pytest.mark.parametrize(
        "order_type", [OrderType.MARKET_ON_CLOSE, OrderType.LIMIT_ON_CLOSE]
    )
    def test_bracket_entry_rejects_on_close_types(self, order_type: OrderType) -> None:
        with pytest.raises(ValidationError, match="entry order type"):
            _order(
                order_type=order_type,
                limit_price=(
                    Decimal("200") if order_type == OrderType.LIMIT_ON_CLOSE else None
                ),
                order_class=OrderClass.OTO,
                stop_loss=StopLoss(stop_price=Decimal("180")),
            )

    @pytest.mark.parametrize("raw", ["MARKET_ON_CLOSE", "LIMIT_ON_CLOSE"])
    def test_order_responses_parse_on_close_types(self, raw: str) -> None:
        payload = {
            "orderId": VALID_UUID,
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "type": raw,
            "side": "BUY",
            "status": "NEW",
            "quantity": "10",
        }
        assert Order.model_validate(payload).type == OrderType(raw)
        assert OrderV2.model_validate(payload).type == OrderType(raw)


class TestStopLoss:
    def test_stop_price_still_required(self) -> None:
        # The spec relaxes stopPrice for trailing stop-losses, but defines no
        # trailing fields yet, so a stop-loss without a stop price can't be sent.
        with pytest.raises(ValidationError, match="stop_price"):
            StopLoss()  # type: ignore[call-arg]

    def test_stop_and_limit_serialize(self) -> None:
        stop_loss = StopLoss(stop_price=Decimal("180"), limit_price=Decimal("179.5"))
        assert stop_loss.model_dump(by_alias=True) == {
            "stopPrice": "180.00",
            "limitPrice": "179.50",
        }


class TestDayTradeBuyingPower:
    _BASE = {
        "cashOnlyBuyingPower": "10000.00",
        "buyingPower": "20000.00",
        "optionsBuyingPower": "5000.00",
    }

    def test_parses_day_trade_buying_power(self) -> None:
        bp = BuyingPower.model_validate(
            {**self._BASE, "dayTradeBuyingPower": "80000.00"}
        )
        assert bp.day_trade_buying_power == Decimal("80000.00")

    def test_missing_day_trade_buying_power_is_none(self) -> None:
        # Required in the spec, optional in the SDK so older responses still parse.
        assert BuyingPower.model_validate(self._BASE).day_trade_buying_power is None

    def test_null_day_trade_buying_power_is_none(self) -> None:
        bp = BuyingPower.model_validate({**self._BASE, "dayTradeBuyingPower": None})
        assert bp.day_trade_buying_power is None

    def test_serializes_with_alias(self) -> None:
        bp = BuyingPower.model_validate({**self._BASE, "dayTradeBuyingPower": "1"})
        assert bp.model_dump(by_alias=True)["dayTradeBuyingPower"] == Decimal("1")

    def test_portfolio_exposes_day_trade_buying_power(self) -> None:
        portfolio = Portfolio.model_validate(
            {
                "accountId": "ACC123",
                "accountType": "BROKERAGE",
                "buyingPower": {**self._BASE, "dayTradeBuyingPower": "20000.00"},
                "equity": [],
                "positions": [],
                "orders": [],
            }
        )
        assert portfolio.buying_power.day_trade_buying_power == Decimal("20000.00")


class TestTradeMarketIdentificationCode:
    _TRADE = {
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "quantity": "4",
        "price": "189.25",
        "side": "BUY",
        "tradeId": "trade-1",
        "timestamp": "2026-10-29T14:30:05Z",
    }

    def test_parses_mic(self) -> None:
        trade = Trade.model_validate(
            {**self._TRADE, "marketIdentificationCode": "XNAS"}
        )
        assert trade.market_identification_code == "XNAS"
        assert trade.model_dump(by_alias=True)["marketIdentificationCode"] == "XNAS"

    def test_snake_case_accepted(self) -> None:
        trade = Trade.model_validate(
            {**self._TRADE, "market_identification_code": "XNYS"}
        )
        assert trade.market_identification_code == "XNYS"

    def test_missing_mic_is_none(self) -> None:
        assert Trade.model_validate(self._TRADE).market_identification_code is None


class TestEventOutcomeFloorStrike:
    def test_parses_floor_strike(self) -> None:
        outcome = EventOutcome.model_validate(
            {"outcomeId": "KXBALANCESHEET-EO26-6.6", "floorStrike": "6.6"}
        )
        assert outcome.floor_strike == Decimal("6.6")
        assert outcome.model_dump(by_alias=True)["floorStrike"] == Decimal("6.6")

    def test_missing_floor_strike_is_none(self) -> None:
        outcome = EventOutcome.model_validate({"outcomeId": "KXBALANCESHEET-EO26-6.6"})
        assert outcome.floor_strike is None
