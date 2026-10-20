"""Tests for the recurring-market helpers (e.g. 15-minute windows).

- ``get_current_event`` / ``wait_for_current_event``;
- ``buy_event_contract`` / ``preflight_buy_event_contract``;
- ``wait_for_settlement``;
- the read-only shortcuts on ``EventOutcome`` and ``EventDetails``.

None of these is an API endpoint: they combine the event-contract discovery
and order endpoints, which are patched out here.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID

import pytest

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
    WaitTimeoutError,
)
from public_api_sdk.models import (
    EventContract,
    EventContractSide,
    EventDetails,
    EventFrequency,
    EventOutcome,
    EventOutcomeState,
    EventSettledOutcome,
    EventSortingMode,
    EventSummary,
    EventSummaryPage,
    EventTradingMode,
    InstrumentType,
    NewOrder,
    OrderRequest,
    OrderSide,
    OrderType,
    PreflightRequest,
    PreflightResponse,
    TimeInForce,
)

_SERIES = "KXBTC15M"
_EVENT = "KALSHI.KXBTC15M-26OCT201200"
_OUTCOME_ID = "KXBTC15M-26OCT201200-00"
_YES = "KALSHI.KXBTC15M-26OCT201200-00.Y"
_NO = "KALSHI.KXBTC15M-26OCT201200-00.N"
_VALID_UUID = "0d2abd8d-3625-4c83-a806-98abf35567cc"


def _make_client() -> PublicApiClient:
    with (
        patch("public_api_sdk.public_api_client.ApiClient"),
        patch("public_api_sdk.public_api_client.AuthManager"),
    ):
        return PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=PublicApiClientConfiguration(default_account_number="ACC123"),
        )


def _make_async_client() -> AsyncPublicApiClient:
    with (
        patch("public_api_sdk.async_public_api_client.AsyncApiClient"),
        patch("public_api_sdk.async_public_api_client.AsyncAuthManager"),
    ):
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=AsyncPublicApiClientConfiguration(default_account_number="ACC123"),
        )
    client.auth_manager.refresh_token_if_needed = AsyncMock()
    return client


def _in(minutes: float) -> datetime:
    return datetime.now(timezone.utc) + timedelta(minutes=minutes)


def _summary(symbol: str, resolves_in: float, resolved: bool = False) -> EventSummary:
    return EventSummary(
        event_symbol=symbol, resolution_time=_in(resolves_in), resolved=resolved
    )


def _page(*events: EventSummary, next_token: Optional[str] = None) -> EventSummaryPage:
    return EventSummaryPage(content=list(events), next_token=next_token)


def _contract(symbol: str, side: str, ask: Optional[str] = "0.835") -> EventContract:
    return EventContract(
        symbol=symbol,
        predicted_outcome=EventContractSide(side),
        bid=Decimal("0.82"),
        ask=Decimal(ask) if ask is not None else None,
    )


def _outcome(
    closes_in: Optional[float] = 2,
    state: EventOutcomeState = EventOutcomeState.STATE_OPEN,
    trading: EventTradingMode = EventTradingMode.BUY_AND_SELL,
    settled: Optional[EventSettledOutcome] = None,
    outcome_id: str = _OUTCOME_ID,
) -> EventOutcome:
    payload: Dict[str, Any] = {
        "outcomeId": outcome_id,
        "title": "Target Price: $82,438.08",
        "state": state.value,
        "trading": trading.value,
        "contracts": [
            {"symbol": _YES, "predictedOutcome": "YES", "ask": "0.835"},
            {"symbol": _NO, "predictedOutcome": "NO", "ask": "0.175"},
        ],
    }
    if closes_in is not None:
        payload["timeline"] = {"closeTime": _in(closes_in).isoformat()}
    if settled is not None:
        payload["settledOutcome"] = settled.value
    return EventOutcome(**payload)


def _details(*outcomes: EventOutcome) -> EventDetails:
    return EventDetails(event_symbol=_EVENT, outcomes=list(outcomes))


_SETTLED_YES = _outcome(
    closes_in=-5,
    state=EventOutcomeState.STATE_SETTLED,
    trading=EventTradingMode.DISABLED,
    settled=EventSettledOutcome.SETTLED_OUTCOME_YES,
)


# ---------------------------------------------------------------------------
# Model shortcuts
# ---------------------------------------------------------------------------


class TestOutcomeShortcuts:
    def test_yes_and_no(self) -> None:
        outcome = _outcome()
        assert outcome.yes is not None and outcome.yes.symbol == _YES
        assert outcome.no is not None and outcome.no.symbol == _NO

    def test_missing_side_is_none(self) -> None:
        outcome = EventOutcome(
            outcome_id=_OUTCOME_ID, contracts=[_contract(_YES, "YES")]
        )
        assert outcome.no is None

    def test_close_time_and_seconds_left(self) -> None:
        outcome = _outcome(closes_in=2)
        assert outcome.close_time is not None
        assert outcome.seconds_left is not None
        assert 110 < outcome.seconds_left <= 120

    def test_seconds_left_is_zero_after_close(self) -> None:
        assert _outcome(closes_in=-1).seconds_left == 0.0

    def test_seconds_left_treats_naive_close_time_as_utc(self) -> None:
        naive = datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(minutes=2)
        outcome = EventOutcome(outcome_id=_OUTCOME_ID, timeline={"closeTime": naive})
        assert outcome.seconds_left is not None and 110 < outcome.seconds_left <= 120

    def test_no_timeline(self) -> None:
        outcome = _outcome(closes_in=None)
        assert outcome.close_time is None
        assert outcome.seconds_left is None
        assert outcome.is_tradable is True

    @pytest.mark.parametrize(
        "kwargs, tradable",
        [
            ({}, True),
            # the API still reports STATE_OPEN for a few minutes after close
            ({"closes_in": -1}, False),
            ({"state": EventOutcomeState.STATE_HALTED}, False),
            ({"state": EventOutcomeState.STATE_CLOSED}, False),
            ({"trading": EventTradingMode.LIQUIDATION_ONLY}, False),
            ({"trading": EventTradingMode.DISABLED}, False),
        ],
    )
    def test_is_tradable(self, kwargs: Dict[str, Any], tradable: bool) -> None:
        assert _outcome(**kwargs).is_tradable is tradable

    def test_winner_and_won(self) -> None:
        assert _SETTLED_YES.winner is not None
        assert _SETTLED_YES.winner.symbol == _YES
        assert _SETTLED_YES.won(_SETTLED_YES.yes) is True  # type: ignore[arg-type]
        assert _SETTLED_YES.won(_NO) is False
        assert _SETTLED_YES.won(f" {_YES} ") is True

    def test_winner_no(self) -> None:
        outcome = _outcome(settled=EventSettledOutcome.SETTLED_OUTCOME_NO)
        assert outcome.winner is not None and outcome.winner.symbol == _NO

    @pytest.mark.parametrize(
        "settled",
        [
            None,
            EventSettledOutcome.SETTLED_OUTCOME_UNSPECIFIED,
            EventSettledOutcome.SETTLED_OUTCOME_OTHER,
            EventSettledOutcome.UNKNOWN,
        ],
    )
    def test_no_winner(self, settled: Optional[EventSettledOutcome]) -> None:
        outcome = _outcome(settled=settled)
        assert outcome.winner is None
        assert outcome.won(_YES) is None

    def test_shortcuts_are_not_serialized(self) -> None:
        outcome = _outcome()
        dumped = outcome.model_dump(by_alias=True, mode="json")
        for name in (
            "yes",
            "no",
            "close_time",
            "seconds_left",
            "is_tradable",
            "winner",
        ):
            assert name not in dumped
            assert name not in outcome.model_dump()
        assert EventOutcome(**dumped) == outcome


class TestDetailsOutcome:
    def test_single_outcome(self) -> None:
        outcome = _outcome()
        assert _details(outcome).outcome == outcome

    @pytest.mark.parametrize("count", [0, 2])
    def test_not_single_outcome(self, count: int) -> None:
        outcomes = [_outcome(outcome_id=f"O{i}") for i in range(count)]
        assert _details(*outcomes).outcome is None

    def test_not_serialized(self) -> None:
        details = _details(_outcome())
        dumped = details.model_dump(by_alias=True, mode="json")
        assert "outcome" not in dumped
        assert EventDetails(**dumped) == details


# ---------------------------------------------------------------------------
# get_current_event / wait_for_current_event
# ---------------------------------------------------------------------------


class TestGetCurrentEvent:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_request(self) -> None:
        self.client.get_event_summary = Mock(return_value=_page())
        self.client.get_current_event(_SERIES, category="Crypto", subcategory="BTC")
        (request,), _ = self.client.get_event_summary.call_args
        assert request.model_dump(by_alias=True, exclude_none=True) == {
            "sortingMode": "EXPIRATION",
            "category": "Crypto",
            "subcategory": "BTC",
            "displayResolvedEvents": False,
            "filters": {"eventSymbols": [], "frequencies": ["FIFTEEN_MINUTES"]},
        }

    def test_frequency_argument(self) -> None:
        self.client.get_event_summary = Mock(return_value=_page())
        self.client.get_current_event("KXBTCD", EventFrequency.ONE_HOUR)
        (request,), _ = self.client.get_event_summary.call_args
        assert request.filters.frequencies == [EventFrequency.ONE_HOUR]
        assert request.sorting_mode == EventSortingMode.EXPIRATION

    def test_picks_soonest_open_event_of_series(self) -> None:
        current = _summary(_EVENT, resolves_in=8)
        self.client.get_event_summary = Mock(
            return_value=_page(
                _summary("KALSHI.KXBTC15M-26OCT201145", resolves_in=-1),  # closed
                _summary("KALSHI.KXETH15M-26OCT201200", resolves_in=1),  # other series
                _summary("KALSHI.KXBTC15M-26OCT201215", resolves_in=23),
                current,
                _summary("KALSHI.KXBTC15M-26OCT201130", resolves_in=5, resolved=True),
                EventSummary(event_symbol="KALSHI.KXBTC15M-NOTIME"),
            )
        )
        assert self.client.get_current_event("kxbtc15m ") == current

    def test_pages_through_results(self) -> None:
        current = _summary(_EVENT, resolves_in=8)
        self.client.get_event_summary = Mock(
            side_effect=[
                _page(_summary("KALSHI.KXETH15M-26OCT201200", 8), next_token="t2"),
                _page(current),
            ]
        )
        assert self.client.get_current_event(_SERIES) == current
        second_request = self.client.get_event_summary.call_args_list[1][0][0]
        assert second_request.next_token == "t2"

    def test_none_when_no_open_event(self) -> None:
        self.client.get_event_summary = Mock(
            return_value=_page(_summary("KALSHI.KXBTC15M-26OCT201145", -1))
        )
        assert self.client.get_current_event(_SERIES) is None

    @pytest.mark.parametrize("series", ["", "   "])
    def test_empty_series(self, series: str) -> None:
        self.client.get_event_summary = Mock()
        with pytest.raises(ValueError, match="series is required"):
            self.client.get_current_event(series)
        self.client.get_event_summary.assert_not_called()


class TestWaitForCurrentEvent:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_waits_until_listed(self) -> None:
        current = _summary(_EVENT, 14)
        self.client.get_current_event = Mock(side_effect=[None, None, current])
        with patch("public_api_sdk.public_api_client.time.sleep") as sleep:
            result = self.client.wait_for_current_event(
                _SERIES, category="Crypto", poll_interval=5
            )
        assert result == current
        assert sleep.call_count == 2
        sleep.assert_called_with(5)
        self.client.get_current_event.assert_called_with(
            _SERIES, EventFrequency.FIFTEEN_MINUTES, category="Crypto", subcategory=None
        )

    def test_timeout(self) -> None:
        self.client.get_current_event = Mock(return_value=None)
        with pytest.raises(WaitTimeoutError, match="No open KXBTC15M event"):
            self.client.wait_for_current_event(_SERIES, timeout=0)
        self.client.get_current_event.assert_called_once()

    def test_sleep_never_overshoots_timeout(self) -> None:
        self.client.get_current_event = Mock(return_value=None)
        with patch("public_api_sdk.public_api_client.time.sleep") as sleep:
            with pytest.raises(WaitTimeoutError):
                self.client.wait_for_current_event(
                    _SERIES, timeout=0.05, poll_interval=30
                )
        assert all(call.args[0] <= 0.05 for call in sleep.call_args_list)


# ---------------------------------------------------------------------------
# buy_event_contract / preflight_buy_event_contract
# ---------------------------------------------------------------------------


class TestBuyEventContract:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.mock_order = Mock(spec=NewOrder)
        self.client.place_order = Mock(return_value=self.mock_order)

    def _request(self) -> Any:
        request, _ = self.client.place_order.call_args[0]
        return request

    def test_limit_at_ask_rounded_up_to_cent(self) -> None:
        result = self.client.buy_event_contract(_contract(_YES, "YES", ask="0.831"))
        assert result is self.mock_order
        request = self._request()
        assert request.instrument.symbol == _YES
        assert request.instrument.type == InstrumentType.EVENTCONTRACT
        assert request.order_side == OrderSide.BUY
        assert request.order_type == OrderType.LIMIT
        assert request.limit_price == Decimal("0.84")
        assert request.quantity == Decimal("1")
        assert request.expiration.time_in_force == TimeInForce.DAY
        assert UUID(request.order_id).version == 4
        body = request.model_dump(by_alias=True, exclude_none=True)
        assert body["limitPrice"] == "0.84"
        # the API rejects event-contract quantities with more than 2 decimals
        assert body["quantity"] == "1.00"
        assert body["instrument"] == {"symbol": _YES, "type": "EVENTCONTRACT"}

    def test_whole_cent_ask_is_kept(self) -> None:
        self.client.buy_event_contract(_contract(_YES, "YES", ask="0.83"))
        assert self._request().limit_price == Decimal("0.83")

    def test_explicit_arguments(self) -> None:
        self.client.buy_event_contract(
            _YES,
            quantity=3,
            limit_price=0.8,
            order_id=_VALID_UUID,
            account_id="ACC456",
        )
        request, account_id = self.client.place_order.call_args[0]
        assert request.limit_price == Decimal("0.8")
        assert request.quantity == Decimal("3")
        assert request.order_id == _VALID_UUID
        assert account_id == "ACC456"

    @pytest.mark.parametrize(
        "contract, kwargs, message",
        [
            (_YES, {}, "limit_price is required"),
            (_contract(_YES, "YES", ask=None), {}, "has no ask"),
            (_YES, {"limit_price": "0.835"}, "whole cents"),
            (_YES, {"limit_price": 1}, "between 0.01 and 0.99"),
            (_YES, {"limit_price": 0}, "between 0.01 and 0.99"),
            (_contract(_YES, "YES", ask="0.995"), {}, "between 0.01 and 0.99"),
            ("  ", {"limit_price": "0.5"}, "symbol is required"),
            (_YES, {"limit_price": "0.5", "quantity": 0}, "greater than 0"),
            (_YES, {"limit_price": "0.5", "quantity": Decimal("1.005")}, "2 decimal"),
        ],
    )
    def test_invalid_raises_before_dispatch(
        self, contract: Any, kwargs: Dict[str, Any], message: str
    ) -> None:
        with pytest.raises(ValueError, match=message):
            self.client.buy_event_contract(contract, **kwargs)
        self.client.place_order.assert_not_called()

    def test_preflight(self) -> None:
        response = Mock(spec=PreflightResponse)
        self.client.perform_preflight_calculation = Mock(return_value=response)
        result = self.client.preflight_buy_event_contract(
            _contract(_NO, "NO", ask="0.172"), quantity=2, account_id="ACC456"
        )
        assert result is response
        request, account_id = self.client.perform_preflight_calculation.call_args[0]
        assert request.instrument.symbol == _NO
        assert request.instrument.type == InstrumentType.EVENTCONTRACT
        assert request.order_side == OrderSide.BUY
        assert request.order_type == OrderType.LIMIT
        assert request.limit_price == Decimal("0.18")
        assert request.quantity == Decimal("2")
        assert (
            request.model_dump(by_alias=True, exclude_none=True)["quantity"] == "2.00"
        )
        assert account_id == "ACC456"


class TestOrderQuantitySerialization:
    @pytest.mark.parametrize(
        "instrument_type, expected",
        [
            (InstrumentType.EVENTCONTRACT, "1.50"),
            (InstrumentType.EQUITY, "1.50000"),
            (InstrumentType.CRYPTO, "1.50000"),
        ],
    )
    def test_quantity_decimals_by_instrument(
        self, instrument_type: InstrumentType, expected: str
    ) -> None:
        common: Dict[str, Any] = {
            "instrument": {"symbol": "X", "type": instrument_type},
            "order_side": OrderSide.BUY,
            "order_type": OrderType.LIMIT,
            "limit_price": Decimal("0.5"),
            "quantity": Decimal("1.5"),
            "expiration": {"time_in_force": TimeInForce.DAY},
        }
        order = OrderRequest(order_id=_VALID_UUID, **common)
        preflight = PreflightRequest(**common)
        for request in (order, preflight):
            assert (
                request.model_dump(by_alias=True, exclude_none=True)["quantity"]
                == expected
            )


# ---------------------------------------------------------------------------
# wait_for_settlement
# ---------------------------------------------------------------------------


class TestWaitForSettlement:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_waits_until_settled(self) -> None:
        self.client.get_event_details = Mock(
            side_effect=[_details(_outcome(closes_in=-1)), _details(_SETTLED_YES)]
        )
        with patch("public_api_sdk.public_api_client.time.sleep") as sleep:
            outcome = self.client.wait_for_settlement(_EVENT, poll_interval=7)
        assert outcome == _SETTLED_YES
        assert outcome.won(_YES) is True
        sleep.assert_called_once_with(7)
        self.client.get_event_details.assert_called_with(_EVENT)

    def test_outcome_id_selects_outcome(self) -> None:
        settled = _outcome(
            outcome_id="B",
            state=EventOutcomeState.STATE_SETTLED,
            settled=EventSettledOutcome.SETTLED_OUTCOME_NO,
        )
        self.client.get_event_details = Mock(
            return_value=_details(_outcome(outcome_id="A"), settled)
        )
        assert self.client.wait_for_settlement(_EVENT, "B") == settled

    def test_multi_outcome_needs_outcome_id(self) -> None:
        self.client.get_event_details = Mock(
            return_value=_details(_outcome(outcome_id="A"), _outcome(outcome_id="B"))
        )
        with pytest.raises(ValueError, match="has 2 outcomes; pass outcome_id"):
            self.client.wait_for_settlement(_EVENT)

    def test_unknown_outcome_id(self) -> None:
        self.client.get_event_details = Mock(return_value=_details(_outcome()))
        with pytest.raises(ValueError, match="has no outcome 'X'"):
            self.client.wait_for_settlement(_EVENT, "X")

    def test_timeout(self) -> None:
        self.client.get_event_details = Mock(return_value=_details(_outcome(-1)))
        with pytest.raises(WaitTimeoutError, match="did not settle within 0s"):
            self.client.wait_for_settlement(_EVENT, timeout=0)


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class TestAsyncHelpers:
    def setup_method(self) -> None:
        self.client = _make_async_client()

    @pytest.mark.asyncio
    async def test_get_current_event(self) -> None:
        current = _summary(_EVENT, 8)
        self.client.get_event_summary = AsyncMock(
            side_effect=[
                _page(_summary("KALSHI.KXBTC15M-26OCT201145", -1), next_token="t2"),
                _page(current),
            ]
        )
        assert (
            await self.client.get_current_event(_SERIES, subcategory="BTC") == current
        )
        request = self.client.get_event_summary.call_args_list[0][0][0]
        assert request.subcategory == "BTC"
        assert request.filters.frequencies == [EventFrequency.FIFTEEN_MINUTES]

    @pytest.mark.asyncio
    async def test_wait_for_current_event(self) -> None:
        current = _summary(_EVENT, 14)
        self.client.get_current_event = AsyncMock(side_effect=[None, current])
        with patch(
            "public_api_sdk.async_public_api_client.asyncio.sleep", new=AsyncMock()
        ) as sleep:
            assert await self.client.wait_for_current_event(_SERIES) == current
        sleep.assert_awaited_once_with(30.0)

    @pytest.mark.asyncio
    async def test_wait_for_current_event_timeout(self) -> None:
        self.client.get_current_event = AsyncMock(return_value=None)
        with pytest.raises(WaitTimeoutError):
            await self.client.wait_for_current_event(_SERIES, timeout=0)

    @pytest.mark.asyncio
    async def test_buy_event_contract(self) -> None:
        order = Mock()
        self.client.place_order = AsyncMock(return_value=order)
        assert await self.client.buy_event_contract(_contract(_YES, "YES")) is order
        request, account_id = self.client.place_order.call_args[0]
        assert request.instrument.type == InstrumentType.EVENTCONTRACT
        assert request.limit_price == Decimal("0.84")
        assert account_id is None

    @pytest.mark.asyncio
    async def test_preflight_buy_event_contract(self) -> None:
        response = Mock(spec=PreflightResponse)
        self.client.perform_preflight_calculation = AsyncMock(return_value=response)
        result = await self.client.preflight_buy_event_contract(_YES, limit_price="0.5")
        assert result is response
        request, _ = self.client.perform_preflight_calculation.call_args[0]
        assert request.limit_price == Decimal("0.5")

    @pytest.mark.asyncio
    async def test_wait_for_settlement(self) -> None:
        self.client.get_event_details = AsyncMock(
            side_effect=[_details(_outcome(-1)), _details(_SETTLED_YES)]
        )
        with patch(
            "public_api_sdk.async_public_api_client.asyncio.sleep", new=AsyncMock()
        ) as sleep:
            outcome = await self.client.wait_for_settlement(_EVENT)
        assert outcome.winner is not None and outcome.winner.symbol == _YES
        sleep.assert_awaited_once_with(20.0)

    @pytest.mark.asyncio
    async def test_wait_for_settlement_timeout(self) -> None:
        self.client.get_event_details = AsyncMock(return_value=_details(_outcome(-1)))
        with pytest.raises(WaitTimeoutError):
            await self.client.wait_for_settlement(_EVENT, timeout=0)
