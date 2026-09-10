"""Tests for bracket orders — `orderClass`, `takeProfit`, `stopLoss`, `bracketId`."""

from decimal import Decimal

import pytest
from pydantic import ValidationError

from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.order import (
    BRACKET_ORDER_CLASSES,
    EquityMarketSession,
    Order,
    OrderClass,
    OrderExpirationRequest,
    OrderInstrument,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    StopLoss,
    TakeProfit,
    TimeInForce,
)

VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _order(**overrides: object) -> OrderRequest:
    """Build an OrderRequest from a valid equity LIMIT base, with overrides."""
    kwargs = {
        "order_id": VALID_UUID,
        "instrument": OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        "order_side": OrderSide.BUY,
        "order_type": OrderType.LIMIT,
        "expiration": OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        "quantity": Decimal("10"),
    }
    kwargs.update(overrides)
    return OrderRequest(**kwargs)  # type: ignore[arg-type]


TAKE_PROFIT = TakeProfit(limit_price=Decimal("210.50"))
STOP_LOSS = StopLoss(stop_price=Decimal("180.00"))


class TestOrderClass:
    def test_enum_values(self) -> None:
        assert OrderClass.SIMPLE.value == "SIMPLE"
        assert OrderClass.BRACKET.value == "BRACKET"
        assert OrderClass.OCO.value == "OCO"
        assert OrderClass.OTO.value == "OTO"

    def test_bracket_classes_exclude_simple(self) -> None:
        assert BRACKET_ORDER_CLASSES == {
            OrderClass.BRACKET,
            OrderClass.OCO,
            OrderClass.OTO,
        }
        assert OrderClass.SIMPLE not in BRACKET_ORDER_CLASSES


class TestTakeProfit:
    def test_serializes_to_two_decimal_places(self) -> None:
        tp = TakeProfit(limit_price=Decimal("210.5"))
        assert tp.model_dump(by_alias=True) == {"limitPrice": "210.50"}

    def test_accepts_camel_case(self) -> None:
        tp = TakeProfit.model_validate({"limitPrice": "99.99"})
        assert tp.limit_price == Decimal("99.99")

    def test_limit_price_is_required(self) -> None:
        with pytest.raises(ValidationError):
            TakeProfit()  # type: ignore[call-arg]

    @pytest.mark.parametrize("price", ["0", "-1.50"])
    def test_rejects_non_positive_price(self, price: str) -> None:
        with pytest.raises(ValidationError, match="greater than 0"):
            TakeProfit(limit_price=Decimal(price))


class TestStopLoss:
    def test_stop_only_serializes_without_limit(self) -> None:
        sl = StopLoss(stop_price=Decimal("180"))
        assert sl.model_dump(by_alias=True, exclude_none=True) == {
            "stopPrice": "180.00"
        }

    def test_stop_limit_serializes_both(self) -> None:
        sl = StopLoss(stop_price=Decimal("180"), limit_price=Decimal("179.5"))
        assert sl.model_dump(by_alias=True, exclude_none=True) == {
            "stopPrice": "180.00",
            "limitPrice": "179.50",
        }

    def test_accepts_camel_case(self) -> None:
        sl = StopLoss.model_validate({"stopPrice": "10", "limitPrice": "9.5"})
        assert sl.stop_price == Decimal("10")
        assert sl.limit_price == Decimal("9.5")

    def test_stop_price_is_required(self) -> None:
        with pytest.raises(ValidationError):
            StopLoss(limit_price=Decimal("179.50"))  # type: ignore[call-arg]

    @pytest.mark.parametrize("field", ["stop_price", "limit_price"])
    def test_rejects_non_positive_prices(self, field: str) -> None:
        kwargs = {"stop_price": Decimal("180")}
        kwargs[field] = Decimal("0")
        with pytest.raises(ValidationError, match="greater than 0"):
            StopLoss(**kwargs)  # type: ignore[arg-type]


class TestBracketOrderRequest:
    def test_bracket_serializes_all_three_fields(self) -> None:
        order = _order(
            order_class=OrderClass.BRACKET,
            take_profit=TAKE_PROFIT,
            stop_loss=STOP_LOSS,
        )
        payload = order.model_dump(by_alias=True, exclude_none=True)
        assert payload["orderClass"] == "BRACKET"
        assert payload["takeProfit"] == {"limitPrice": "210.50"}
        assert payload["stopLoss"] == {"stopPrice": "180.00"}

    def test_simple_order_omits_bracket_fields(self) -> None:
        payload = _order().model_dump(by_alias=True, exclude_none=True)
        assert "orderClass" not in payload
        assert "takeProfit" not in payload
        assert "stopLoss" not in payload

    def test_explicit_simple_class_needs_no_exit_legs(self) -> None:
        order = _order(order_class=OrderClass.SIMPLE)
        assert order.order_class is OrderClass.SIMPLE

    def test_accepts_camel_case_payload(self) -> None:
        order = OrderRequest.model_validate(
            {
                "orderId": VALID_UUID,
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "orderSide": "BUY",
                "orderType": "MARKET",
                "expiration": {"timeInForce": "DAY"},
                "quantity": "5",
                "orderClass": "OTO",
                "stopLoss": {"stopPrice": "180"},
            }
        )
        assert order.order_class is OrderClass.OTO
        assert order.stop_loss is not None
        assert order.stop_loss.stop_price == Decimal("180")

    @pytest.mark.parametrize(
        "order_class", [OrderClass.BRACKET, OrderClass.OCO, OrderClass.OTO]
    )
    def test_take_profit_alone_is_enough(self, order_class: OrderClass) -> None:
        order = _order(order_class=order_class, take_profit=TAKE_PROFIT)
        assert order.stop_loss is None

    @pytest.mark.parametrize(
        "order_class", [OrderClass.BRACKET, OrderClass.OCO, OrderClass.OTO]
    )
    def test_stop_loss_alone_is_enough(self, order_class: OrderClass) -> None:
        order = _order(order_class=order_class, stop_loss=STOP_LOSS)
        assert order.take_profit is None

    @pytest.mark.parametrize(
        "order_class", [OrderClass.BRACKET, OrderClass.OCO, OrderClass.OTO]
    )
    def test_bracket_class_requires_an_exit_leg(self, order_class: OrderClass) -> None:
        with pytest.raises(ValidationError, match="at least one of"):
            _order(order_class=order_class)

    @pytest.mark.parametrize(
        "exit_leg", [{"take_profit": TAKE_PROFIT}, {"stop_loss": STOP_LOSS}]
    )
    def test_exit_legs_rejected_without_bracket_class(self, exit_leg: dict) -> None:
        with pytest.raises(ValidationError, match="require `order_class`"):
            _order(**exit_leg)

    def test_exit_legs_rejected_for_explicit_simple_class(self) -> None:
        with pytest.raises(ValidationError, match="require `order_class`"):
            _order(order_class=OrderClass.SIMPLE, take_profit=TAKE_PROFIT)

    @pytest.mark.parametrize(
        "instrument_type", [InstrumentType.CRYPTO, InstrumentType.BOND]
    )
    def test_rejects_unsupported_instrument_types(
        self, instrument_type: InstrumentType
    ) -> None:
        with pytest.raises(ValidationError, match="EQUITY and OPTION"):
            _order(
                order_class=OrderClass.BRACKET,
                take_profit=TAKE_PROFIT,
                instrument=OrderInstrument(symbol="BTC", type=instrument_type),
            )

    def test_allows_option_instrument(self) -> None:
        order = _order(
            order_class=OrderClass.BRACKET,
            take_profit=TAKE_PROFIT,
            instrument=OrderInstrument(
                symbol="AAPL251219C00200000", type=InstrumentType.OPTION
            ),
        )
        assert order.instrument.type is InstrumentType.OPTION

    def test_rejects_amount(self) -> None:
        with pytest.raises(ValidationError, match="`amount` is not supported"):
            _order(
                order_class=OrderClass.BRACKET,
                take_profit=TAKE_PROFIT,
                quantity=None,
                amount=Decimal("500.00"),
            )

    def test_rejects_fractional_quantity(self) -> None:
        with pytest.raises(ValidationError, match="whole-share `quantity`"):
            _order(
                order_class=OrderClass.BRACKET,
                take_profit=TAKE_PROFIT,
                quantity=Decimal("1.5"),
            )

    def test_rejects_non_core_market_session(self) -> None:
        with pytest.raises(ValidationError, match="CORE market session"):
            _order(
                order_class=OrderClass.BRACKET,
                take_profit=TAKE_PROFIT,
                equity_market_session=EquityMarketSession.EXTENDED,
            )

    def test_allows_explicit_core_market_session(self) -> None:
        order = _order(
            order_class=OrderClass.BRACKET,
            take_profit=TAKE_PROFIT,
            equity_market_session=EquityMarketSession.CORE,
        )
        assert order.equity_market_session is EquityMarketSession.CORE

    def test_allows_omitted_market_session(self) -> None:
        order = _order(order_class=OrderClass.BRACKET, take_profit=TAKE_PROFIT)
        assert order.equity_market_session is None

    @pytest.mark.parametrize("order_type", [OrderType.LIMIT, OrderType.MARKET])
    @pytest.mark.parametrize("order_class", [OrderClass.BRACKET, OrderClass.OTO])
    def test_allows_limit_and_market_entries(
        self, order_class: OrderClass, order_type: OrderType
    ) -> None:
        order = _order(
            order_class=order_class, take_profit=TAKE_PROFIT, order_type=order_type
        )
        assert order.order_type is order_type

    def test_oco_allows_limit_entry(self) -> None:
        order = _order(
            order_class=OrderClass.OCO,
            take_profit=TAKE_PROFIT,
            order_type=OrderType.LIMIT,
        )
        assert order.order_type is OrderType.LIMIT

    def test_oco_rejects_market_entry(self) -> None:
        with pytest.raises(ValidationError, match="must be LIMIT, not MARKET"):
            _order(
                order_class=OrderClass.OCO,
                take_profit=TAKE_PROFIT,
                order_type=OrderType.MARKET,
            )

    @pytest.mark.parametrize(
        "order_class", [OrderClass.BRACKET, OrderClass.OCO, OrderClass.OTO]
    )
    def test_rejects_stop_entry_types(self, order_class: OrderClass) -> None:
        with pytest.raises(ValidationError, match="entry order type"):
            _order(
                order_class=order_class,
                take_profit=TAKE_PROFIT,
                order_type=OrderType.STOP,
                stop_price=Decimal("175.00"),
            )

    def test_simple_orders_still_allow_stop_entry(self) -> None:
        """The entry-type restriction must not leak onto standalone orders."""
        order = _order(order_type=OrderType.STOP, stop_price=Decimal("175.00"))
        assert order.order_type is OrderType.STOP


class TestOrderBracketId:
    def _order_payload(self, **extra: object) -> dict:
        payload = {
            "orderId": VALID_UUID,
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "type": "LIMIT",
            "side": "BUY",
            "status": "NEW",
        }
        payload.update(extra)
        return payload

    def test_parses_bracket_id(self) -> None:
        order = Order.model_validate(self._order_payload(bracketId=VALID_UUID))
        assert order.bracket_id == VALID_UUID

    def test_bracket_id_is_none_for_standalone_orders(self) -> None:
        order = Order.model_validate(self._order_payload())
        assert order.bracket_id is None
        assert order.status is OrderStatus.NEW

    def test_bracket_id_serializes_to_camel_case(self) -> None:
        order = Order.model_validate(self._order_payload(bracketId=VALID_UUID))
        payload = order.model_dump(by_alias=True, exclude_none=True)
        assert payload["bracketId"] == VALID_UUID

    def test_legs_share_the_entry_order_id(self) -> None:
        """All legs of one bracket carry the entry order's id as bracket_id."""
        entry = Order.model_validate(self._order_payload(bracketId=VALID_UUID))
        exit_leg = Order.model_validate(
            self._order_payload(
                orderId="7c9e6679-7425-40de-944b-e07fc1f90ae7",
                bracketId=VALID_UUID,
                type="STOP",
            )
        )
        assert entry.bracket_id == exit_leg.bracket_id == entry.order_id
