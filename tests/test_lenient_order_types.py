"""Order responses with order types and enum values the SDK did not know.

The API returns TRAILING_STOP and TRAILING_STOP_LIMIT for the stop-loss leg of
a BRACKET or OTO order placed with ``stopLoss.trailingStop``. One such order
anywhere in a response used to fail the whole call (get_portfolio, get_order,
search_orders) with a pydantic ValidationError on ``Order.type``.

Client tests patch ApiClient and AuthManager so no real HTTP calls are made.
"""

from decimal import Decimal
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.models import _lenient, stream
from public_api_sdk.models.account import AccountType
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.option import PreflightMultiLegRequest
from public_api_sdk.models.order import (
    TRAILING_STOP_ORDER_TYPES,
    CancelAndReplaceRequest,
    LegInstrumentType,
    OpenCloseIndicator,
    Order,
    OrderExpirationRequest,
    OrderInstrument,
    OrderMarketSession,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    OrderV2,
    PreflightRequest,
    TimeInForce,
    TrailingStop,
    TrailingStopType,
)
from public_api_sdk.models.portfolio import AssetType, Portfolio

_ACCOUNT = "ACC123"
_ENTRY_ID = "6f1c2a4e-8b3d-4c5e-9a7f-1b2c3d4e5f60"
_TRAILING_ID = "0d2abd8d-3625-4c83-a806-98abf35567cc"


def _make_client() -> PublicApiClient:
    with (
        patch("public_api_sdk.public_api_client.ApiClient"),
        patch("public_api_sdk.public_api_client.AuthManager"),
    ):
        return PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=PublicApiClientConfiguration(default_account_number=_ACCOUNT),
        )


def _make_async_client() -> AsyncPublicApiClient:
    with (
        patch("public_api_sdk.async_public_api_client.AsyncApiClient"),
        patch("public_api_sdk.async_public_api_client.AsyncAuthManager"),
    ):
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=AsyncPublicApiClientConfiguration(default_account_number=_ACCOUNT),
        )
    client.auth_manager.refresh_token_if_needed = AsyncMock()
    return client


def _trailing_order(**overrides: Any) -> Dict[str, Any]:
    """The trailing stop-loss leg of a bracket, as the API returns it."""
    payload: Dict[str, Any] = {
        "orderId": _TRAILING_ID,
        "bracketId": _ENTRY_ID,
        "instrument": {"symbol": "NVDA", "type": "EQUITY"},
        "createdAt": "2026-11-24T14:30:00Z",
        "type": "TRAILING_STOP_LIMIT",
        "side": "SELL",
        "status": "NEW",
        "quantity": "10",
        "expiration": {
            "timeInForce": "GTD",
            "expirationTime": "2026-12-24T21:00:00Z",
        },
        "stopPrice": "172.14",
        "limitPrice": "171.64",
        "trailingStop": {
            "type": "PERCENTAGE",
            "value": "0.05",
            "limitOffset": "0.50",
        },
        "highWatermark": "181.20",
    }
    payload.update(overrides)
    return payload


def _limit_order() -> Dict[str, Any]:
    return {
        "orderId": _ENTRY_ID,
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "type": "LIMIT",
        "side": "BUY",
        "status": "NEW",
        "quantity": "1",
        "expiration": {"timeInForce": "DAY"},
        "limitPrice": "190.00",
    }


def _portfolio(*orders: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "accountId": _ACCOUNT,
        "accountType": "BROKERAGE",
        "buyingPower": {
            "cashOnlyBuyingPower": "1000.00",
            "buyingPower": "1000.00",
            "optionsBuyingPower": "1000.00",
        },
        "equity": [{"type": "STOCK", "value": "1812.00"}],
        "positions": [
            {
                "instrument": {"symbol": "NVDA", "name": "NVIDIA", "type": "EQUITY"},
                "quantity": "10",
            }
        ],
        "orders": list(orders),
    }


@pytest.mark.parametrize("order_type", ["TRAILING_STOP", "TRAILING_STOP_LIMIT"])
class TestTrailingStopResponsesParse:
    def test_get_portfolio(self, order_type: str) -> None:
        client = _make_client()
        client.api_client.get.return_value = _portfolio(
            _limit_order(), _trailing_order(type=order_type)
        )
        portfolio = client.get_portfolio()
        assert [o.type for o in portfolio.orders] == [
            OrderType.LIMIT,
            OrderType(order_type),
        ]

    def test_get_order(self, order_type: str) -> None:
        client = _make_client()
        client.api_client.get.return_value = _trailing_order(type=order_type)
        order = client.get_order(_TRAILING_ID)
        assert order.type is OrderType(order_type)

    def test_search_orders(self, order_type: str) -> None:
        client = _make_client()
        client.api_client.post.return_value = {
            "orders": [_limit_order(), _trailing_order(type=order_type)]
        }
        orders = client.search_orders()
        assert [o.order_id for o in orders] == [_ENTRY_ID, _TRAILING_ID]
        assert orders[1].type is OrderType(order_type)

    @pytest.mark.asyncio
    async def test_async_client(self, order_type: str) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(
            side_effect=[
                _portfolio(_trailing_order(type=order_type)),
                _trailing_order(type=order_type),
            ]
        )
        client.api_client.post = AsyncMock(
            return_value={"orders": [_trailing_order(type=order_type)]}
        )
        portfolio = await client.get_portfolio()
        order = await client.get_order(_TRAILING_ID)
        orders = await client.search_orders()
        for parsed in (portfolio.orders[0], order, orders[0]):
            assert parsed.type is OrderType(order_type)

    def test_trailing_fields_are_populated(self, order_type: str) -> None:
        order = OrderV2(**_trailing_order(type=order_type))
        assert order.trailing_stop == TrailingStop(
            type=TrailingStopType.PERCENTAGE,
            value=Decimal("0.05"),
            limit_offset=Decimal("0.50"),
        )
        assert order.trailing_stop.type is TrailingStopType.PERCENTAGE
        assert order.high_watermark == Decimal("181.20")
        assert order.bracket_id == _ENTRY_ID
        assert order.expiration is not None
        assert order.expiration.time_in_force is TimeInForce.GTD


class TestTrailingStop:
    def test_amount_trail(self) -> None:
        order = Order(
            **_trailing_order(
                type="TRAILING_STOP",
                trailingStop={"type": "AMOUNT", "value": "2.50"},
                stopPrice=None,
                limitPrice=None,
            )
        )
        assert order.trailing_stop is not None
        assert order.trailing_stop.type is TrailingStopType.AMOUNT
        assert order.trailing_stop.value == Decimal("2.50")
        assert order.trailing_stop.limit_offset is None

    def test_absent_on_other_orders(self) -> None:
        order = Order(**_limit_order())
        assert order.trailing_stop is None
        assert order.high_watermark is None

    def test_unknown_trail_type_kept(self) -> None:
        order = Order(**_trailing_order(trailingStop={"type": "TICKS", "value": "3"}))
        assert order.trailing_stop is not None
        assert order.trailing_stop.type == "TICKS"

    def test_dumps_by_alias(self) -> None:
        dumped = Order(**_trailing_order()).model_dump(by_alias=True, mode="json")
        assert dumped["type"] == "TRAILING_STOP_LIMIT"
        assert dumped["trailingStop"] == {
            "type": "PERCENTAGE",
            "value": "0.05",
            "limitOffset": "0.50",
        }
        assert dumped["highWatermark"] == "181.20"

    def test_stream_uses_the_same_model(self) -> None:
        assert stream.StreamTrailingStop is TrailingStop


def _unknown_order() -> Dict[str, Any]:
    """An order where every enum field has a value the SDK has never seen."""
    return {
        "orderId": _TRAILING_ID,
        "instrument": {"symbol": "XYZ", "type": "WARRANT"},
        "type": "SOMETHING_NEW",
        "side": "SELL_SHORT_EXEMPT",
        "status": "PARKED",
        "quantity": "3",
        "expiration": {"timeInForce": "GTC"},
        "openCloseIndicator": "ROLL",
        "equityMarketSession": "OVERNIGHT",
        "legs": [
            {
                "instrument": {"symbol": "XYZ", "type": "FUTURE"},
                "side": "SELL_SHORT_EXEMPT",
                "openCloseIndicator": "ROLL",
                "ratioQuantity": 1,
            }
        ],
        "trades": [
            {
                "instrument": {"symbol": "XYZ", "type": "WARRANT"},
                "quantity": "1",
                "price": "1.00",
                "side": "SELL_SHORT_EXEMPT",
            }
        ],
    }


class TestUnknownValuesParse:
    def test_order_keeps_raw_strings(self) -> None:
        order = OrderV2(**_unknown_order())
        assert order.type == "SOMETHING_NEW"
        assert not isinstance(order.type, OrderType)
        assert order.side == "SELL_SHORT_EXEMPT"
        assert order.instrument.type == "WARRANT"
        assert order.expiration is not None
        assert order.expiration.time_in_force == "GTC"
        assert order.open_close_indicator == "ROLL"
        # status and the v2 session already had an UNKNOWN fallback; unchanged
        assert order.status is OrderStatus.UNKNOWN
        assert order.equity_market_session is OrderMarketSession.UNKNOWN

    def test_legs_and_trades_keep_raw_strings(self) -> None:
        order = OrderV2(**_unknown_order())
        assert order.legs is not None
        leg = order.legs[0]
        assert leg.instrument.type == "FUTURE"
        assert leg.side == "SELL_SHORT_EXEMPT"
        assert leg.open_close_indicator == "ROLL"
        assert order.trades is not None
        trade = order.trades[0]
        assert trade.side == "SELL_SHORT_EXEMPT"
        assert trade.instrument.type == "WARRANT"

    def test_round_trips(self) -> None:
        order = OrderV2(**_unknown_order())
        dumped = order.model_dump(by_alias=True, mode="json")
        assert dumped["type"] == "SOMETHING_NEW"
        assert dumped["instrument"] == {"symbol": "XYZ", "type": "WARRANT"}
        assert OrderV2(**dumped).type == "SOMETHING_NEW"
        assert order.model_dump()["type"] == "SOMETHING_NEW"

    def test_search_orders_with_unknown_order(self) -> None:
        client = _make_client()
        client.api_client.post.return_value = {
            "orders": [_limit_order(), _unknown_order()]
        }
        orders = client.search_orders()
        assert [o.type for o in orders] == [OrderType.LIMIT, "SOMETHING_NEW"]

    def test_portfolio_keeps_raw_strings(self) -> None:
        payload = _portfolio(_unknown_order())
        payload["accountType"] = "CUSTODIAL"
        payload["equity"] = [{"type": "FUTURES", "value": "10.00"}]
        payload["positions"][0]["instrument"]["type"] = "FUTURE"
        portfolio = Portfolio(**payload)
        assert portfolio.account_type == "CUSTODIAL"
        assert portfolio.equity[0].type == "FUTURES"
        assert portfolio.positions[0].instrument.type == "FUTURE"
        assert portfolio.orders[0].type == "SOMETHING_NEW"
        portfolio.model_dump(by_alias=True, mode="json")


class TestKnownValuesStillCoerce:
    @pytest.mark.parametrize(
        "order_type",
        ["MARKET", "LIMIT", "STOP", "STOP_LIMIT", "MARKET_ON_CLOSE", "LIMIT_ON_CLOSE"],
    )
    def test_order_type(self, order_type: str) -> None:
        order = Order(**_trailing_order(type=order_type))
        assert order.type is OrderType(order_type)

    def test_other_order_fields(self) -> None:
        order = OrderV2(
            **_trailing_order(
                openCloseIndicator="CLOSE",
                equityMarketSession="REGULAR",
                legs=[
                    {
                        "instrument": {"symbol": "NVDA", "type": "OPTION"},
                        "side": "BUY",
                        "openCloseIndicator": "OPEN",
                    }
                ],
                trades=[
                    {
                        "instrument": {"symbol": "NVDA", "type": "EQUITY"},
                        "side": "SELL",
                    }
                ],
            )
        )
        assert order.side is OrderSide.SELL
        assert order.instrument.type is InstrumentType.EQUITY
        assert order.expiration is not None
        assert order.expiration.time_in_force is TimeInForce.GTD
        assert order.open_close_indicator is OpenCloseIndicator.CLOSE
        assert order.equity_market_session is OrderMarketSession.REGULAR
        assert order.legs is not None
        assert order.legs[0].instrument.type is LegInstrumentType.OPTION
        assert order.legs[0].side is OrderSide.BUY
        assert order.legs[0].open_close_indicator is OpenCloseIndicator.OPEN
        assert order.trades is not None
        assert order.trades[0].side is OrderSide.SELL
        assert order.trades[0].instrument.type is InstrumentType.EQUITY

    def test_portfolio_fields(self) -> None:
        portfolio = Portfolio(**_portfolio(_limit_order()))
        assert portfolio.account_type is AccountType.BROKERAGE
        assert portfolio.equity[0].type is AssetType.STOCK
        assert portfolio.positions[0].instrument.type is InstrumentType.EQUITY

    def test_order_accepts_a_request_instrument(self) -> None:
        payload = _limit_order()
        payload["instrument"] = OrderInstrument(
            symbol="AAPL", type=InstrumentType.EQUITY
        )
        order = Order(**payload)
        assert isinstance(order.instrument, OrderInstrument)
        assert order.instrument.type is InstrumentType.EQUITY


def _order_request(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument": OrderInstrument(symbol="NVDA", type=InstrumentType.EQUITY),
        "order_side": OrderSide.SELL,
        "order_type": OrderType.STOP,
        "expiration": OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        "quantity": Decimal("10"),
        "stop_price": Decimal("170.00"),
    }
    payload.update(overrides)
    return payload


class TestRequestModelsStayStrict:
    @pytest.mark.parametrize(
        "order_type",
        ["SOMETHING_NEW", "TRAILING_STOP", "TRAILING_STOP_LIMIT"],
    )
    def test_order_and_preflight_requests_reject(self, order_type: str) -> None:
        with pytest.raises(ValidationError):
            OrderRequest(order_id=_TRAILING_ID, **_order_request(order_type=order_type))
        with pytest.raises(ValidationError):
            PreflightRequest(**_order_request(order_type=order_type))

    @pytest.mark.parametrize("order_type", sorted(TRAILING_STOP_ORDER_TYPES))
    def test_trailing_rejection_explains_why(self, order_type: OrderType) -> None:
        with pytest.raises(ValidationError, match="stop-loss leg of a BRACKET or OTO"):
            OrderRequest(order_id=_TRAILING_ID, **_order_request(order_type=order_type))

    @pytest.mark.parametrize(
        "order_type",
        ["SOMETHING_NEW", "TRAILING_STOP", "TRAILING_STOP_LIMIT"],
    )
    def test_replace_request_rejects(self, order_type: str) -> None:
        with pytest.raises(ValidationError):
            CancelAndReplaceRequest(
                order_id=_TRAILING_ID,
                request_id=_ENTRY_ID,
                order_type=order_type,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("10"),
                stop_price=Decimal("170.00"),
            )

    @pytest.mark.parametrize("order_type", ["TRAILING_STOP", "TRAILING_STOP_LIMIT"])
    def test_multileg_request_rejects(self, order_type: str) -> None:
        with pytest.raises(ValidationError):
            PreflightMultiLegRequest(
                order_type=order_type,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=1,
                limit_price=Decimal("1.00"),
                legs=[],
            )

    def test_other_request_enums_reject_unknown_values(self) -> None:
        with pytest.raises(ValidationError):
            OrderRequest(
                order_id=_TRAILING_ID, **_order_request(order_side="SELL_SHORT")
            )
        with pytest.raises(ValidationError):
            OrderInstrument(symbol="XYZ", type="WARRANT")
        with pytest.raises(ValidationError):
            OrderExpirationRequest(time_in_force="GTC")

    def test_known_order_types_still_accepted(self) -> None:
        request = OrderRequest(order_id=_TRAILING_ID, **_order_request())
        assert request.order_type is OrderType.STOP
        assert request.model_dump(by_alias=True)["orderType"] == "STOP"


class TestSharedLenientHelpers:
    def test_stream_reuses_the_shared_annotations(self) -> None:
        for name in (
            "LenientOrderType",
            "LenientOrderSide",
            "LenientInstrumentType",
            "LenientLegInstrumentType",
            "LenientTimeInForce",
            "LenientMarketSession",
            "LenientOpenCloseIndicator",
        ):
            assert getattr(stream, name) is getattr(_lenient, name)

    def test_streamed_trailing_order_parses(self) -> None:
        streamed = stream.StreamOrder(
            orderId=_TRAILING_ID,
            accountNumber="5LF00001",
            version=3,
            instrument={"symbol": "NVDA", "type": "EQUITY"},
            type="TRAILING_STOP",
            side="SELL",
            status="NEW",
            trailingStop={"type": "PERCENTAGE", "value": "0.05"},
        )
        assert streamed.type is OrderType.TRAILING_STOP
        assert streamed.trailing_stop is not None
        assert streamed.trailing_stop.type is TrailingStopType.PERCENTAGE
