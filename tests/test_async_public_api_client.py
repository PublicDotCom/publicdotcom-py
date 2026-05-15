"""Tests for AsyncPublicApiClient API methods.

All tests patch AsyncApiClient and AsyncAuthManager at construction time so no
real HTTP calls are made.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    InstrumentType,
    OrderInstrument,
)
from public_api_sdk.models.account import AccountsResponse
from public_api_sdk.models.async_new_order import AsyncNewOrder
from public_api_sdk.models.historic_data import Bar, BarAggregation, BarPeriod, BarsResponse
from public_api_sdk.models.history import HistoryRequest, HistoryResponsePage
from public_api_sdk.models.instrument import Instrument
from public_api_sdk.models.option import GreeksResponse
from public_api_sdk.models.order import (
    CancelAndReplaceRequest,
    EquityMarketSession,
    OpenCloseIndicator,
    Order,
    OrderExpirationRequest,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PreflightRequest,
    PreflightResponse,
    TimeInForce,
)
from public_api_sdk.models.portfolio import Portfolio
from public_api_sdk.models.quote import Quote


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ACCOUNT = "ACC123"
_VALID_UUID = "550e8400-e29b-41d4-a716-446655440000"


def _make_client(default_account: Optional[str] = _ACCOUNT) -> AsyncPublicApiClient:
    """Return AsyncPublicApiClient with AsyncApiClient and AsyncAuthManager patched."""
    with patch("public_api_sdk.async_public_api_client.AsyncApiClient"), patch(
        "public_api_sdk.async_public_api_client.AsyncAuthManager"
    ):
        config = AsyncPublicApiClientConfiguration(
            default_account_number=default_account
        )
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )
    # Auth manager methods need to be async mocks
    client.auth_manager.refresh_token_if_needed = AsyncMock()
    client.auth_manager.revoke_current_token = AsyncMock()
    return client


def _order_payload(order_id: str = "ORDER-123", status: str = "NEW") -> dict:
    return {
        "orderId": order_id,
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "type": "LIMIT",
        "side": "BUY",
        "status": status,
        "quantity": "10",
    }


def _portfolio_payload(account_id: str = _ACCOUNT) -> dict:
    return {
        "accountId": account_id,
        "accountType": "BROKERAGE",
        "buyingPower": {
            "cashOnlyBuyingPower": "10000.00",
            "buyingPower": "20000.00",
            "optionsBuyingPower": "5000.00",
        },
        "equity": [],
        "positions": [],
        "orders": [],
    }


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestAsyncContextManager:
    @pytest.mark.asyncio
    async def test_aenter_returns_client(self) -> None:
        client = _make_client()
        client.api_client.aclose = AsyncMock()
        async with client as c:
            assert c is client

    @pytest.mark.asyncio
    async def test_aexit_calls_close(self) -> None:
        client = _make_client()
        client.api_client.aclose = AsyncMock()
        async with client:
            pass
        client.api_client.aclose.assert_called_once()

    @pytest.mark.asyncio
    async def test_close_calls_aclose_on_api_client(self) -> None:
        client = _make_client()
        client.api_client.aclose = AsyncMock()
        await client.close()
        client.api_client.aclose.assert_called_once()


# ---------------------------------------------------------------------------
# api_endpoint property
# ---------------------------------------------------------------------------


class TestApiEndpointProperty:
    def test_get_returns_base_url(self) -> None:
        client = _make_client()
        client.api_client.base_url = "https://api.example.com"
        assert client.api_endpoint == "https://api.example.com"

    def test_set_updates_base_url(self) -> None:
        client = _make_client()
        client.api_endpoint = "https://staging.example.com/"
        assert client.api_client.base_url == "https://staging.example.com"

    def test_set_non_string_raises_type_error(self) -> None:
        client = _make_client()
        with pytest.raises(TypeError):
            client.api_endpoint = 12345  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Account ID resolution
# ---------------------------------------------------------------------------


class TestAccountIdResolution:
    @pytest.mark.asyncio
    async def test_default_account_used_when_no_explicit_id(self) -> None:
        client = _make_client(default_account="DEFAULT_ACC")
        client.api_client.get = AsyncMock(
            return_value=_portfolio_payload("DEFAULT_ACC")
        )
        await client.get_portfolio()
        url = client.api_client.get.call_args[0][0]
        assert "DEFAULT_ACC" in url

    @pytest.mark.asyncio
    async def test_explicit_account_overrides_default(self) -> None:
        client = _make_client(default_account="DEFAULT_ACC")
        client.api_client.get = AsyncMock(
            return_value=_portfolio_payload("EXPLICIT_ACC")
        )
        await client.get_portfolio(account_id="EXPLICIT_ACC")
        url = client.api_client.get.call_args[0][0]
        assert "EXPLICIT_ACC" in url

    @pytest.mark.asyncio
    async def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            await client.get_portfolio()


# ---------------------------------------------------------------------------
# get_accounts
# ---------------------------------------------------------------------------


class TestGetAccounts:
    def setup_method(self) -> None:
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = AsyncMock(return_value={"accounts": []})
        await self.client.get_accounts()
        self.client.api_client.get.assert_called_once_with(
            "/userapigateway/trading/account"
        )

    @pytest.mark.asyncio
    async def test_returns_accounts_response(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value={
                "accounts": [{"accountId": "ACC-001", "accountType": "BROKERAGE"}]
            }
        )
        result = await self.client.get_accounts()
        assert isinstance(result, AccountsResponse)
        assert len(result.accounts) == 1
        assert result.accounts[0].account_id == "ACC-001"

    @pytest.mark.asyncio
    async def test_refreshes_token(self) -> None:
        self.client.api_client.get = AsyncMock(return_value={"accounts": []})
        await self.client.get_accounts()
        self.client.auth_manager.refresh_token_if_needed.assert_called()


# ---------------------------------------------------------------------------
# get_portfolio
# ---------------------------------------------------------------------------


class TestGetPortfolio:
    def setup_method(self) -> None:
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint_with_default_account(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_portfolio_payload())
        await self.client.get_portfolio()
        url = self.client.api_client.get.call_args[0][0]
        assert f"/{_ACCOUNT}/portfolio/v2" in url

    @pytest.mark.asyncio
    async def test_returns_portfolio_model(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_portfolio_payload())
        result = await self.client.get_portfolio()
        assert isinstance(result, Portfolio)
        assert result.account_id == _ACCOUNT

    @pytest.mark.asyncio
    async def test_refreshes_token(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_portfolio_payload())
        await self.client.get_portfolio()
        self.client.auth_manager.refresh_token_if_needed.assert_called()


# ---------------------------------------------------------------------------
# get_quotes
# ---------------------------------------------------------------------------


class TestGetQuotes:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.instruments = [
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        ]

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.post = AsyncMock(return_value={"quotes": []})
        await self.client.get_quotes(self.instruments)
        url = self.client.api_client.post.call_args[0][0]
        assert f"/{_ACCOUNT}/quotes" in url

    @pytest.mark.asyncio
    async def test_returns_list_of_quotes(self) -> None:
        self.client.api_client.post = AsyncMock(
            return_value={
                "quotes": [
                    {
                        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                        "outcome": "SUCCESS",
                    }
                ]
            }
        )
        result = await self.client.get_quotes(self.instruments)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], Quote)

    @pytest.mark.asyncio
    async def test_empty_quotes_returns_empty_list(self) -> None:
        self.client.api_client.post = AsyncMock(return_value={"quotes": []})
        result = await self.client.get_quotes(self.instruments)
        assert result == []

    @pytest.mark.asyncio
    async def test_sends_instrument_list_in_body(self) -> None:
        self.client.api_client.post = AsyncMock(return_value={"quotes": []})
        await self.client.get_quotes(self.instruments)
        call_kwargs = self.client.api_client.post.call_args[1]
        body = call_kwargs["json_data"]
        assert body == {"instruments": [{"symbol": "AAPL", "type": "EQUITY"}]}


# ---------------------------------------------------------------------------
# get_instrument / get_all_instruments
# ---------------------------------------------------------------------------


class TestGetInstrument:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.instrument_payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "trading": "BUY_AND_SELL",
            "fractionalTrading": "BUY_AND_SELL",
            "optionTrading": "BUY_AND_SELL",
            "optionSpreadTrading": "BUY_AND_SELL",
        }

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value=self.instrument_payload
        )
        await self.client.get_instrument("AAPL", InstrumentType.EQUITY)
        url = self.client.api_client.get.call_args[0][0]
        assert "/instruments/AAPL/EQUITY" in url

    @pytest.mark.asyncio
    async def test_returns_instrument_model(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value=self.instrument_payload
        )
        result = await self.client.get_instrument("AAPL", InstrumentType.EQUITY)
        assert isinstance(result, Instrument)
        assert result.instrument.symbol == "AAPL"

    @pytest.mark.asyncio
    async def test_get_all_instruments_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value={"instruments": [], "page": {}}
        )
        await self.client.get_all_instruments()
        url = self.client.api_client.get.call_args[0][0]
        assert "/trading/instruments" in url


# ---------------------------------------------------------------------------
# place_order / place_multileg_order
# ---------------------------------------------------------------------------


class TestPlaceOrder:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.order_request = OrderRequest(
            order_id=_VALID_UUID,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("1"),
        )

    @pytest.mark.asyncio
    async def test_place_order_calls_correct_endpoint(self) -> None:
        self.client.api_client.post = AsyncMock(
            return_value={"orderId": "ORDER-123"}
        )
        await self.client.place_order(self.order_request)
        url = self.client.api_client.post.call_args[0][0]
        assert f"/{_ACCOUNT}/order" in url

    @pytest.mark.asyncio
    async def test_place_order_returns_async_new_order(self) -> None:
        self.client.api_client.post = AsyncMock(
            return_value={"orderId": "ORDER-123"}
        )
        result = await self.client.place_order(self.order_request)
        assert isinstance(result, AsyncNewOrder)
        assert result.order_id == "ORDER-123"
        assert result.account_id == _ACCOUNT

    @pytest.mark.asyncio
    async def test_place_order_refreshes_token(self) -> None:
        self.client.api_client.post = AsyncMock(
            return_value={"orderId": "ORDER-123"}
        )
        await self.client.place_order(self.order_request)
        self.client.auth_manager.refresh_token_if_needed.assert_called()


class TestPlaceShortOrder:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.mock_order = Mock(spec=AsyncNewOrder)
        self.client.place_order = AsyncMock(return_value=self.mock_order)

    @pytest.mark.asyncio
    async def test_builds_quantity_only_sell_to_open_order(self) -> None:
        result = await self.client.place_short_order(
            symbol="aapl",
            quantity=Decimal("10"),
            order_id=_VALID_UUID,
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.00"),
            equity_market_session=EquityMarketSession.CORE,
            account_id="ACC456",
        )

        assert result is self.mock_order
        request, account_id = self.client.place_order.call_args[0]
        assert request.order_id == _VALID_UUID
        assert request.instrument.symbol == "AAPL"
        assert request.instrument.type == InstrumentType.EQUITY
        assert request.order_side == OrderSide.SELL
        assert request.open_close_indicator == OpenCloseIndicator.OPEN
        assert request.quantity == Decimal("10")
        assert request.amount is None
        assert request.limit_price == Decimal("150.00")
        assert request.equity_market_session == EquityMarketSession.CORE
        assert account_id == "ACC456"

    @pytest.mark.asyncio
    async def test_generates_order_id_when_omitted(self) -> None:
        await self.client.place_short_order(
            symbol="AAPL",
            quantity=Decimal("1"),
        )

        request, _ = self.client.place_order.call_args[0]
        assert UUID(request.order_id).version == 4

    @pytest.mark.asyncio
    async def test_invalid_market_limit_price_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="`limit_price` can only be set"):
            await self.client.place_short_order(
                symbol="AAPL",
                quantity=Decimal("10"),
                limit_price=Decimal("150.00"),
            )
        self.client.place_order.assert_not_called()


class TestFlattenAndGoShort:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.flatten_order = Mock()
        self.flatten_order.order_id = "FLATTEN-123"
        self.filled_flatten = Mock()
        self.flatten_order.wait_for_fill = AsyncMock(return_value=self.filled_flatten)
        self.short_order = Mock(spec=AsyncNewOrder)
        self.client.place_order = AsyncMock(return_value=self.flatten_order)
        self.client.place_short_order = AsyncMock(return_value=self.short_order)

    def _portfolio(self, quantity: Decimal) -> SimpleNamespace:
        positions = []
        if quantity != 0:
            positions.append(
                SimpleNamespace(
                    instrument=SimpleNamespace(
                        symbol="AAPL",
                        type=InstrumentType.EQUITY,
                    ),
                    quantity=quantity,
                )
            )
        return SimpleNamespace(positions=positions)

    @pytest.mark.asyncio
    async def test_flattens_long_position_waits_then_places_short(self) -> None:
        self.client.get_portfolio = AsyncMock(
            side_effect=[
                self._portfolio(Decimal("100")),
                self._portfolio(Decimal("0")),
            ]
        )

        result = await self.client.flatten_and_go_short(
            symbol="aapl",
            short_quantity=Decimal("200"),
            order_id=_VALID_UUID,
            flatten_order_id="85718cfb-32f4-4c57-976b-6060b94bbaf9",
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.00"),
            equity_market_session=EquityMarketSession.CORE,
            flatten_timeout=12,
            polling_interval=0.5,
            account_id="ACC456",
        )

        flatten_request = self.client.place_order.call_args[0][0]
        flatten_account_id = self.client.place_order.call_args[1]["account_id"]
        assert flatten_request.instrument.symbol == "AAPL"
        assert flatten_request.order_side == OrderSide.SELL
        assert flatten_request.open_close_indicator == OpenCloseIndicator.CLOSE
        assert flatten_request.order_type == OrderType.MARKET
        assert flatten_request.quantity == Decimal("100")
        assert flatten_account_id == "ACC456"
        self.flatten_order.wait_for_fill.assert_called_once_with(
            timeout=12,
            polling_interval=0.5,
        )
        self.client.place_short_order.assert_called_once_with(
            symbol="AAPL",
            quantity=Decimal("200"),
            order_id=_VALID_UUID,
            order_type=OrderType.LIMIT,
            time_in_force=TimeInForce.DAY,
            expiration_time=None,
            limit_price=Decimal("150.00"),
            stop_price=None,
            equity_market_session=EquityMarketSession.CORE,
            account_id="ACC456",
        )
        assert result.initial_position_quantity == Decimal("100")
        assert result.flatten_order is self.flatten_order
        assert result.flatten_filled_order is self.filled_flatten
        assert result.short_order is self.short_order

    @pytest.mark.asyncio
    async def test_flat_position_places_short_without_flatten_order(self) -> None:
        self.client.get_portfolio = AsyncMock(
            return_value=self._portfolio(Decimal("0"))
        )

        result = await self.client.flatten_and_go_short(
            symbol="AAPL",
            short_quantity=Decimal("25"),
        )

        self.client.place_order.assert_not_called()
        self.client.place_short_order.assert_called_once()
        assert result.initial_position_quantity == Decimal("0")
        assert result.flatten_order is None
        assert result.flatten_filled_order is None
        assert result.short_order is self.short_order

    @pytest.mark.asyncio
    async def test_remaining_long_position_stops_before_short_order(self) -> None:
        self.client.get_portfolio = AsyncMock(
            side_effect=[
                self._portfolio(Decimal("100")),
                self._portfolio(Decimal("5")),
            ]
        )

        with pytest.raises(RuntimeError, match="Long position in AAPL remains"):
            await self.client.flatten_and_go_short(
                symbol="AAPL",
                short_quantity=Decimal("25"),
            )

        self.flatten_order.wait_for_fill.assert_called_once()
        self.client.place_short_order.assert_not_called()


# ---------------------------------------------------------------------------
# get_order / cancel_order
# ---------------------------------------------------------------------------


class TestGetOrder:
    def setup_method(self) -> None:
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_get_order_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value=_order_payload("ORDER-99")
        )
        await self.client.get_order("ORDER-99")
        url = self.client.api_client.get.call_args[0][0]
        assert "ORDER-99" in url
        assert f"/{_ACCOUNT}/order/" in url

    @pytest.mark.asyncio
    async def test_get_order_returns_order_model(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value=_order_payload("ORDER-99", status="FILLED")
        )
        result = await self.client.get_order("ORDER-99")
        assert isinstance(result, Order)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_cancel_order_calls_delete_endpoint(self) -> None:
        self.client.api_client.delete = AsyncMock(return_value={})
        await self.client.cancel_order("ORDER-99")
        url = self.client.api_client.delete.call_args[0][0]
        assert "ORDER-99" in url
        assert f"/{_ACCOUNT}/order/" in url

    @pytest.mark.asyncio
    async def test_cancel_order_refreshes_token(self) -> None:
        self.client.api_client.delete = AsyncMock(return_value={})
        await self.client.cancel_order("ORDER-99")
        self.client.auth_manager.refresh_token_if_needed.assert_called()


# ---------------------------------------------------------------------------
# cancel_and_replace_order
# ---------------------------------------------------------------------------

_REQUEST_UUID = "85718cfb-32f4-4c57-976b-6060b94bbaf9"


class TestCancelAndReplaceOrder:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.request = CancelAndReplaceRequest(
            order_id=_VALID_UUID,
            request_id=_REQUEST_UUID,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            limit_price=Decimal("150.00"),
        )

    @pytest.mark.asyncio
    async def test_calls_put_on_correct_endpoint(self) -> None:
        self.client.api_client.put = AsyncMock(
            return_value={"orderId": "NEW-ORDER-456"}
        )
        await self.client.cancel_and_replace_order(self.request)
        url = self.client.api_client.put.call_args[0][0]
        assert f"/{_ACCOUNT}/order" in url

    @pytest.mark.asyncio
    async def test_returns_async_new_order(self) -> None:
        self.client.api_client.put = AsyncMock(
            return_value={"orderId": "NEW-ORDER-456"}
        )
        result = await self.client.cancel_and_replace_order(self.request)
        assert isinstance(result, AsyncNewOrder)
        assert result.order_id == "NEW-ORDER-456"
        assert result.account_id == _ACCOUNT

    @pytest.mark.asyncio
    async def test_sends_serialized_body(self) -> None:
        self.client.api_client.put = AsyncMock(
            return_value={"orderId": "NEW-ORDER-456"}
        )
        await self.client.cancel_and_replace_order(self.request)
        json_data = self.client.api_client.put.call_args[1]["json_data"]
        assert json_data["orderId"] == _VALID_UUID
        assert json_data["requestId"] == _REQUEST_UUID
        assert json_data["orderType"] == "LIMIT"
        assert json_data["limitPrice"] == "150.00"

    @pytest.mark.asyncio
    async def test_uses_explicit_account_id(self) -> None:
        self.client.api_client.put = AsyncMock(
            return_value={"orderId": "NEW-ORDER-456"}
        )
        await self.client.cancel_and_replace_order(self.request, account_id="OTHER_ACC")
        url = self.client.api_client.put.call_args[0][0]
        assert "/OTHER_ACC/order" in url

    @pytest.mark.asyncio
    async def test_refreshes_token(self) -> None:
        self.client.api_client.put = AsyncMock(
            return_value={"orderId": "NEW-ORDER-456"}
        )
        await self.client.cancel_and_replace_order(self.request)
        self.client.auth_manager.refresh_token_if_needed.assert_called()

    @pytest.mark.asyncio
    async def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            await client.cancel_and_replace_order(self.request)


# ---------------------------------------------------------------------------
# perform_preflight_calculation
# ---------------------------------------------------------------------------


class TestPreflightCalculation:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.preflight_request = PreflightRequest(
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("1"),
        )

    @pytest.mark.asyncio
    async def test_calls_preflight_endpoint(self) -> None:
        self.client.api_client.post = AsyncMock(
            return_value={
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "orderValue": "150.00",
            }
        )
        await self.client.perform_preflight_calculation(self.preflight_request)
        url = self.client.api_client.post.call_args[0][0]
        assert "preflight/single-leg" in url

    @pytest.mark.asyncio
    async def test_refreshes_token(self) -> None:
        self.client.api_client.post = AsyncMock(
            return_value={
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "orderValue": "150.00",
            }
        )
        await self.client.perform_preflight_calculation(self.preflight_request)
        self.client.auth_manager.refresh_token_if_needed.assert_called()


class TestPreflightShortOrder:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.mock_response = Mock(spec=PreflightResponse)
        self.client.perform_preflight_calculation = AsyncMock(
            return_value=self.mock_response
        )

    @pytest.mark.asyncio
    async def test_builds_quantity_only_sell_to_open_request(self) -> None:
        result = await self.client.preflight_short_order(
            symbol="aapl",
            quantity=Decimal("10"),
            order_type=OrderType.LIMIT,
            limit_price=Decimal("150.00"),
            equity_market_session=EquityMarketSession.CORE,
            validate_order=False,
            account_id="ACC456",
        )

        assert result is self.mock_response
        request, account_id = self.client.perform_preflight_calculation.call_args[0]
        assert request.instrument.symbol == "AAPL"
        assert request.instrument.type == InstrumentType.EQUITY
        assert request.order_side == OrderSide.SELL
        assert request.open_close_indicator == OpenCloseIndicator.OPEN
        assert request.quantity == Decimal("10")
        assert request.amount is None
        assert request.limit_price == Decimal("150.00")
        assert request.equity_market_session == EquityMarketSession.CORE
        assert request.validate_order is False
        assert account_id == "ACC456"

    @pytest.mark.asyncio
    async def test_invalid_market_limit_price_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="`limit_price` can only be set"):
            await self.client.preflight_short_order(
                symbol="AAPL",
                quantity=Decimal("10"),
                limit_price=Decimal("150.00"),
            )
        self.client.perform_preflight_calculation.assert_not_called()


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    def setup_method(self) -> None:
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = AsyncMock(return_value={"transactions": []})
        await self.client.get_history()
        url = self.client.api_client.get.call_args[0][0]
        assert f"/{_ACCOUNT}/history" in url

    @pytest.mark.asyncio
    async def test_returns_history_response_page(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value={"transactions": []}
        )
        result = await self.client.get_history()
        assert isinstance(result, HistoryResponsePage)

    @pytest.mark.asyncio
    async def test_passes_request_params(self) -> None:
        from datetime import datetime, timezone

        self.client.api_client.get = AsyncMock(
            return_value={"transactions": []}
        )
        request = HistoryRequest(page_size=5)
        await self.client.get_history(history_request=request)
        call_kwargs = self.client.api_client.get.call_args[1]
        assert call_kwargs["params"] is not None


# ---------------------------------------------------------------------------
# get_option_greeks
# ---------------------------------------------------------------------------


class TestGetOptionGreeks:
    def setup_method(self) -> None:
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = AsyncMock(return_value={"greeks": []})
        await self.client.get_option_greeks(["AAPL230120C00150000"])
        url = self.client.api_client.get.call_args[0][0]
        assert "greeks" in url

    @pytest.mark.asyncio
    async def test_returns_greeks_response(self) -> None:
        self.client.api_client.get = AsyncMock(return_value={"greeks": []})
        result = await self.client.get_option_greeks(["AAPL230120C00150000"])
        assert isinstance(result, GreeksResponse)

    @pytest.mark.asyncio
    async def test_get_option_greek_raises_when_no_greeks_returned(self) -> None:
        self.client.api_client.get = AsyncMock(return_value={"greeks": []})
        with pytest.raises(ValueError, match="No greeks found"):
            await self.client.get_option_greek("AAPL230120C00150000")


# ---------------------------------------------------------------------------
# get_bars
# ---------------------------------------------------------------------------


def _bars_payload(symbol: str = "AAPL", period: str = "YEAR") -> dict:
    bar = {
        "timestamp": "2024-01-02T09:30:00",
        "open": "185.00",
        "close": "186.50",
        "high": "187.00",
        "low": "184.50",
        "value": "186.50",
        "volume": 6321507.562155,
    }
    session = {"expectedBars": 1, "bars": [bar]}
    return {
        "symbol": symbol,
        "period": period,
        "totalExpectedBars": 1,
        "preMarket": session,
        "regularMarket": session,
        "afterMarket": session,
    }


class TestGetBars:
    def setup_method(self) -> None:
        self.client = _make_client()

    @pytest.mark.asyncio
    async def test_calls_url_without_aggregation(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload())
        await self.client.get_bars("AAPL", BarPeriod.YEAR)
        url = self.client.api_client.get.call_args[0][0]
        assert url == "/userapigateway/historicdata/EQUITY/AAPL/YEAR"

    @pytest.mark.asyncio
    async def test_calls_url_with_aggregation(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload())
        await self.client.get_bars("AAPL", BarPeriod.YEAR, aggregation=BarAggregation.ONE_HOUR)
        url = self.client.api_client.get.call_args[0][0]
        assert url == "/userapigateway/historicdata/EQUITY/AAPL/YEAR/ONE_HOUR"

    @pytest.mark.asyncio
    async def test_calls_url_with_crypto_instrument_type(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload(symbol="BTC"))
        await self.client.get_bars(
            "BTC", BarPeriod.YEAR, instrument_type=InstrumentType.CRYPTO
        )
        url = self.client.api_client.get.call_args[0][0]
        assert url == "/userapigateway/historicdata/CRYPTO/BTC/YEAR"

    @pytest.mark.asyncio
    async def test_calls_url_with_option_instrument_type(self) -> None:
        self.client.api_client.get = AsyncMock(
            return_value=_bars_payload(symbol="AAPL  240119C00150000")
        )
        await self.client.get_bars(
            "AAPL  240119C00150000",
            BarPeriod.YEAR,
            instrument_type=InstrumentType.OPTION,
        )
        url = self.client.api_client.get.call_args[0][0]
        assert url == "/userapigateway/historicdata/OPTION/AAPL  240119C00150000/YEAR"

    @pytest.mark.asyncio
    async def test_rejects_unsupported_instrument_type(self) -> None:
        with pytest.raises(ValueError, match="not supported for historic bars"):
            await self.client.get_bars(
                "AAPL", BarPeriod.YEAR, instrument_type=InstrumentType.BOND
            )

    @pytest.mark.asyncio
    async def test_passes_purchase_date_as_query_param(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload(period="SINCE_PURCHASE"))
        await self.client.get_bars("AAPL", BarPeriod.SINCE_PURCHASE, purchase_date="2024-03-15")
        params = self.client.api_client.get.call_args[1]["params"]
        assert params == {"purchaseDate": "2024-03-15"}

    @pytest.mark.asyncio
    async def test_omits_params_when_no_purchase_date(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload())
        await self.client.get_bars("AAPL", BarPeriod.YEAR)
        params = self.client.api_client.get.call_args[1]["params"]
        assert params is None

    @pytest.mark.asyncio
    async def test_returns_bars_response(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload())
        result = await self.client.get_bars("AAPL", BarPeriod.YEAR)
        assert isinstance(result, BarsResponse)
        assert result.symbol == "AAPL"
        assert result.period == "YEAR"

    @pytest.mark.asyncio
    async def test_response_deserializes_sessions_and_bars(self) -> None:
        self.client.api_client.get = AsyncMock(return_value=_bars_payload())
        result = await self.client.get_bars("AAPL", BarPeriod.YEAR)
        assert result.total_expected_bars == 1
        assert len(result.regular_market.bars) == 1
        bar = result.regular_market.bars[0]
        assert isinstance(bar, Bar)
        assert bar.open == Decimal("185.00")
        assert bar.close == Decimal("186.50")
        assert bar.volume == Decimal("6321507.562155")
