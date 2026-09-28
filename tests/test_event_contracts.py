"""Tests for the 2026-09-28 spec revision:

- ``EVENTCONTRACT`` added to the security-type enums (``InstrumentType``,
  ``TransactionSecurityType``) and accepted by ``get_bars``;
- ``get_event_contract_bars`` (GET
  /historicdata/event-contracts/{eventId}/bars/{period}) and its models
  (``EventContractBarPeriod``, ``EventContractChart``,
  ``EventContractChartsResponse``);
- ``get_order`` now returning ``OrderV2`` (the spec's ``GatewayOrderV2``).

Client tests patch ApiClient/AsyncApiClient and the auth managers at
construction time so no real HTTP calls are made, mirroring the other client
test modules.
"""

import warnings
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest

import public_api_sdk
from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.exceptions import NotFoundError
from public_api_sdk.models import (
    Bar,
    BarPeriod,
    EventContractBarPeriod,
    EventContractChart,
    EventContractChartsResponse,
    InstrumentsRequest,
    InstrumentType,
    Order,
    OrderInstrument,
    OrderMarketSession,
    OrderSearchRequest,
    OrderV2,
)
from public_api_sdk.models.history import HistoryTransaction, TransactionSecurityType
from public_api_sdk.models.portfolio import PortfolioInstrument

_ACCOUNT = "ACC123"
_ORDER_ID = "550e8400-e29b-41d4-a716-446655440000"
_EVENT_ID = "KALSHI.KXBALANCESHEET-EO26-EVENT"
_YES = "KALSHI.KXBALANCESHEET-EO26-6.6.Y-EVENTCONTRACT"
_NO = "KALSHI.KXBALANCESHEET-EO26-6.6.N-EVENTCONTRACT"
_BARS_URL = f"/userapigateway/historicdata/event-contracts/{_EVENT_ID}/bars"


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
# Payload builders (shapes taken from the spec's Bar / EventContractChart /
# EventContractChartsResponse / GatewayOrderV2)
# ---------------------------------------------------------------------------


def _bar_payload(timestamp: str, price: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "timestamp": timestamp,
        "open": price,
        "close": price,
        "high": price,
        "low": price,
        "value": price,
        "volume": 120,
    }
    payload.update(overrides)
    return payload


def _chart_payload(symbol: str = _YES, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "symbol": symbol,
        "previousClosePrice": "0.41",
        "currentPrice": "0.47",
        "totalGainLoss": "0.06",
        "totalGainLossPercentage": "14.63",
        "bars": [
            _bar_payload("2026-09-27T14:00:00Z", "0.41"),
            _bar_payload("2026-09-27T15:00:00Z", "0.47", gainAmount="0.06"),
        ],
    }
    payload.update(overrides)
    return payload


def _charts_payload(*charts: Dict[str, Any], period: str = "DAY") -> Dict[str, Any]:
    return {"period": period, "charts": list(charts)}


def _order_v2_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "orderId": _ORDER_ID,
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "createdAt": "2026-09-27T14:30:00Z",
        "type": "LIMIT",
        "side": "BUY",
        "status": "FILLED",
        "quantity": "10",
        "expiration": {"timeInForce": "DAY"},
        "limitPrice": "190.00",
        "filledQuantity": "10",
        "averagePrice": "189.40",
        "equityMarketSession": "REGULAR",
        "filledAt": "2026-09-27T14:30:07Z",
        "trades": [
            {
                "instrument": {"symbol": "AAPL", "type": "EQUITY"},
                "quantity": "10",
                "price": "189.40",
                "side": "BUY",
                "tradeId": "trade-1",
                "timestamp": "2026-09-27T14:30:07Z",
            }
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# EVENTCONTRACT enum value
# ---------------------------------------------------------------------------


class TestEventContractSecurityType:
    def test_instrument_type_has_eventcontract(self) -> None:
        assert InstrumentType("EVENTCONTRACT") is InstrumentType.EVENTCONTRACT

    def test_transaction_security_type_has_eventcontract(self) -> None:
        assert (
            TransactionSecurityType("EVENTCONTRACT")
            is TransactionSecurityType.EVENTCONTRACT
        )

    def test_order_instrument_parses(self) -> None:
        instrument = OrderInstrument(**{"symbol": _YES, "type": "EVENTCONTRACT"})
        assert instrument.type is InstrumentType.EVENTCONTRACT

    def test_portfolio_instrument_parses(self) -> None:
        instrument = PortfolioInstrument(
            **{"symbol": _YES, "name": "Balance sheet > $6.6T", "type": "EVENTCONTRACT"}
        )
        assert instrument.type is InstrumentType.EVENTCONTRACT

    def test_history_transaction_parses(self) -> None:
        transaction = HistoryTransaction(
            **{
                "id": "tx-1",
                "timestamp": "2026-09-27T14:30:07Z",
                "type": "TRADE",
                "symbol": _YES,
                "securityType": "EVENTCONTRACT",
                "side": "BUY",
            }
        )
        assert transaction.security_type is TransactionSecurityType.EVENTCONTRACT

    def test_order_search_filter_serializes(self) -> None:
        request = OrderSearchRequest(security_type=InstrumentType.EVENTCONTRACT)
        assert request.model_dump(by_alias=True, exclude_none=True) == {
            "securityType": "EVENTCONTRACT"
        }

    def test_instruments_type_filter_serializes(self) -> None:
        request = InstrumentsRequest(type_filter=[InstrumentType.EVENTCONTRACT])
        dumped = request.model_dump(by_alias=True, exclude_none=True)
        assert dumped["typeFilter"] == [InstrumentType.EVENTCONTRACT]
        assert dumped["typeFilter"][0] == "EVENTCONTRACT"

    def test_get_bars_accepts_eventcontract(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(side_effect=RuntimeError("stop"))
        with pytest.raises(RuntimeError, match="stop"):
            client.get_bars(
                _YES, BarPeriod.WEEK, instrument_type=InstrumentType.EVENTCONTRACT
            )
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/historicdata/EVENTCONTRACT/{_YES}/WEEK"

    @pytest.mark.asyncio
    async def test_async_get_bars_accepts_eventcontract(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(side_effect=RuntimeError("stop"))
        with pytest.raises(RuntimeError, match="stop"):
            await client.get_bars(
                _YES, BarPeriod.DAY, instrument_type=InstrumentType.EVENTCONTRACT
            )
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/historicdata/EVENTCONTRACT/{_YES}/DAY"

    def test_get_bars_still_rejects_unsupported_type(self) -> None:
        client = _make_client()
        with pytest.raises(ValueError, match="EVENTCONTRACT"):
            client.get_bars(
                "US912797", BarPeriod.WEEK, instrument_type=InstrumentType.TREASURY
            )


# ---------------------------------------------------------------------------
# Event-contract chart models
# ---------------------------------------------------------------------------


class TestEventContractModels:
    def test_period_enum_matches_spec(self) -> None:
        assert {p.value for p in EventContractBarPeriod} == {
            "DAY",
            "WEEK",
            "MONTH",
            "ALL",
        }

    def test_chart_parses_prices_as_decimals(self) -> None:
        chart = EventContractChart(**_chart_payload())
        assert chart.symbol == _YES
        assert chart.previous_close_price == Decimal("0.41")
        assert chart.current_price == Decimal("0.47")
        assert chart.total_gain_loss == Decimal("0.06")
        assert chart.total_gain_loss_percentage == Decimal("14.63")
        assert len(chart.bars) == 2
        assert isinstance(chart.bars[0], Bar)
        assert chart.bars[1].close == Decimal("0.47")
        assert chart.bars[1].gain_amount == Decimal("0.06")
        assert chart.bars[0].volume == Decimal("120")

    def test_chart_nullable_prices(self) -> None:
        chart = EventContractChart(
            **_chart_payload(
                previousClosePrice=None,
                currentPrice=None,
                totalGainLoss=None,
                totalGainLossPercentage=None,
            )
        )
        assert chart.previous_close_price is None
        assert chart.current_price is None
        assert chart.total_gain_loss is None
        assert chart.total_gain_loss_percentage is None

    def test_chart_missing_bars_defaults_to_empty(self) -> None:
        chart = EventContractChart(**{"symbol": _YES})
        assert chart.bars == []

    def test_chart_accepts_snake_case(self) -> None:
        chart = EventContractChart(symbol=_YES, current_price=Decimal("0.5"))
        assert chart.current_price == Decimal("0.5")

    def test_chart_serializes_camel_case(self) -> None:
        dumped = EventContractChart(**_chart_payload()).model_dump(by_alias=True)
        assert "previousClosePrice" in dumped
        assert "totalGainLossPercentage" in dumped

    def test_response_parses_charts_with_different_start_times(self) -> None:
        no_chart = _chart_payload(
            symbol=_NO, bars=[_bar_payload("2026-09-27T15:00:00Z", "0.53")]
        )
        response = EventContractChartsResponse(
            **_charts_payload(_chart_payload(), no_chart)
        )
        assert response.period == "DAY"
        assert [c.symbol for c in response.charts] == [_YES, _NO]
        # Charts are aligned by timestamp, not by index.
        assert (
            response.charts[0].bars[1].timestamp == response.charts[1].bars[0].timestamp
        )

    def test_response_missing_charts_defaults_to_empty(self) -> None:
        response = EventContractChartsResponse(**{"period": "ALL"})
        assert response.charts == []

    def test_models_exported_top_level(self) -> None:
        for name in (
            "EventContractBarPeriod",
            "EventContractChart",
            "EventContractChartsResponse",
        ):
            assert hasattr(public_api_sdk, name)
            assert name in public_api_sdk.__all__


# ---------------------------------------------------------------------------
# get_event_contract_bars — sync
# ---------------------------------------------------------------------------


class TestGetEventContractBars:
    def test_builds_url_and_symbols_query(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_charts_payload(_chart_payload()))
        response = client.get_event_contract_bars(
            _EVENT_ID, EventContractBarPeriod.DAY, [_YES, _NO]
        )
        args, kwargs = client.api_client.get.call_args
        assert args[0] == f"{_BARS_URL}/DAY"
        assert kwargs["params"] == {"symbols": f"{_YES},{_NO}"}
        assert isinstance(response, EventContractChartsResponse)
        assert response.charts[0].symbol == _YES

    @pytest.mark.parametrize("period", list(EventContractBarPeriod))
    def test_every_period_in_path(self, period: EventContractBarPeriod) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_charts_payload(period=period.value))
        client.get_event_contract_bars(_EVENT_ID, period, [_YES])
        assert client.api_client.get.call_args[0][0] == f"{_BARS_URL}/{period.value}"

    def test_refreshes_token_first(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_charts_payload())
        client.get_event_contract_bars(_EVENT_ID, EventContractBarPeriod.WEEK, [_YES])
        client.auth_manager.refresh_token_if_needed.assert_called_once()

    def test_does_not_need_account(self) -> None:
        client = _make_client(default_account=None)
        client.api_client.get = Mock(return_value=_charts_payload())
        client.get_event_contract_bars(_EVENT_ID, EventContractBarPeriod.WEEK, [_YES])
        client.api_client.get.assert_called_once()

    def test_single_string_is_one_symbol(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_charts_payload())
        client.get_event_contract_bars(_EVENT_ID, EventContractBarPeriod.MONTH, _YES)  # type: ignore[arg-type]
        assert client.api_client.get.call_args.kwargs["params"] == {"symbols": _YES}

    def test_strips_blank_symbols(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_charts_payload())
        client.get_event_contract_bars(
            _EVENT_ID, EventContractBarPeriod.ALL, [f" {_YES} ", "", "  "]
        )
        assert client.api_client.get.call_args.kwargs["params"] == {"symbols": _YES}

    def test_eight_symbols_allowed(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_charts_payload())
        symbols = [f"S{i}-EVENTCONTRACT" for i in range(8)]
        client.get_event_contract_bars(_EVENT_ID, EventContractBarPeriod.DAY, symbols)
        assert (
            client.api_client.get.call_args.kwargs["params"]["symbols"].count(",") == 7
        )

    def test_more_than_eight_symbols_raises(self) -> None:
        client = _make_client()
        client.api_client.get = Mock()
        symbols = [f"S{i}-EVENTCONTRACT" for i in range(9)]
        with pytest.raises(ValueError, match="At most 8"):
            client.get_event_contract_bars(
                _EVENT_ID, EventContractBarPeriod.DAY, symbols
            )
        client.api_client.get.assert_not_called()

    @pytest.mark.parametrize("symbols", [[], ["", " "]])
    def test_no_symbols_raises(self, symbols: List[str]) -> None:
        client = _make_client()
        client.api_client.get = Mock()
        with pytest.raises(ValueError, match="At least one"):
            client.get_event_contract_bars(
                _EVENT_ID, EventContractBarPeriod.DAY, symbols
            )
        client.api_client.get.assert_not_called()

    def test_empty_event_id_raises(self) -> None:
        client = _make_client()
        client.api_client.get = Mock()
        with pytest.raises(ValueError, match="event_id"):
            client.get_event_contract_bars("", EventContractBarPeriod.DAY, [_YES])
        client.api_client.get.assert_not_called()

    def test_404_propagates_as_not_found(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(
            side_effect=NotFoundError(
                "No data for any requested event contract", 404, {}
            )
        )
        with pytest.raises(NotFoundError):
            client.get_event_contract_bars(
                _EVENT_ID, EventContractBarPeriod.DAY, [_YES]
            )


# ---------------------------------------------------------------------------
# get_event_contract_bars — async
# ---------------------------------------------------------------------------


class TestAsyncGetEventContractBars:
    @pytest.mark.asyncio
    async def test_builds_url_and_symbols_query(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(
            return_value=_charts_payload(_chart_payload(), _chart_payload(symbol=_NO))
        )
        response = await client.get_event_contract_bars(
            _EVENT_ID, EventContractBarPeriod.WEEK, [_YES, _NO]
        )
        args, kwargs = client.api_client.get.call_args
        assert args[0] == f"{_BARS_URL}/WEEK"
        assert kwargs["params"] == {"symbols": f"{_YES},{_NO}"}
        assert [c.symbol for c in response.charts] == [_YES, _NO]
        client.auth_manager.refresh_token_if_needed.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_more_than_eight_symbols_raises(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock()
        with pytest.raises(ValueError, match="At most 8"):
            await client.get_event_contract_bars(
                _EVENT_ID,
                EventContractBarPeriod.DAY,
                [f"S{i}-EVENTCONTRACT" for i in range(9)],
            )
        client.api_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_symbols_raises(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock()
        with pytest.raises(ValueError, match="At least one"):
            await client.get_event_contract_bars(
                _EVENT_ID, EventContractBarPeriod.DAY, []
            )

    @pytest.mark.asyncio
    async def test_empty_event_id_raises(self) -> None:
        client = _make_async_client()
        with pytest.raises(ValueError, match="event_id"):
            await client.get_event_contract_bars("", EventContractBarPeriod.DAY, [_YES])


# ---------------------------------------------------------------------------
# get_order now returns OrderV2
# ---------------------------------------------------------------------------


class TestGetOrderReturnsOrderV2:
    def test_returns_order_v2_from_get_order_endpoint(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_order_v2_payload())
        order = client.get_order(_ORDER_ID)
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/trading/{_ACCOUNT}/order/{_ORDER_ID}"
        assert isinstance(order, OrderV2)
        assert isinstance(order, Order)  # existing callers keep working
        assert order.equity_market_session is OrderMarketSession.REGULAR
        assert order.trades is not None and order.trades[0].trade_id == "trade-1"

    def test_v1_shaped_payload_still_parses(self) -> None:
        client = _make_client()
        payload = _order_v2_payload()
        for key in ("equityMarketSession", "filledAt", "trades"):
            payload.pop(key)
        client.api_client.get = Mock(return_value=payload)
        order = client.get_order(_ORDER_ID)
        assert isinstance(order, OrderV2)
        assert order.trades is None
        assert order.equity_market_session is None

    def test_get_order_does_not_warn(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_order_v2_payload())
        with warnings.catch_warnings():
            warnings.simplefilter("error")
            client.get_order(_ORDER_ID)

    def test_get_order_v2_delegates_to_get_order(self) -> None:
        client = _make_client()
        sentinel = OrderV2(**_order_v2_payload())
        client.get_order = Mock(return_value=sentinel)  # type: ignore[method-assign]
        with pytest.warns(DeprecationWarning, match="use get_order"):
            result = client.get_order_v2(_ORDER_ID, account_id="OTHER_ACC")
        assert result is sentinel
        client.get_order.assert_called_once_with(_ORDER_ID, account_id="OTHER_ACC")

    @pytest.mark.asyncio
    async def test_async_returns_order_v2(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_order_v2_payload())
        order = await client.get_order(_ORDER_ID)
        url = client.api_client.get.call_args[0][0]
        assert url == f"/userapigateway/trading/{_ACCOUNT}/order/{_ORDER_ID}"
        assert isinstance(order, OrderV2) and isinstance(order, Order)
        assert order.trades is not None and len(order.trades) == 1

    @pytest.mark.asyncio
    async def test_async_get_order_v2_delegates_to_get_order(self) -> None:
        client = _make_async_client()
        sentinel = OrderV2(**_order_v2_payload())
        client.get_order = AsyncMock(return_value=sentinel)  # type: ignore[method-assign]
        with pytest.warns(DeprecationWarning, match="use get_order"):
            result = await client.get_order_v2(_ORDER_ID)
        assert result is sentinel
        client.get_order.assert_awaited_once_with(_ORDER_ID, account_id=None)
