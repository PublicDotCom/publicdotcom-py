"""Tests for response model deserialization from realistic API payloads.

These tests verify that camelCase API responses (as returned by the live API)
are correctly deserialized into the SDK's Pydantic models, and that optional
fields degrade gracefully when absent.
"""

from decimal import Decimal

import pytest

from public_api_sdk.models.account import (
    Account,
    AccountsResponse,
    AccountType,
    BrokerageAccountType,
    OptionsLevel,
    TradePermissions,
)
from public_api_sdk.models.history import (
    HistoryResponsePage,
    HistoryTransaction,
    TransactionType,
)
from public_api_sdk.models.instrument import Instrument, InstrumentsResponse, Trading
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.option import (
    GreekValues,
    GreeksResponse,
    OptionGreeks,
)
from public_api_sdk.models.portfolio import BuyingPower, Portfolio, PortfolioPosition
from public_api_sdk.models.quote import Quote, QuoteOutcome


# ---------------------------------------------------------------------------
# AccountsResponse
# ---------------------------------------------------------------------------


class TestAccountsResponseDeserialization:
    def test_full_account(self) -> None:
        payload = {
            "accounts": [
                {
                    "accountId": "ACC-001",
                    "accountType": "BROKERAGE",
                    "optionsLevel": "LEVEL_2",
                    "brokerageAccountType": "MARGIN",
                    "tradePermissions": "BUY_AND_SELL",
                }
            ]
        }
        response = AccountsResponse(**payload)
        account = response.accounts[0]
        assert account.account_id == "ACC-001"
        assert account.account_type == AccountType.BROKERAGE
        assert account.options_level == OptionsLevel.LEVEL_2
        assert account.brokerage_account_type == BrokerageAccountType.MARGIN
        assert account.trade_permissions == TradePermissions.BUY_AND_SELL

    def test_optional_fields_missing(self) -> None:
        payload = {"accounts": [{"accountId": "ACC-002", "accountType": "ROTH_IRA"}]}
        response = AccountsResponse(**payload)
        account = response.accounts[0]
        assert account.account_id == "ACC-002"
        assert account.account_type == AccountType.ROTH_IRA
        assert account.options_level is None
        assert account.brokerage_account_type is None
        assert account.trade_permissions is None

    def test_multiple_accounts(self) -> None:
        payload = {
            "accounts": [
                {"accountId": "ACC-001", "accountType": "BROKERAGE"},
                {"accountId": "ACC-002", "accountType": "TRADITIONAL_IRA"},
                {"accountId": "ACC-003", "accountType": "HIGH_YIELD"},
            ]
        }
        response = AccountsResponse(**payload)
        assert len(response.accounts) == 3
        assert response.accounts[1].account_type == AccountType.TRADITIONAL_IRA

    def test_empty_accounts_list(self) -> None:
        response = AccountsResponse(**{"accounts": []})
        assert response.accounts == []

    def test_all_account_types(self) -> None:
        types = [
            "BROKERAGE",
            "HIGH_YIELD",
            "BOND_ACCOUNT",
            "RIA_ASSET",
            "TREASURY",
            "TRADITIONAL_IRA",
            "ROTH_IRA",
        ]
        for account_type in types:
            account = Account(accountId="ACC", accountType=account_type)
            assert account.account_type == AccountType(account_type)


# ---------------------------------------------------------------------------
# Portfolio
# ---------------------------------------------------------------------------


class TestPortfolioDeserialization:
    def _base_payload(self, account_id: str = "ACC-001") -> dict:
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

    def test_minimal_portfolio(self) -> None:
        portfolio = Portfolio(**self._base_payload())
        assert portfolio.account_id == "ACC-001"
        assert isinstance(portfolio.buying_power, BuyingPower)
        assert portfolio.buying_power.buying_power == Decimal("20000.00")
        assert portfolio.buying_power.cash_only_buying_power == Decimal("10000.00")
        assert portfolio.buying_power.options_buying_power == Decimal("5000.00")

    def test_portfolio_with_position(self) -> None:
        payload = self._base_payload()
        payload["positions"] = [
            {
                "instrument": {
                    "symbol": "AAPL",
                    "name": "Apple Inc.",
                    "type": "EQUITY",
                },
                "quantity": "100",
                "currentValue": "15000.00",
                "percentOfPortfolio": "0.25",
            }
        ]
        portfolio = Portfolio(**payload)
        assert len(portfolio.positions) == 1
        position = portfolio.positions[0]
        assert isinstance(position, PortfolioPosition)
        assert position.instrument.symbol == "AAPL"
        assert position.quantity == Decimal("100")
        assert position.current_value == Decimal("15000.00")

    def test_portfolio_position_optional_fields(self) -> None:
        payload = self._base_payload()
        payload["positions"] = [
            {
                "instrument": {"symbol": "MSFT", "name": "Microsoft", "type": "EQUITY"},
                "quantity": "50",
            }
        ]
        portfolio = Portfolio(**payload)
        position = portfolio.positions[0]
        assert position.current_value is None
        assert position.last_price is None
        assert position.cost_basis is None

    def test_portfolio_with_open_orders(self) -> None:
        payload = self._base_payload()
        payload["orders"] = [
            {
                "orderId": "ORDER-1",
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "type": "LIMIT",
                "side": "BUY",
                "status": "NEW",
                "quantity": "10",
            }
        ]
        portfolio = Portfolio(**payload)
        assert len(portfolio.orders) == 1
        assert portfolio.orders[0].order_id == "ORDER-1"


# ---------------------------------------------------------------------------
# Quote
# ---------------------------------------------------------------------------


class TestQuoteDeserialization:
    def test_full_quote_camelcase(self) -> None:
        """camelCase keys as returned by the API are accepted."""
        payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "outcome": "SUCCESS",
            "last": "150.50",
            "bid": "150.45",
            "bidSize": 100,
            "ask": "150.55",
            "askSize": 200,
            "volume": 5000000,
        }
        quote = Quote(**payload)
        assert quote.outcome == QuoteOutcome.SUCCESS
        assert quote.last == Decimal("150.50")
        assert quote.bid == Decimal("150.45")
        assert quote.bid_size == 100
        assert quote.ask == Decimal("150.55")
        assert quote.ask_size == 200
        assert quote.volume == 5000000

    def test_snake_case_also_accepted(self) -> None:
        """snake_case keys also work because populate_by_name=True."""
        payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "outcome": "SUCCESS",
            "bid_size": 50,
            "ask_size": 75,
        }
        quote = Quote(**payload)
        assert quote.bid_size == 50
        assert quote.ask_size == 75

    def test_unknown_outcome(self) -> None:
        payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "outcome": "UNKNOWN",
        }
        quote = Quote(**payload)
        assert quote.outcome == QuoteOutcome.UNKNOWN
        assert quote.last is None

    def test_all_optional_fields_absent(self) -> None:
        payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "outcome": "UNKNOWN",
        }
        quote = Quote(**payload)
        assert quote.last is None
        assert quote.bid is None
        assert quote.ask is None
        assert quote.bid_size is None
        assert quote.ask_size is None
        assert quote.volume is None
        assert quote.open_interest is None

    def test_open_interest_camelcase(self) -> None:
        payload = {
            "instrument": {"symbol": "AAPL260116C00270000", "type": "EQUITY"},
            "outcome": "SUCCESS",
            "openInterest": 12345,
        }
        quote = Quote(**payload)
        assert quote.open_interest == 12345


# ---------------------------------------------------------------------------
# Instrument
# ---------------------------------------------------------------------------


class TestInstrumentDeserialization:
    def test_equity_instrument_fully_enabled(self) -> None:
        payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "trading": "BUY_AND_SELL",
            "fractionalTrading": "BUY_AND_SELL",
            "optionTrading": "BUY_AND_SELL",
            "optionSpreadTrading": "BUY_AND_SELL",
        }
        instrument = Instrument(**payload)
        assert instrument.instrument.symbol == "AAPL"
        assert instrument.instrument.type == InstrumentType.EQUITY
        assert instrument.trading == Trading.BUY_AND_SELL
        assert instrument.fractional_trading == Trading.BUY_AND_SELL
        assert instrument.option_trading == Trading.BUY_AND_SELL
        assert instrument.option_spread_trading == Trading.BUY_AND_SELL

    def test_instrument_with_disabled_trading(self) -> None:
        payload = {
            "instrument": {"symbol": "XYZ", "type": "EQUITY"},
            "trading": "LIQUIDATION_ONLY",
            "fractionalTrading": "DISABLED",
            "optionTrading": "DISABLED",
            "optionSpreadTrading": "DISABLED",
        }
        instrument = Instrument(**payload)
        assert instrument.trading == Trading.LIQUIDATION_ONLY
        assert instrument.option_trading == Trading.DISABLED

    def test_instrument_details_optional(self) -> None:
        payload = {
            "instrument": {"symbol": "AAPL", "type": "EQUITY"},
            "trading": "BUY_AND_SELL",
            "fractionalTrading": "BUY_AND_SELL",
            "optionTrading": "BUY_AND_SELL",
            "optionSpreadTrading": "BUY_AND_SELL",
        }
        instrument = Instrument(**payload)
        assert instrument.instrument_details is None

    def test_instruments_response_list(self) -> None:
        payload = {
            "instruments": [
                {
                    "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                    "trading": "BUY_AND_SELL",
                    "fractionalTrading": "BUY_AND_SELL",
                    "optionTrading": "BUY_AND_SELL",
                    "optionSpreadTrading": "BUY_AND_SELL",
                },
                {
                    "instrument": {"symbol": "BTC", "type": "CRYPTO"},
                    "trading": "BUY_AND_SELL",
                    "fractionalTrading": "BUY_AND_SELL",
                    "optionTrading": "DISABLED",
                    "optionSpreadTrading": "DISABLED",
                },
            ]
        }
        response = InstrumentsResponse(**payload)
        assert len(response.instruments) == 2
        assert response.instruments[0].instrument.symbol == "AAPL"
        assert response.instruments[1].instrument.symbol == "BTC"


# ---------------------------------------------------------------------------
# HistoryResponsePage
# ---------------------------------------------------------------------------


class TestHistoryDeserialization:
    def test_empty_page(self) -> None:
        payload = {"transactions": []}
        page = HistoryResponsePage(**payload)
        assert len(page.transactions) == 0
        assert page.next_token is None
        assert page.page_size is None

    def test_trade_transaction(self) -> None:
        payload = {
            "transactions": [
                {
                    "id": "txn-001",
                    "timestamp": "2025-01-15T10:30:00Z",
                    "type": "TRADE",
                    "subType": "TRADE",
                    "accountNumber": "ACC-001",
                    "symbol": "AAPL",
                    "securityType": "EQUITY",
                    "side": "BUY",
                    "netAmount": "-1500.00",
                    "principalAmount": "1500.00",
                    "quantity": "10",
                    "fees": "0.00",
                }
            ]
        }
        page = HistoryResponsePage(**payload)
        txn = page.transactions[0]
        assert isinstance(txn, HistoryTransaction)
        assert txn.id == "txn-001"
        assert txn.type == TransactionType.TRADE
        assert txn.symbol == "AAPL"
        assert txn.net_amount == Decimal("-1500.00")
        assert txn.quantity == Decimal("10")

    def test_money_movement_transaction(self) -> None:
        payload = {
            "transactions": [
                {
                    "id": "txn-002",
                    "timestamp": "2025-01-10T09:00:00Z",
                    "type": "MONEY_MOVEMENT",
                    "subType": "DEPOSIT",
                    "netAmount": "5000.00",
                    "direction": "INCOMING",
                }
            ]
        }
        page = HistoryResponsePage(**payload)
        txn = page.transactions[0]
        assert txn.type == TransactionType.MONEY_MOVEMENT
        assert txn.net_amount == Decimal("5000.00")

    def test_transaction_optional_fields_absent(self) -> None:
        payload = {
            "transactions": [
                {
                    "id": "txn-003",
                    "timestamp": "2025-01-12T12:00:00Z",
                    "type": "POSITION_ADJUSTMENT",
                }
            ]
        }
        page = HistoryResponsePage(**payload)
        txn = page.transactions[0]
        assert txn.symbol is None
        assert txn.net_amount is None
        assert txn.side is None

    def test_pagination_fields(self) -> None:
        payload = {
            "transactions": [],
            "nextToken": "TOKEN_FOR_PAGE_2",
            "pageSize": 25,
        }
        page = HistoryResponsePage(**payload)
        assert page.next_token == "TOKEN_FOR_PAGE_2"
        assert page.page_size == 25

    def test_multiple_transactions(self) -> None:
        payload = {
            "transactions": [
                {
                    "id": f"txn-{i}",
                    "timestamp": "2025-01-15T10:30:00Z",
                    "type": "TRADE",
                }
                for i in range(5)
            ]
        }
        page = HistoryResponsePage(**payload)
        assert len(page.transactions) == 5
        assert page.transactions[4].id == "txn-4"


# ---------------------------------------------------------------------------
# GreeksResponse
# ---------------------------------------------------------------------------


class TestGreeksResponseDeserialization:
    def _greek_values(self) -> dict:
        return {
            "delta": "0.52",
            "gamma": "0.015",
            "theta": "-0.04",
            "vega": "0.18",
            "rho": "0.08",
            "impliedVolatility": "0.30",
        }

    def test_single_greek(self) -> None:
        payload = {
            "greeks": [
                {"symbol": "AAPL260116C00270000", "greeks": self._greek_values()}
            ]
        }
        response = GreeksResponse(**payload)
        assert len(response.greeks) == 1
        greek = response.greeks[0]
        assert isinstance(greek, OptionGreeks)
        assert greek.symbol == "AAPL260116C00270000"
        assert isinstance(greek.greeks, GreekValues)
        assert greek.greeks.delta == Decimal("0.52")
        assert greek.greeks.implied_volatility == Decimal("0.30")

    def test_multiple_greeks(self) -> None:
        payload = {
            "greeks": [
                {"symbol": "AAPL260116C00270000", "greeks": self._greek_values()},
                {"symbol": "AAPL260116P00270000", "greeks": self._greek_values()},
            ]
        }
        response = GreeksResponse(**payload)
        assert len(response.greeks) == 2

    def test_implied_volatility_camelcase_alias(self) -> None:
        values = self._greek_values()
        greek_values = GreekValues(**values)
        assert greek_values.implied_volatility == Decimal("0.30")

    def test_empty_greeks_list(self) -> None:
        response = GreeksResponse(**{"greeks": []})
        assert response.greeks == []
