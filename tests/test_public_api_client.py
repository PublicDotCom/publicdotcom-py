"""Tests for PublicApiClient API methods.

All tests patch ApiClient and AuthManager at construction time so no real HTTP
calls are made. After construction the mocked api_client and auth_manager
instances remain on the client object and can be configured per-test.
"""

from decimal import Decimal
from types import SimpleNamespace
from typing import Optional
from unittest.mock import Mock, patch
from uuid import UUID

import pytest

from public_api_sdk import (
    ApiKeyAuthConfig,
    InstrumentType,
    OrderInstrument,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.models.account import AccountsResponse
from public_api_sdk.models.history import HistoryRequest, HistoryResponsePage
from public_api_sdk.models.instrument import Instrument
from public_api_sdk.models.new_order import NewOrder
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


def _make_client(default_account: Optional[str] = _ACCOUNT) -> PublicApiClient:
    """Return a PublicApiClient with ApiClient and AuthManager patched out."""
    with patch("public_api_sdk.public_api_client.ApiClient"), patch(
        "public_api_sdk.public_api_client.AuthManager"
    ):
        config = PublicApiClientConfiguration(default_account_number=default_account)
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )
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
# Account ID resolution
# ---------------------------------------------------------------------------


class TestAccountIdResolution:
    def test_default_account_used_when_no_explicit_id(self) -> None:
        client = _make_client(default_account="DEFAULT_ACC")
        client.api_client.get = Mock(return_value=_portfolio_payload("DEFAULT_ACC"))
        client.get_portfolio()
        url = client.api_client.get.call_args[0][0]
        assert "DEFAULT_ACC" in url

    def test_explicit_account_overrides_default(self) -> None:
        client = _make_client(default_account="DEFAULT_ACC")
        client.api_client.get = Mock(return_value=_portfolio_payload("EXPLICIT_ACC"))
        client.get_portfolio(account_id="EXPLICIT_ACC")
        url = client.api_client.get.call_args[0][0]
        assert "EXPLICIT_ACC" in url

    def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            client.get_portfolio()

    def test_no_account_explicit_none_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        client.api_client.get = Mock(return_value={})
        with pytest.raises(ValueError, match="No account ID provided"):
            client.get_portfolio(account_id=None)


# ---------------------------------------------------------------------------
# get_accounts
# ---------------------------------------------------------------------------


class TestGetAccounts:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = Mock(return_value={"accounts": []})
        self.client.get_accounts()
        self.client.api_client.get.assert_called_once_with(
            "/userapigateway/trading/account"
        )

    def test_returns_accounts_response(self) -> None:
        self.client.api_client.get = Mock(
            return_value={
                "accounts": [{"accountId": "ACC-001", "accountType": "BROKERAGE"}]
            }
        )
        result = self.client.get_accounts()
        assert isinstance(result, AccountsResponse)
        assert len(result.accounts) == 1
        assert result.accounts[0].account_id == "ACC-001"

    def test_refreshes_token(self) -> None:
        self.client.api_client.get = Mock(return_value={"accounts": []})
        self.client.get_accounts()
        self.client.auth_manager.refresh_token_if_needed.assert_called()

    def test_empty_accounts_list(self) -> None:
        self.client.api_client.get = Mock(return_value={"accounts": []})
        result = self.client.get_accounts()
        assert result.accounts == []


# ---------------------------------------------------------------------------
# get_portfolio
# ---------------------------------------------------------------------------


class TestGetPortfolio:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint_with_default_account(self) -> None:
        self.client.api_client.get = Mock(return_value=_portfolio_payload())
        self.client.get_portfolio()
        url = self.client.api_client.get.call_args[0][0]
        assert f"/{_ACCOUNT}/portfolio/v2" in url

    def test_calls_correct_endpoint_with_explicit_account(self) -> None:
        self.client.api_client.get = Mock(return_value=_portfolio_payload("OTHER"))
        self.client.get_portfolio(account_id="OTHER")
        url = self.client.api_client.get.call_args[0][0]
        assert "/OTHER/portfolio/v2" in url

    def test_returns_portfolio_model(self) -> None:
        self.client.api_client.get = Mock(return_value=_portfolio_payload())
        result = self.client.get_portfolio()
        assert isinstance(result, Portfolio)
        assert result.account_id == _ACCOUNT

    def test_refreshes_token(self) -> None:
        self.client.api_client.get = Mock(return_value=_portfolio_payload())
        self.client.get_portfolio()
        self.client.auth_manager.refresh_token_if_needed.assert_called()


# ---------------------------------------------------------------------------
# get_quotes
# ---------------------------------------------------------------------------


class TestGetQuotes:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.instruments = [
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
        ]

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.post = Mock(return_value={"quotes": []})
        self.client.get_quotes(self.instruments)
        url = self.client.api_client.post.call_args[0][0]
        assert f"/{_ACCOUNT}/quotes" in url

    def test_sends_instruments_in_body(self) -> None:
        self.client.api_client.post = Mock(return_value={"quotes": []})
        self.client.get_quotes(self.instruments)
        json_data = self.client.api_client.post.call_args[1]["json_data"]
        assert "instruments" in json_data
        assert len(json_data["instruments"]) == 2

    def test_returns_list_of_quotes(self) -> None:
        self.client.api_client.post = Mock(
            return_value={
                "quotes": [
                    {
                        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                        "outcome": "SUCCESS",
                        "last": "150.00",
                    }
                ]
            }
        )
        result = self.client.get_quotes(self.instruments)
        assert isinstance(result, list)
        assert len(result) == 1
        assert isinstance(result[0], Quote)
        assert result[0].last == Decimal("150.00")

    def test_empty_response_returns_empty_list(self) -> None:
        self.client.api_client.post = Mock(return_value={"quotes": []})
        result = self.client.get_quotes(self.instruments)
        assert result == []


# ---------------------------------------------------------------------------
# get_history
# ---------------------------------------------------------------------------


class TestGetHistory:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = Mock(return_value={"transactions": []})
        self.client.get_history()
        url = self.client.api_client.get.call_args[0][0]
        assert f"/{_ACCOUNT}/history" in url

    def test_without_request_sends_no_params(self) -> None:
        self.client.api_client.get = Mock(return_value={"transactions": []})
        self.client.get_history()
        params = self.client.api_client.get.call_args[1]["params"]
        assert params is None

    def test_with_request_sends_params(self) -> None:
        self.client.api_client.get = Mock(return_value={"transactions": []})
        self.client.get_history(history_request=HistoryRequest(page_size=10))
        params = self.client.api_client.get.call_args[1]["params"]
        assert params is not None
        assert "pageSize" in params

    def test_returns_history_response_page(self) -> None:
        self.client.api_client.get = Mock(return_value={"transactions": []})
        result = self.client.get_history()
        assert isinstance(result, HistoryResponsePage)


# ---------------------------------------------------------------------------
# get_instrument / get_all_instruments
# ---------------------------------------------------------------------------

_INSTRUMENT_PAYLOAD = {
    "instrument": {"symbol": "AAPL", "type": "EQUITY"},
    "trading": "BUY_AND_SELL",
    "fractionalTrading": "BUY_AND_SELL",
    "optionTrading": "BUY_AND_SELL",
    "optionSpreadTrading": "DISABLED",
}


class TestGetInstrument:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = Mock(return_value=_INSTRUMENT_PAYLOAD)
        self.client.get_instrument("AAPL", InstrumentType.EQUITY)
        url = self.client.api_client.get.call_args[0][0]
        assert "AAPL" in url
        assert "EQUITY" in url

    def test_returns_instrument_model(self) -> None:
        self.client.api_client.get = Mock(return_value=_INSTRUMENT_PAYLOAD)
        result = self.client.get_instrument("AAPL", InstrumentType.EQUITY)
        assert isinstance(result, Instrument)
        assert result.instrument.symbol == "AAPL"


class TestGetAllInstruments:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = Mock(return_value={"instruments": []})
        self.client.get_all_instruments()
        url = self.client.api_client.get.call_args[0][0]
        assert "instruments" in url

    def test_without_filter_sends_no_params(self) -> None:
        self.client.api_client.get = Mock(return_value={"instruments": []})
        self.client.get_all_instruments()
        params = self.client.api_client.get.call_args[1]["params"]
        assert params is None

    def test_with_filter_sends_params(self) -> None:
        from public_api_sdk.models.instrument import InstrumentsRequest, Trading

        self.client.api_client.get = Mock(return_value={"instruments": []})
        request = InstrumentsRequest(trading_filter=[Trading.BUY_AND_SELL])
        self.client.get_all_instruments(instruments_request=request)
        params = self.client.api_client.get.call_args[1]["params"]
        assert params is not None


# ---------------------------------------------------------------------------
# Options: expirations, chain, greeks
# ---------------------------------------------------------------------------


class TestGetOptionExpirations:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint(self) -> None:
        from public_api_sdk.models.option import OptionExpirationsRequest

        self.client.api_client.post = Mock(
            return_value={"baseSymbol": "AAPL", "expirations": []}
        )
        request = OptionExpirationsRequest(
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
        )
        self.client.get_option_expirations(request)
        url = self.client.api_client.post.call_args[0][0]
        assert f"/{_ACCOUNT}/option-expirations" in url

    def test_returns_expirations_response(self) -> None:
        from public_api_sdk.models.option import (
            OptionExpirationsRequest,
            OptionExpirationsResponse,
        )

        self.client.api_client.post = Mock(
            return_value={"baseSymbol": "AAPL", "expirations": ["2025-01-17"]}
        )
        request = OptionExpirationsRequest(
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
        )
        result = self.client.get_option_expirations(request)
        assert isinstance(result, OptionExpirationsResponse)
        assert result.expirations == ["2025-01-17"]


class TestGetOptionGreeks:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.greeks_payload = {
            "greeks": [
                {
                    "symbol": "AAPL260116C00270000",
                    "greeks": {
                        "delta": "0.5",
                        "gamma": "0.01",
                        "theta": "-0.05",
                        "vega": "0.2",
                        "rho": "0.1",
                        "impliedVolatility": "0.25",
                    },
                }
            ]
        }

    def test_get_option_greeks_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = Mock(return_value=self.greeks_payload)
        self.client.get_option_greeks(["AAPL260116C00270000"])
        url = self.client.api_client.get.call_args[0][0]
        assert f"/{_ACCOUNT}/greeks" in url

    def test_get_option_greeks_returns_response(self) -> None:
        self.client.api_client.get = Mock(return_value=self.greeks_payload)
        result = self.client.get_option_greeks(["AAPL260116C00270000"])
        assert isinstance(result, GreeksResponse)
        assert len(result.greeks) == 1
        assert result.greeks[0].symbol == "AAPL260116C00270000"

    def test_get_option_greek_returns_single(self) -> None:
        from public_api_sdk.models.option import OptionGreeks

        self.client.api_client.get = Mock(return_value=self.greeks_payload)
        result = self.client.get_option_greek("AAPL260116C00270000")
        assert isinstance(result, OptionGreeks)
        assert result.symbol == "AAPL260116C00270000"

    def test_get_option_greek_raises_when_empty(self) -> None:
        self.client.api_client.get = Mock(return_value={"greeks": []})
        with pytest.raises(ValueError, match="No greeks found"):
            self.client.get_option_greek("AAPL260116C00270000")


# ---------------------------------------------------------------------------
# Preflight calculations
# ---------------------------------------------------------------------------


class TestPerformPreflightCalculation:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.preflight_response = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "orderValue": "15000.00",
            "estimatedCommission": "0.00",
            "estimatedCost": "15000.00",
        }

    def _make_request(self) -> PreflightRequest:
        return PreflightRequest(
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=100,
            limit_price=Decimal("150.00"),
        )

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.post = Mock(return_value=self.preflight_response)
        self.client.perform_preflight_calculation(self._make_request())
        url = self.client.api_client.post.call_args[0][0]
        assert f"/{_ACCOUNT}/preflight/single-leg" in url

    def test_returns_preflight_response(self) -> None:
        from public_api_sdk.models.order import PreflightResponse

        self.client.api_client.post = Mock(return_value=self.preflight_response)
        result = self.client.perform_preflight_calculation(self._make_request())
        assert isinstance(result, PreflightResponse)


class TestPreflightShortOrder:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.mock_response = Mock(spec=PreflightResponse)
        self.client.perform_preflight_calculation = Mock(
            return_value=self.mock_response
        )

    def test_builds_quantity_only_sell_to_open_request(self) -> None:
        result = self.client.preflight_short_order(
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

    def test_invalid_market_limit_price_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="`limit_price` can only be set"):
            self.client.preflight_short_order(
                symbol="AAPL",
                quantity=Decimal("10"),
                limit_price=Decimal("150.00"),
            )
        self.client.perform_preflight_calculation.assert_not_called()


# ---------------------------------------------------------------------------
# place_order / place_multileg_order
# ---------------------------------------------------------------------------


class TestPlaceOrder:
    def setup_method(self) -> None:
        self.client = _make_client()

    def _make_request(self) -> OrderRequest:
        return OrderRequest(
            order_id=_VALID_UUID,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=10,
        )

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.post = Mock(return_value={"orderId": "ORDER-123"})
        self.client.place_order(self._make_request())
        url = self.client.api_client.post.call_args[0][0]
        assert f"/{_ACCOUNT}/order" in url

    def test_returns_new_order(self) -> None:
        self.client.api_client.post = Mock(return_value={"orderId": "ORDER-123"})
        result = self.client.place_order(self._make_request())
        assert isinstance(result, NewOrder)
        assert result.order_id == "ORDER-123"
        assert result.account_id == _ACCOUNT

    def test_sends_serialized_request(self) -> None:
        self.client.api_client.post = Mock(return_value={"orderId": "ORDER-123"})
        self.client.place_order(self._make_request())
        json_data = self.client.api_client.post.call_args[1]["json_data"]
        assert "orderId" in json_data

    def test_uses_explicit_account_id(self) -> None:
        self.client.api_client.post = Mock(return_value={"orderId": "ORDER-123"})
        self.client.place_order(self._make_request(), account_id="OTHER_ACC")
        url = self.client.api_client.post.call_args[0][0]
        assert "/OTHER_ACC/order" in url


class TestPlaceShortOrder:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.mock_order = Mock(spec=NewOrder)
        self.client.place_order = Mock(return_value=self.mock_order)

    def test_builds_quantity_only_sell_to_open_order(self) -> None:
        result = self.client.place_short_order(
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

    def test_generates_order_id_when_omitted(self) -> None:
        self.client.place_short_order(
            symbol="AAPL",
            quantity=Decimal("1"),
        )

        request, _ = self.client.place_order.call_args[0]
        assert UUID(request.order_id).version == 4

    def test_invalid_market_limit_price_raises_before_dispatch(self) -> None:
        with pytest.raises(ValueError, match="`limit_price` can only be set"):
            self.client.place_short_order(
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
        self.flatten_order.wait_for_fill = Mock(return_value=self.filled_flatten)
        self.short_order = Mock(spec=NewOrder)
        self.client.place_order = Mock(return_value=self.flatten_order)
        self.client.place_short_order = Mock(return_value=self.short_order)

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

    def test_flattens_long_position_waits_then_places_short(self) -> None:
        self.client.get_portfolio = Mock(
            side_effect=[
                self._portfolio(Decimal("100")),
                self._portfolio(Decimal("0")),
            ]
        )

        result = self.client.flatten_and_go_short(
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
        assert flatten_request.order_id == "85718cfb-32f4-4c57-976b-6060b94bbaf9"
        assert flatten_request.instrument.symbol == "AAPL"
        assert flatten_request.order_side == OrderSide.SELL
        assert flatten_request.open_close_indicator == OpenCloseIndicator.CLOSE
        assert flatten_request.order_type == OrderType.MARKET
        assert flatten_request.quantity == Decimal("100")
        assert flatten_request.amount is None
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

    def test_flat_position_places_short_without_flatten_order(self) -> None:
        self.client.get_portfolio = Mock(return_value=self._portfolio(Decimal("0")))

        result = self.client.flatten_and_go_short(
            symbol="AAPL",
            short_quantity=Decimal("25"),
        )

        self.client.place_order.assert_not_called()
        self.client.place_short_order.assert_called_once()
        assert result.initial_position_quantity == Decimal("0")
        assert result.flatten_order is None
        assert result.flatten_filled_order is None
        assert result.short_order is self.short_order

    def test_remaining_long_position_stops_before_short_order(self) -> None:
        self.client.get_portfolio = Mock(
            side_effect=[
                self._portfolio(Decimal("100")),
                self._portfolio(Decimal("5")),
            ]
        )

        with pytest.raises(RuntimeError, match="Long position in AAPL remains"):
            self.client.flatten_and_go_short(
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

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.get = Mock(return_value=_order_payload())
        self.client.get_order("ORDER-123")
        url = self.client.api_client.get.call_args[0][0]
        assert "ORDER-123" in url
        assert _ACCOUNT in url

    def test_returns_order_model(self) -> None:
        self.client.api_client.get = Mock(return_value=_order_payload())
        result = self.client.get_order("ORDER-123")
        assert isinstance(result, Order)
        assert result.status == OrderStatus.NEW

    def test_uses_default_account(self) -> None:
        self.client.api_client.get = Mock(return_value=_order_payload())
        self.client.get_order("ORDER-123")
        url = self.client.api_client.get.call_args[0][0]
        assert _ACCOUNT in url

    def test_uses_explicit_account(self) -> None:
        self.client.api_client.get = Mock(return_value=_order_payload())
        self.client.get_order("ORDER-123", account_id="OTHER_ACC")
        url = self.client.api_client.get.call_args[0][0]
        assert "OTHER_ACC" in url

    def test_refreshes_token(self) -> None:
        self.client.api_client.get = Mock(return_value=_order_payload())
        self.client.get_order("ORDER-123")
        self.client.auth_manager.refresh_token_if_needed.assert_called()


class TestCancelOrder:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_calls_correct_endpoint(self) -> None:
        self.client.api_client.delete = Mock(return_value={})
        self.client.cancel_order("ORDER-123")
        url = self.client.api_client.delete.call_args[0][0]
        assert "ORDER-123" in url
        assert _ACCOUNT in url

    def test_returns_none(self) -> None:
        self.client.api_client.delete = Mock(return_value={})
        result = self.client.cancel_order("ORDER-123")
        assert result is None

    def test_uses_explicit_account(self) -> None:
        self.client.api_client.delete = Mock(return_value={})
        self.client.cancel_order("ORDER-123", account_id="OTHER_ACC")
        url = self.client.api_client.delete.call_args[0][0]
        assert "OTHER_ACC" in url

    def test_refreshes_token(self) -> None:
        self.client.api_client.delete = Mock(return_value={})
        self.client.cancel_order("ORDER-123")
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

    def test_calls_put_on_correct_endpoint(self) -> None:
        self.client.api_client.put = Mock(return_value={"orderId": "NEW-ORDER-456"})
        self.client.cancel_and_replace_order(self.request)
        url = self.client.api_client.put.call_args[0][0]
        assert f"/{_ACCOUNT}/order" in url

    def test_returns_new_order(self) -> None:
        self.client.api_client.put = Mock(return_value={"orderId": "NEW-ORDER-456"})
        result = self.client.cancel_and_replace_order(self.request)
        assert isinstance(result, NewOrder)
        assert result.order_id == "NEW-ORDER-456"
        assert result.account_id == _ACCOUNT

    def test_sends_serialized_body(self) -> None:
        self.client.api_client.put = Mock(return_value={"orderId": "NEW-ORDER-456"})
        self.client.cancel_and_replace_order(self.request)
        json_data = self.client.api_client.put.call_args[1]["json_data"]
        assert json_data["orderId"] == _VALID_UUID
        assert json_data["requestId"] == _REQUEST_UUID
        assert json_data["orderType"] == "LIMIT"
        assert json_data["limitPrice"] == "150.00"

    def test_uses_explicit_account_id(self) -> None:
        self.client.api_client.put = Mock(return_value={"orderId": "NEW-ORDER-456"})
        self.client.cancel_and_replace_order(self.request, account_id="OTHER_ACC")
        url = self.client.api_client.put.call_args[0][0]
        assert "/OTHER_ACC/order" in url

    def test_refreshes_token(self) -> None:
        self.client.api_client.put = Mock(return_value={"orderId": "NEW-ORDER-456"})
        self.client.cancel_and_replace_order(self.request)
        self.client.auth_manager.refresh_token_if_needed.assert_called()

    def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            client.cancel_and_replace_order(self.request)


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
        client.api_endpoint = "https://staging.api.example.com"
        assert client.api_client.base_url == "https://staging.api.example.com"

    def test_set_strips_trailing_slash(self) -> None:
        client = _make_client()
        client.api_endpoint = "https://staging.api.example.com/"
        assert client.api_client.base_url == "https://staging.api.example.com"

    def test_set_non_string_raises_type_error(self) -> None:
        client = _make_client()
        with pytest.raises(TypeError, match="must be a string URL"):
            client.api_endpoint = 12345  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# close
# ---------------------------------------------------------------------------


class TestClose:
    def test_stops_subscription_managers_and_api_client(self) -> None:
        client = _make_client()
        client._subscription_manager.stop = Mock()
        client._order_subscription_manager.stop = Mock()
        client.api_client.close = Mock()

        client.close()

        client._subscription_manager.stop.assert_called_once()
        client._order_subscription_manager.stop.assert_called_once()
        client.api_client.close.assert_called_once()
