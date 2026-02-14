"""Integration-style tests for PublicApiClient with mocked HTTP responses."""
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock, patch

import pytest

from public_api_sdk import (
    PublicApiClient,
    PublicApiClientConfiguration,
    ApiKeyAuthConfig,
    OrderInstrument,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderExpirationRequest,
    OrderRequest,
    PreflightRequest,
    InstrumentType,
    HistoryRequest,
)
from public_api_sdk.models import AccountType


class TestPublicApiClientIntegration:
    """Integration tests mocking HTTP layer."""

    @pytest.fixture
    def mock_api_client(self):
        """Create a mock API client that returns successful responses."""
        with patch('public_api_sdk.public_api_client.ApiClient') as MockApiClient:
            instance = Mock()
            instance.base_url = "https://api.public.com"
            MockApiClient.return_value = instance
            yield instance

    @pytest.fixture
    def client(self, mock_api_client):
        """Create a configured PublicApiClient with mocked HTTP."""
        # Mock token creation
        mock_api_client.post.return_value = {"accessToken": "test-token"}
        
        client = PublicApiClient(
            ApiKeyAuthConfig(api_secret_key="test-secret"),
            config=PublicApiClientConfiguration(default_account_number="ACC123"),
        )
        return client

    def test_full_order_flow(self, client, mock_api_client):
        """Complete order lifecycle: place, check status, cancel."""
        # Setup mock responses in sequence
        mock_api_client.post.side_effect = [
            {"accessToken": "test-token"},  # Auth
            {"orderId": "ORDER123"},  # Place order
        ]
        mock_api_client.get.side_effect = [
            {  # Get order - NEW
                "orderId": "ORDER123",
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "type": "LIMIT",
                "side": "BUY",
                "status": "NEW",
                "quantity": "10",
            },
            {  # Get order - FILLED
                "orderId": "ORDER123",
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "type": "LIMIT",
                "side": "BUY",
                "status": "FILLED",
                "quantity": "10",
                "filledQuantity": "10",
                "averagePrice": "149.95",
            },
        ]
        mock_api_client.delete.return_value = {}  # Cancel
        
        # Place order
        order_request = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
        )
        new_order = client.place_order(order_request)
        
        assert new_order.order_id == "ORDER123"
        
        # Check initial status
        order = client.get_order(new_order.order_id)
        assert order.status.value == "NEW"
        
        # Check filled status
        order = client.get_order(new_order.order_id)
        assert order.status.value == "FILLED"
        assert order.filled_quantity == Decimal("10")

    def test_get_accounts_flow(self, client, mock_api_client):
        """Test getting accounts."""
        mock_api_client.get.return_value = {
            "accounts": [
                {
                    "accountId": "ACC123",
                    "accountType": "BROKERAGE",
                },
                {
                    "accountId": "IRA456",
                    "accountType": "TRADITIONAL_IRA",
                },
            ]
        }
        
        accounts = client.get_accounts()
        
        assert len(accounts.accounts) == 2
        assert accounts.accounts[0].account_id == "ACC123"
        assert accounts.accounts[0].account_type == AccountType.BROKERAGE
        assert accounts.accounts[1].account_type == AccountType.TRADITIONAL_IRA

    def test_get_portfolio_flow(self, client, mock_api_client):
        """Test getting portfolio."""
        mock_api_client.get.return_value = {
            "accountId": "ACC123",
            "accountType": "BROKERAGE",
            "buyingPower": {
                "cashOnlyBuyingPower": "1000.00",
                "buyingPower": "2000.00",
                "optionsBuyingPower": "500.00",
            },
            "equity": [
                {
                    "type": "STOCK",
                    "value": "5000.00",
                    "percentageOfPortfolio": 50.0,
                }
            ],
            "positions": [],
            "orders": [],
        }
        
        portfolio = client.get_portfolio()
        
        assert portfolio.account_id == "ACC123"
        assert portfolio.buying_power.cash_only_buying_power == Decimal("1000.00")
        assert portfolio.buying_power.buying_power == Decimal("2000.00")
        assert len(portfolio.equity) == 1

    def test_get_quotes_flow(self, client, mock_api_client):
        """Test getting quotes."""
        mock_api_client.post.return_value = {
            "quotes": [
                {
                    "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                    "last": {"value": "150.00"},
                    "bid": {"value": "149.95"},
                    "ask": {"value": "150.05"},
                },
                {
                    "instrument": {"symbol": "MSFT", "type": "EQUITY"},
                    "last": {"value": "250.00"},
                    "bid": {"value": "249.95"},
                    "ask": {"value": "250.05"},
                },
            ]
        }
        
        quotes = client.get_quotes([
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY),
        ])
        
        assert len(quotes) == 2
        assert quotes[0].instrument.symbol == "AAPL"
        assert quotes[0].last.value == Decimal("150.00")
        assert quotes[1].instrument.symbol == "MSFT"

    def test_get_history_flow(self, client, mock_api_client):
        """Test getting account history."""
        mock_api_client.get.return_value = {
            "items": [
                {
                    "type": "ORDER_FILL",
                    "orderId": "ORDER123",
                    "timestamp": "2024-01-15T10:30:00Z",
                }
            ],
            "continuationToken": "next-page-token",
        }
        
        history = client.get_history(HistoryRequest(page_size=10))
        
        assert len(history.items) == 1
        assert history.continuation_token == "next-page-token"

    def test_get_instrument_flow(self, client, mock_api_client):
        """Test getting instrument details."""
        mock_api_client.get.return_value = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "trading": "BUY_AND_SELL",
            "fractionalTrading": "ENABLED",
            "optionTrading": "ENABLED",
            "optionSpreadTrading": "DISABLED",
        }
        
        instrument = client.get_instrument("AAPL", InstrumentType.EQUITY)
        
        assert instrument.instrument.symbol == "AAPL"
        assert instrument.trading.value == "BUY_AND_SELL"

    def test_get_all_instruments_flow(self, client, mock_api_client):
        """Test getting all instruments."""
        mock_api_client.get.return_value = {
            "instruments": [
                {"symbol": "AAPL", "type": "EQUITY"},
                {"symbol": "MSFT", "type": "EQUITY"},
            ],
            "continuationToken": None,
        }
        
        instruments = client.get_all_instruments()
        
        assert len(instruments.instruments) == 2

    def test_preflight_calculation_flow(self, client, mock_api_client):
        """Test preflight calculation."""
        mock_api_client.post.return_value = {
            "estimatedCommission": "0.00",
            "orderValue": "1500.00",
            "buyingPowerRequirement": "1500.00",
            "estimatedCost": "1500.00",
        }
        
        preflight = PreflightRequest(
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
        )
        result = client.perform_preflight_calculation(preflight)
        
        assert result.estimated_commission == Decimal("0.00")
        assert result.order_value == Decimal("1500.00")

    def test_multileg_preflight_flow(self, client, mock_api_client):
        """Test multi-leg preflight calculation."""
        mock_api_client.post.return_value = {
            "strategyName": "VERTICAL_SPREAD",
            "estimatedCommission": "1.00",
            "estimatedCost": "-345.00",
            "buyingPowerRequirement": "1000.00",
        }
        
        from public_api_sdk.models import PreflightMultiLegRequest, OrderLegRequest
        from public_api_sdk.models import LegInstrument, LegInstrumentType, OpenCloseIndicator
        
        preflight = PreflightMultiLegRequest(
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("1"),
            limit_price=Decimal("3.45"),
            legs=[
                OrderLegRequest(
                    instrument=LegInstrument(symbol="AAPL251024C00110000", type=LegInstrumentType.OPTION),
                    side=OrderSide.SELL,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                ),
            ],
        )
        result = client.perform_multi_leg_preflight_calculation(preflight)
        
        assert result.strategy_name == "VERTICAL_SPREAD"
        assert result.estimated_commission == Decimal("1.00")

    def test_option_expirations_flow(self, client, mock_api_client):
        """Test getting option expirations."""
        mock_api_client.post.return_value = {
            "expirations": ["2025-01-17", "2025-01-24", "2025-01-31"],
        }
        
        from public_api_sdk.models import OptionExpirationsRequest
        
        result = client.get_option_expirations(
            OptionExpirationsRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
            )
        )
        
        assert len(result.expirations) == 3
        assert "2025-01-17" in result.expirations

    def test_option_chain_flow(self, client, mock_api_client):
        """Test getting option chain."""
        mock_api_client.post.return_value = {
            "options": [
                {
                    "osiSymbol": "AAPL250117C00150000",
                    "strikePrice": "150.00",
                    "type": "CALL",
                }
            ]
        }
        
        from public_api_sdk.models import OptionChainRequest
        
        result = client.get_option_chain(
            OptionChainRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                expiration_date="2025-01-17",
            )
        )
        
        assert len(result.options) == 1

    def test_option_greeks_flow(self, client, mock_api_client):
        """Test getting option Greeks."""
        mock_api_client.get.return_value = {
            "greeks": [
                {
                    "osiSymbol": "AAPL250117C00150000",
                    "greeks": {
                        "delta": 0.65,
                        "gamma": 0.05,
                        "theta": -0.12,
                        "vega": 0.25,
                    }
                }
            ]
        }
        
        result = client.get_option_greeks(["AAPL250117C00150000"])
        
        assert len(result.greeks) == 1
        assert result.greeks[0].greeks.delta == 0.65

    def test_option_greek_single_flow(self, client, mock_api_client):
        """Test getting single option Greek."""
        mock_api_client.get.return_value = {
            "greeks": [
                {
                    "osiSymbol": "AAPL250117C00150000",
                    "greeks": {
                        "delta": 0.65,
                        "gamma": 0.05,
                        "theta": -0.12,
                        "vega": 0.25,
                    }
                }
            ]
        }
        
        result = client.get_option_greek("AAPL250117C00150000")
        
        assert result.greeks.delta == 0.65

    def test_option_greek_not_found(self, client, mock_api_client):
        """Test getting non-existent option Greek raises error."""
        mock_api_client.get.return_value = {"greeks": []}
        
        with pytest.raises(ValueError, match="No greeks found"):
            client.get_option_greek("INVALID")

    def test_cancel_order_flow(self, client, mock_api_client):
        """Test canceling an order."""
        mock_api_client.delete.return_value = {}
        
        # Should not raise
        client.cancel_order("ORDER123")

    def test_api_endpoint_property(self, client):
        """api_endpoint property should return base URL."""
        assert client.api_endpoint == "https://api.public.com"

    def test_api_endpoint_setter_changes_url(self, client):
        """Setting api_endpoint should change the URL."""
        client.api_endpoint = "https://staging.api.public.com"
        
        assert client.api_endpoint == "https://staging.api.public.com"

    def test_api_endpoint_setter_normalizes_trailing_slash(self, client):
        """api_endpoint setter should normalize trailing slashes."""
        client.api_endpoint = "https://new.api.com/"
        
        assert client.api_endpoint == "https://new.api.com"

    def test_api_endpoint_setter_invalid_type(self, client):
        """Setting api_endpoint to non-string should raise TypeError."""
        with pytest.raises(TypeError, match="must be a string"):
            client.api_endpoint = 123

    def test_close_cleans_up_resources(self, client, mock_api_client):
        """close() should clean up resources."""
        client.close()
        
        mock_api_client.close.assert_called_once()


class TestPublicApiClientWithoutDefaultAccount:
    """Tests for client without default account number."""

    @pytest.fixture
    def client_no_default(self):
        with patch('public_api_sdk.public_api_client.ApiClient') as MockApiClient:
            instance = Mock()
            instance.base_url = "https://api.public.com"
            instance.post.return_value = {"accessToken": "test-token"}
            MockApiClient.return_value = instance
            
            client = PublicApiClient(
                ApiKeyAuthConfig(api_secret_key="test-secret"),
                config=PublicApiClientConfiguration(),  # No default account
            )
            yield client

    def test_get_portfolio_requires_account_id(self, client_no_default):
        """get_portfolio should require account_id when no default set."""
        with pytest.raises(ValueError, match="No account ID"):
            client_no_default.get_portfolio()

    def test_get_portfolio_with_explicit_account(self, client_no_default):
        """get_portfolio should work with explicit account_id."""
        client_no_default.api_client.get.return_value = {
            "accountId": "ACC123",
            "accountType": "BROKERAGE",
            "buyingPower": {
                "cashOnlyBuyingPower": "1000.00",
                "buyingPower": "2000.00",
                "optionsBuyingPower": "500.00",
            },
            "equity": [],
            "positions": [],
            "orders": [],
        }
        
        portfolio = client_no_default.get_portfolio(account_id="ACC123")
        
        assert portfolio.account_id == "ACC123"

    def test_get_quotes_requires_account_id(self, client_no_default):
        """get_quotes should require account_id when no default set."""
        with pytest.raises(ValueError, match="No account ID"):
            client_no_default.get_quotes([OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)])
