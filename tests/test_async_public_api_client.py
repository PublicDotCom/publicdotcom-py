"""Tests for AsyncPublicApiClient API methods.

All tests patch AsyncApiClient and AsyncAuthManager at construction time so no
real HTTP calls are made.
"""

from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

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
from public_api_sdk.models.history import HistoryRequest, HistoryResponsePage
from public_api_sdk.models.instrument import Instrument
from public_api_sdk.models.option import GreeksResponse
from public_api_sdk.models.order import (
    CancelAndReplaceRequest,
    Order,
    OrderExpirationRequest,
    OrderRequest,
    OrderSide,
    OrderStatus,
    OrderType,
    PreflightRequest,
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
        assert "instruments" in body
        assert body["instruments"][0]["symbol"] == "AAPL"


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
