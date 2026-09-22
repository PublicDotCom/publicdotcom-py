"""Tests for the v2 order endpoints — `search_orders` / `get_order_v2` — and
their models (`OrderV2`, `Trade`, `OrderMarketSession`, `OrderSearchRequest`),
plus the `JOINT` account type added in the same spec revision.

Client tests patch ApiClient/AsyncApiClient and the auth managers at
construction time so no real HTTP calls are made, mirroring the other client
test modules.
"""

import logging
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.exceptions import NotFoundError
from public_api_sdk.models.account import Account, AccountType
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.order import (
    OpenCloseIndicator,
    Order,
    OrderInstrument,
    OrderMarketSession,
    OrderSearchRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    OrderV2,
    TimeInForce,
    Trade,
)

_ACCOUNT = "ACC123"
_ORDER_ID = "550e8400-e29b-41d4-a716-446655440000"


def _make_client(default_account: Optional[str] = _ACCOUNT) -> PublicApiClient:
    """Return a PublicApiClient with ApiClient and AuthManager patched out."""
    with (
        patch("public_api_sdk.public_api_client.ApiClient"),
        patch("public_api_sdk.public_api_client.AuthManager"),
    ):
        config = PublicApiClientConfiguration(default_account_number=default_account)
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )
    return client


def _make_async_client(
    default_account: Optional[str] = _ACCOUNT,
) -> AsyncPublicApiClient:
    """Return AsyncPublicApiClient with AsyncApiClient and AsyncAuthManager patched."""
    with (
        patch("public_api_sdk.async_public_api_client.AsyncApiClient"),
        patch("public_api_sdk.async_public_api_client.AsyncAuthManager"),
    ):
        config = AsyncPublicApiClientConfiguration(
            default_account_number=default_account
        )
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )
    client.auth_manager.refresh_token_if_needed = AsyncMock()
    return client


# ---------------------------------------------------------------------------
# Payload builders (shapes taken from the spec's GatewayTrade / GatewayOrderV2)
# ---------------------------------------------------------------------------


def _trade_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "quantity": "4",
        "price": "189.25",
        "side": "BUY",
        "tradeId": "trade-1",
        "timestamp": "2026-09-21T14:30:05Z",
    }
    payload.update(overrides)
    return payload


def _order_v2_payload(**overrides: Any) -> Dict[str, Any]:
    """A fully-populated filled equity LIMIT order with two partial fills."""
    payload: Dict[str, Any] = {
        "orderId": _ORDER_ID,
        "bracketId": None,
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "createdAt": "2026-09-21T14:30:00Z",
        "type": "LIMIT",
        "side": "BUY",
        "status": "FILLED",
        "quantity": "10",
        "expiration": {"timeInForce": "DAY"},
        "limitPrice": "190.00",
        "closedAt": "2026-09-21T14:30:07Z",
        "filledQuantity": "10",
        "averagePrice": "189.40",
        "equityMarketSession": "REGULAR",
        "filledAt": "2026-09-21T14:30:07Z",
        "lastModified": "2026-09-21T14:30:07Z",
        "trades": [
            _trade_payload(),
            _trade_payload(quantity="6", price="189.50", tradeId="trade-2"),
        ],
    }
    payload.update(overrides)
    return payload


def _orders_payload(*orders: Dict[str, Any]) -> Dict[str, Any]:
    return {"orders": list(orders)}


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class TestOrderMarketSession:
    def test_enum_values(self) -> None:
        assert OrderMarketSession.REGULAR.value == "REGULAR"
        assert OrderMarketSession.REST_OF_DAY.value == "REST_OF_DAY"
        assert OrderMarketSession.TWENTY_FOUR_HOURS.value == "TWENTY_FOUR_HOURS"

    def test_unknown_value_falls_back_with_warning(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level(logging.WARNING):
            session = OrderMarketSession("AFTER_HOURS_PLUS")
        assert session is OrderMarketSession.UNKNOWN
        assert "AFTER_HOURS_PLUS" in caplog.text


class TestTrade:
    def test_parses_full_payload(self) -> None:
        trade = Trade(**_trade_payload())
        assert trade.instrument.symbol == "AAPL"
        assert trade.instrument.type is InstrumentType.EQUITY
        assert trade.quantity == Decimal("4")
        assert trade.price == Decimal("189.25")
        assert trade.side is OrderSide.BUY
        assert trade.trade_id == "trade-1"
        assert trade.timestamp == datetime(2026, 9, 21, 14, 30, 5, tzinfo=timezone.utc)

    def test_instrument_is_required(self) -> None:
        payload = _trade_payload()
        del payload["instrument"]
        with pytest.raises(ValidationError):
            Trade(**payload)

    def test_minimal_payload_defaults_to_none(self) -> None:
        trade = Trade(**{"instrument": {"symbol": "AAPL", "type": "EQUITY"}})
        assert trade.quantity is None
        assert trade.price is None
        assert trade.side is None
        assert trade.trade_id is None
        assert trade.timestamp is None

    def test_round_trips_by_alias(self) -> None:
        trade = Trade(**_trade_payload())
        dumped = trade.model_dump(by_alias=True)
        assert dumped["tradeId"] == "trade-1"
        assert "trade_id" not in dumped


class TestOrderV2:
    def test_parses_full_payload(self) -> None:
        order = OrderV2(**_order_v2_payload())
        assert order.order_id == _ORDER_ID
        assert order.status is OrderStatus.FILLED
        assert order.type is OrderType.LIMIT
        assert order.expiration is not None
        assert order.expiration.time_in_force is TimeInForce.DAY
        assert order.limit_price == Decimal("190.00")
        assert order.filled_quantity == Decimal("10")
        assert order.average_price == Decimal("189.40")

    def test_parses_v2_only_fields(self) -> None:
        order = OrderV2(**_order_v2_payload())
        assert order.equity_market_session is OrderMarketSession.REGULAR
        assert order.filled_at == datetime(2026, 9, 21, 14, 30, 7, tzinfo=timezone.utc)
        assert order.last_modified == datetime(
            2026, 9, 21, 14, 30, 7, tzinfo=timezone.utc
        )
        assert order.replaced_at is None

    def test_parses_trades(self) -> None:
        order = OrderV2(**_order_v2_payload())
        assert order.trades is not None
        assert [t.trade_id for t in order.trades] == ["trade-1", "trade-2"]
        assert sum(t.quantity for t in order.trades if t.quantity) == Decimal("10")
        assert order.trades[1].price == Decimal("189.50")

    def test_is_a_superset_of_order(self) -> None:
        order = OrderV2(**_order_v2_payload())
        assert isinstance(order, Order)
        v1_fields = set(Order.model_fields)
        v2_fields = set(OrderV2.model_fields)
        assert v1_fields <= v2_fields
        assert v2_fields - v1_fields == {
            "equity_market_session",
            "filled_at",
            "replaced_at",
            "last_modified",
            "trades",
        }

    def test_v1_payload_parses_with_v2_fields_none(self) -> None:
        """A GatewayOrder-shaped payload (no v2 fields) is still a valid OrderV2."""
        payload = _order_v2_payload()
        for key in (
            "equityMarketSession",
            "filledAt",
            "replacedAt",
            "lastModified",
            "trades",
        ):
            payload.pop(key, None)
        order = OrderV2(**payload)
        assert order.equity_market_session is None
        assert order.filled_at is None
        assert order.trades is None

    def test_unknown_session_does_not_break_parsing(self) -> None:
        order = OrderV2(**_order_v2_payload(equityMarketSession="SOMETHING_NEW"))
        assert order.equity_market_session is OrderMarketSession.UNKNOWN

    def test_replaced_order_carries_replaced_at(self) -> None:
        order = OrderV2(
            **_order_v2_payload(
                status="REPLACED",
                replacedAt="2026-09-21T14:31:00Z",
                filledAt=None,
                trades=[],
            )
        )
        assert order.status is OrderStatus.REPLACED
        assert order.replaced_at == datetime(2026, 9, 21, 14, 31, tzinfo=timezone.utc)
        assert order.filled_at is None
        assert order.trades == []

    def test_bracket_id_flows_through(self) -> None:
        order = OrderV2(**_order_v2_payload(bracketId="parent-order"))
        assert order.bracket_id == "parent-order"

    def test_populates_by_snake_case_name(self) -> None:
        order = OrderV2(
            order_id=_ORDER_ID,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.MARKET,
            side=OrderSide.SELL,
            status=OrderStatus.NEW,
            equity_market_session=OrderMarketSession.REST_OF_DAY,
        )
        assert order.equity_market_session is OrderMarketSession.REST_OF_DAY


class TestOrderSearchRequestSerialization:
    def test_empty_request_serializes_to_empty_dict(self) -> None:
        assert OrderSearchRequest().model_dump(by_alias=True, exclude_none=True) == {}

    def test_fields_serialize_with_camel_case_aliases_and_enum_values(self) -> None:
        request = OrderSearchRequest(
            status=OrderStatus.FILLED,
            created_after=datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc),
            created_before=datetime(2026, 9, 21, 16, 0, tzinfo=timezone.utc),
            instruments=[
                OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                OrderInstrument(symbol="BTC", type=InstrumentType.CRYPTO),
            ],
            side=OrderSide.BUY,
            open_close_indicator=OpenCloseIndicator.OPEN,
            security_type=InstrumentType.EQUITY,
        )
        assert request.model_dump(by_alias=True, exclude_none=True) == {
            "status": "FILLED",
            "createdAfter": "2026-09-01T09:30:00+00:00",
            "createdBefore": "2026-09-21T16:00:00+00:00",
            "instruments": [
                {"symbol": "AAPL", "type": "EQUITY"},
                {"symbol": "BTC", "type": "CRYPTO"},
            ],
            "side": "BUY",
            "openCloseIndicator": "OPEN",
            "securityType": "EQUITY",
        }

    def test_timestamps_keep_their_offset(self) -> None:
        ny = timezone(timedelta(hours=-4))
        request = OrderSearchRequest(
            created_after=datetime(2026, 9, 1, 9, 30, tzinfo=ny)
        )
        dumped = request.model_dump(by_alias=True, exclude_none=True)
        assert dumped["createdAfter"] == "2026-09-01T09:30:00-04:00"

    def test_populate_by_camel_case_name(self) -> None:
        request = OrderSearchRequest.model_validate(
            {
                "createdAfter": "2026-09-01T09:30:00Z",
                "openCloseIndicator": "CLOSE",
                "securityType": "OPTION",
            }
        )
        assert request.created_after == datetime(2026, 9, 1, 9, 30, tzinfo=timezone.utc)
        assert request.open_close_indicator is OpenCloseIndicator.CLOSE
        assert request.security_type is InstrumentType.OPTION

    def test_security_type_covers_every_spec_value(self) -> None:
        spec_values = {
            "EQUITY",
            "OPTION",
            "MULTI_LEG_INSTRUMENT",
            "CRYPTO",
            "ALT",
            "TREASURY",
            "BOND",
            "INDEX",
        }
        assert {t.value for t in InstrumentType} == spec_values

    def test_status_excludes_client_side_unknown(self) -> None:
        with pytest.raises(ValidationError, match="not searchable"):
            OrderSearchRequest(status=OrderStatus.UNKNOWN)


class TestAccountTypeJoint:
    def test_joint_is_an_account_type(self) -> None:
        assert AccountType.JOINT.value == "JOINT"
        assert AccountType("JOINT") is AccountType.JOINT

    def test_joint_account_parses(self) -> None:
        account = Account(**{"accountId": "JNT1", "accountType": "JOINT"})
        assert account.account_type is AccountType.JOINT


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class TestGetOrderV2:
    def test_hits_v2_endpoint(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_order_v2_payload())
        order = client.get_order_v2(_ORDER_ID)
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/trading/{_ACCOUNT}/order/v2/{_ORDER_ID}"
        assert isinstance(order, OrderV2)
        assert order.trades is not None and len(order.trades) == 2

    def test_refreshes_token_first(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_order_v2_payload())
        client.get_order_v2(_ORDER_ID)
        client.auth_manager.refresh_token_if_needed.assert_called_once()

    def test_explicit_account_overrides_default(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_order_v2_payload())
        client.get_order_v2(_ORDER_ID, account_id="OTHER_ACC")
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/trading/OTHER_ACC/order/v2/{_ORDER_ID}"

    def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            client.get_order_v2(_ORDER_ID)

    def test_404_propagates_as_not_found(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(
            side_effect=NotFoundError("Order not found.", 404, {})
        )
        with pytest.raises(NotFoundError) as exc_info:
            client.get_order_v2(_ORDER_ID)
        assert exc_info.value.status_code == 404


class TestSearchOrders:
    def test_posts_empty_body_when_no_filters(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value=_orders_payload(_order_v2_payload()))
        orders = client.search_orders()
        url = client.api_client.post.call_args[0][0]
        assert url == f"/userapigateway/trading/{_ACCOUNT}/order/v2"
        assert client.api_client.post.call_args.kwargs["json_data"] == {}
        assert len(orders) == 1
        assert isinstance(orders[0], OrderV2)

    def test_passes_filters_as_camel_case_body(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value=_orders_payload())
        client.search_orders(
            OrderSearchRequest(
                status=OrderStatus.NEW,
                side=OrderSide.SELL,
                security_type=InstrumentType.OPTION,
                instruments=[
                    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
                ],
            )
        )
        body = client.api_client.post.call_args.kwargs["json_data"]
        assert body == {
            "status": "NEW",
            "side": "SELL",
            "securityType": "OPTION",
            "instruments": [{"symbol": "AAPL", "type": "EQUITY"}],
        }

    def test_returns_every_order_with_trades(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(
            return_value=_orders_payload(
                _order_v2_payload(),
                _order_v2_payload(orderId="second", status="NEW", trades=[]),
            )
        )
        orders = client.search_orders()
        assert [o.order_id for o in orders] == [_ORDER_ID, "second"]
        assert orders[0].trades is not None and len(orders[0].trades) == 2
        assert orders[1].trades == []
        assert orders[1].status is OrderStatus.NEW

    def test_empty_result_returns_empty_list(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value=_orders_payload())
        assert client.search_orders() == []

    def test_missing_orders_key_returns_empty_list(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value={})
        assert client.search_orders() == []

    def test_explicit_account_overrides_default(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value=_orders_payload())
        client.search_orders(account_id="OTHER_ACC")
        url = client.api_client.post.call_args[0][0]
        assert url == "/userapigateway/trading/OTHER_ACC/order/v2"

    def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            client.search_orders()

    def test_404_propagates_as_not_found(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(
            side_effect=NotFoundError("Account not found", 404, {})
        )
        with pytest.raises(NotFoundError):
            client.search_orders()


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class TestAsyncGetOrderV2:
    @pytest.mark.asyncio
    async def test_hits_v2_endpoint(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_order_v2_payload())
        order = await client.get_order_v2(_ORDER_ID)
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/trading/{_ACCOUNT}/order/v2/{_ORDER_ID}"
        assert order.equity_market_session is OrderMarketSession.REGULAR
        client.auth_manager.refresh_token_if_needed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_no_account_raises_value_error(self) -> None:
        client = _make_async_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            await client.get_order_v2(_ORDER_ID)

    @pytest.mark.asyncio
    async def test_404_propagates_as_not_found(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(
            side_effect=NotFoundError("Order not found.", 404, {})
        )
        with pytest.raises(NotFoundError):
            await client.get_order_v2(_ORDER_ID)


class TestAsyncSearchOrders:
    @pytest.mark.asyncio
    async def test_posts_empty_body_when_no_filters(self) -> None:
        client = _make_async_client()
        client.api_client.post = AsyncMock(
            return_value=_orders_payload(_order_v2_payload())
        )
        orders = await client.search_orders()
        url = client.api_client.post.call_args[0][0]
        assert url == f"/userapigateway/trading/{_ACCOUNT}/order/v2"
        assert client.api_client.post.call_args.kwargs["json_data"] == {}
        assert len(orders) == 1 and isinstance(orders[0], OrderV2)

    @pytest.mark.asyncio
    async def test_passes_filters_as_camel_case_body(self) -> None:
        client = _make_async_client()
        client.api_client.post = AsyncMock(return_value=_orders_payload())
        await client.search_orders(
            OrderSearchRequest(
                status=OrderStatus.FILLED,
                created_after=datetime(2026, 9, 1, tzinfo=timezone.utc),
                open_close_indicator=OpenCloseIndicator.CLOSE,
            )
        )
        body = client.api_client.post.call_args.kwargs["json_data"]
        assert body == {
            "status": "FILLED",
            "createdAfter": "2026-09-01T00:00:00+00:00",
            "openCloseIndicator": "CLOSE",
        }

    @pytest.mark.asyncio
    async def test_no_account_raises_value_error(self) -> None:
        client = _make_async_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            await client.search_orders()
