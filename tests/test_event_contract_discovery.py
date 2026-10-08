"""Tests for the 2026-10-08 spec revision: event-contract discovery.

- ``get_event_categories`` (GET /eventcontract/summary/categories);
- ``get_event_summary`` (POST /eventcontract/summary) with
  ``EventSummaryRequest`` / ``EventSummaryFilters`` and ``next_token``
  pagination;
- ``get_event_details`` (GET /eventcontract/details/{eventSymbol}) with the
  ``includeAllOutcomes`` query parameter;
- the response models and their tolerant enums.

Client tests patch ApiClient/AsyncApiClient and the auth managers at
construction time so no real HTTP calls are made, mirroring the other client
test modules.
"""

import json
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest
from pydantic import ValidationError as PydanticValidationError

import public_api_sdk
from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.api_client import ApiClient
from public_api_sdk.exceptions import ValidationError
from public_api_sdk.models import (
    CftcContract,
    EventCategoriesResponse,
    EventContract,
    EventContractSide,
    EventDetails,
    EventExchange,
    EventFrequency,
    EventOutcomeState,
    EventSettledOutcome,
    EventSortingMode,
    EventSummary,
    EventSummaryFilters,
    EventSummaryPage,
    EventSummaryRequest,
    EventTradingMode,
)

_EVENT = "KALSHI.KXBALANCESHEET-EO26"
_OUTCOME = "KALSHI.KXBALANCESHEET-EO26-6.6"
_YES = "KALSHI.KXBALANCESHEET-EO26-6.6.Y"
_NO = "KALSHI.KXBALANCESHEET-EO26-6.6.N"
_SUMMARY_URL = "/userapigateway/eventcontract/summary"
_CATEGORIES_URL = "/userapigateway/eventcontract/summary/categories"
_DETAILS_URL = f"/userapigateway/eventcontract/details/{_EVENT}"


def _make_client() -> PublicApiClient:
    """Return a PublicApiClient with ApiClient and AuthManager patched out."""
    with (
        patch("public_api_sdk.public_api_client.ApiClient"),
        patch("public_api_sdk.public_api_client.AuthManager"),
    ):
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=PublicApiClientConfiguration(default_account_number="ACC123"),
        )
    return client


def _make_async_client() -> AsyncPublicApiClient:
    """Return AsyncPublicApiClient with AsyncApiClient and AsyncAuthManager patched."""
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


# ---------------------------------------------------------------------------
# Payload builders (shapes taken from the spec's EventCategoryListDto /
# EventSummaryUserApiListDto / EventUserApiDto)
# ---------------------------------------------------------------------------


def _categories_payload() -> Dict[str, Any]:
    return {
        "categories": [
            {
                "category": "Economics",
                "subcategories": ["Fed", "Inflation"],
                "eventFrequency": {
                    "show": True,
                    "frequencies": ["ALL", "ONE_MONTH", "ONE_YEAR"],
                },
            },
            {
                "category": "Politics",
                "subcategories": [],
                "eventFrequency": {"show": False, "frequencies": ["ALL"]},
            },
        ]
    }


def _summary_payload(
    *event_symbols: str, next_token: Optional[str] = None
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "content": [
            {
                "title": "Size of Fed balance sheet at end of 2026",
                "eventSymbol": symbol,
                "volume": "125000",
                "resolutionTime": "2026-12-31T23:59:00Z",
                "resolved": False,
                "halted": False,
                "category": "Economics",
                "subcategories": ["Fed"],
                "symbols": [f"{symbol}-6.6.Y", f"{symbol}-6.6.N"],
            }
            for symbol in event_symbols
        ]
    }
    if next_token is not None:
        payload["nextToken"] = next_token
    return payload


def _contract_payload(symbol: str, side: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "symbol": symbol,
        "predictedOutcome": side,
        "bid": "0.41",
        "ask": "0.43",
        "last": "0.42",
        "openInterest": "1500",
        "dailyGainValue": "0.02",
        "dailyGainPercentage": "5.0",
        "probability": "0.42",
    }
    payload.update(overrides)
    return payload


def _details_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "eventSymbol": _EVENT,
        "exchange": "KALSHI",
        "resolved": False,
        "halted": False,
        "title": "Size of Fed balance sheet at end of 2026",
        "category": "Economics",
        "volume": "125000",
        "subcategories": ["Fed"],
        "cftcContract": {
            "contractTermsUrl": "https://example.com/terms.pdf",
            "prohibitions": ["Employees of the Federal Reserve"],
            "resolutionSources": [
                {"name": "Federal Reserve H.4.1", "url": "https://example.com/h41"}
            ],
        },
        "outcomeCount": 12,
        "outcomes": [
            {
                "outcomeId": _OUTCOME,
                "title": "ABOVE $6.6 TRILLION",
                "rules": "Resolves YES if the balance sheet is above $6.6T.",
                "volume": "40000",
                "state": "STATE_OPEN",
                "timeline": {
                    "openTime": "2026-01-01T00:00:00Z",
                    "closeTime": "2026-12-31T23:59:00Z",
                    "expectedExpirationTime": "2027-01-02T15:00:00Z",
                    "latestExpirationTime": "2027-01-09T15:00:00Z",
                    "settlementTime": "2027-01-02T16:00:00Z",
                    "settlementDelaySeconds": 3600,
                },
                "settledOutcome": "SETTLED_OUTCOME_UNSPECIFIED",
                "trading": "BUY_AND_SELL",
                "contracts": [
                    _contract_payload(_YES, "YES"),
                    _contract_payload(
                        _NO,
                        "NO",
                        bid="0.57",
                        ask="0.59",
                        last="0.58",
                        probability="0.58",
                    ),
                ],
            }
        ],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Exports / version
# ---------------------------------------------------------------------------


class TestExports:
    @pytest.mark.parametrize(
        "name",
        [
            "CftcContract",
            "EventCategoriesResponse",
            "EventCategory",
            "EventCategoryFrequencies",
            "EventContract",
            "EventContractSide",
            "EventDetails",
            "EventExchange",
            "EventFrequency",
            "EventOutcome",
            "EventOutcomeState",
            "EventSettledOutcome",
            "EventSortingMode",
            "EventSummary",
            "EventSummaryFilters",
            "EventSummaryPage",
            "EventSummaryRequest",
            "EventTimeline",
            "EventTradingMode",
            "ResolutionSource",
        ],
    )
    def test_exported_from_package_and_models(self, name: str) -> None:
        assert name in public_api_sdk.__all__
        assert getattr(public_api_sdk, name) is getattr(public_api_sdk.models, name)
        assert name in public_api_sdk.models.__all__

    def test_version_bumped(self) -> None:
        assert public_api_sdk.__version__ == "0.1.26"


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------


class TestEventSummaryRequest:
    def test_default_body_is_volume_sort_only(self) -> None:
        body = EventSummaryRequest().model_dump(by_alias=True, exclude_none=True)
        assert body == {"sortingMode": "VOLUME"}

    def test_full_body_uses_camel_case_aliases(self) -> None:
        request = EventSummaryRequest(
            sorting_mode=EventSortingMode.RECENTLY_ADDED,
            category="Economics",
            subcategory="Fed",
            next_token="tok-2",
            display_resolved_events=True,
            created_within_days=7,
            filters=EventSummaryFilters(
                event_symbols=[_EVENT],
                frequencies=[EventFrequency.ONE_MONTH, EventFrequency.ONE_YEAR],
                resolution_time_start=datetime(2026, 10, 1, tzinfo=timezone.utc),
                resolution_time_end=datetime(2026, 12, 31, 23, 59, tzinfo=timezone.utc),
            ),
        )
        body = request.model_dump(by_alias=True, exclude_none=True)
        assert body == {
            "sortingMode": "RECENTLY_ADDED",
            "category": "Economics",
            "subcategory": "Fed",
            "nextToken": "tok-2",
            "displayResolvedEvents": True,
            "createdWithinDays": 7,
            "filters": {
                "eventSymbols": [_EVENT],
                "frequencies": ["ONE_MONTH", "ONE_YEAR"],
                "resolutionTimeStart": "2026-10-01T00:00:00+00:00",
                "resolutionTimeEnd": "2026-12-31T23:59:00+00:00",
            },
        }
        # The body must be JSON-serialisable as sent by the HTTP client.
        json.dumps(body)

    def test_accepts_camel_case_input(self) -> None:
        request = EventSummaryRequest(
            sortingMode="EXPIRATION",
            nextToken="abc",
            displayResolvedEvents=False,
            createdWithinDays=3,
        )
        assert request.sorting_mode is EventSortingMode.EXPIRATION
        assert request.next_token == "abc"
        assert request.display_resolved_events is False
        assert request.created_within_days == 3

    def test_invalid_sorting_mode_rejected(self) -> None:
        with pytest.raises(PydanticValidationError):
            EventSummaryRequest(sorting_mode="ALPHABETICAL")

    def test_filters_require_both_lists(self) -> None:
        with pytest.raises(PydanticValidationError):
            EventSummaryFilters(event_symbols=[_EVENT])  # type: ignore[call-arg]
        with pytest.raises(PydanticValidationError):
            EventSummaryFilters(frequencies=[EventFrequency.ALL])  # type: ignore[call-arg]

    def test_filters_reject_unknown_frequency(self) -> None:
        with pytest.raises(PydanticValidationError, match="client-side fallback"):
            EventSummaryFilters(event_symbols=[], frequencies=[EventFrequency.UNKNOWN])

    def test_filters_omit_unset_resolution_times(self) -> None:
        body = EventSummaryFilters(
            event_symbols=[], frequencies=[EventFrequency.ALL]
        ).model_dump(by_alias=True, exclude_none=True)
        assert body == {"eventSymbols": [], "frequencies": ["ALL"]}


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class TestResponseModels:
    def test_categories_parse(self) -> None:
        response = EventCategoriesResponse(**_categories_payload())
        economics, politics = response.categories
        assert economics.category == "Economics"
        assert economics.subcategories == ["Fed", "Inflation"]
        assert economics.event_frequency is not None
        assert economics.event_frequency.show is True
        assert economics.event_frequency.frequencies == [
            EventFrequency.ALL,
            EventFrequency.ONE_MONTH,
            EventFrequency.ONE_YEAR,
        ]
        assert politics.event_frequency is not None
        assert politics.event_frequency.show is False

    def test_empty_categories(self) -> None:
        assert EventCategoriesResponse(**{}).categories == []

    def test_summary_page_parse(self) -> None:
        page = EventSummaryPage(**_summary_payload(_EVENT, next_token="tok-2"))
        assert page.next_token == "tok-2"
        (event,) = page.content
        assert isinstance(event, EventSummary)
        assert event.event_symbol == _EVENT
        assert event.volume == Decimal("125000")
        assert event.resolution_time == datetime(
            2026, 12, 31, 23, 59, tzinfo=timezone.utc
        )
        assert event.resolved is False
        assert event.halted is False
        assert event.category == "Economics"
        assert event.subcategories == ["Fed"]
        assert event.symbols == [f"{_EVENT}-6.6.Y", f"{_EVENT}-6.6.N"]

    def test_summary_last_page_has_no_token(self) -> None:
        page = EventSummaryPage(**_summary_payload(_EVENT))
        assert page.next_token is None

    def test_summary_requires_event_symbol_not_event_id(self) -> None:
        # The field was renamed eventId → eventSymbol before release.
        with pytest.raises(PydanticValidationError):
            EventSummary(**{"eventId": _EVENT, "title": "x"})

    def test_summary_tolerates_missing_optional_fields(self) -> None:
        event = EventSummary(**{"eventSymbol": _EVENT})
        assert event.title is None
        assert event.volume is None
        assert event.subcategories == []
        assert event.symbols == []

    def test_details_parse(self) -> None:
        details = EventDetails(**_details_payload())
        assert details.event_symbol == _EVENT
        assert details.exchange is EventExchange.KALSHI
        assert details.volume == Decimal("125000")
        assert details.outcome_count == 12
        assert isinstance(details.cftc_contract, CftcContract)
        assert (
            details.cftc_contract.contract_terms_url == "https://example.com/terms.pdf"
        )
        assert details.cftc_contract.prohibitions == [
            "Employees of the Federal Reserve"
        ]
        (source,) = details.cftc_contract.resolution_sources
        assert source.name == "Federal Reserve H.4.1"
        assert source.url == "https://example.com/h41"

        (outcome,) = details.outcomes
        assert outcome.outcome_id == _OUTCOME
        assert outcome.title == "ABOVE $6.6 TRILLION"
        assert outcome.volume == Decimal("40000")
        assert outcome.state is EventOutcomeState.STATE_OPEN
        assert (
            outcome.settled_outcome is EventSettledOutcome.SETTLED_OUTCOME_UNSPECIFIED
        )
        assert outcome.trading is EventTradingMode.BUY_AND_SELL
        assert outcome.timeline is not None
        assert outcome.timeline.open_time == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert outcome.timeline.close_time == datetime(
            2026, 12, 31, 23, 59, tzinfo=timezone.utc
        )
        assert outcome.timeline.expected_expiration_time is not None
        assert outcome.timeline.latest_expiration_time is not None
        assert outcome.timeline.settlement_time is not None
        assert outcome.timeline.settlement_delay_seconds == 3600

        yes, no = outcome.contracts
        assert isinstance(yes, EventContract)
        assert yes.symbol == _YES
        assert yes.predicted_outcome is EventContractSide.YES
        assert yes.bid == Decimal("0.41")
        assert yes.ask == Decimal("0.43")
        assert yes.last == Decimal("0.42")
        assert yes.open_interest == Decimal("1500")
        assert yes.daily_gain_value == Decimal("0.02")
        assert yes.daily_gain_percentage == Decimal("5.0")
        assert yes.probability == Decimal("0.42")
        assert no.predicted_outcome is EventContractSide.NO
        assert no.probability == Decimal("0.58")

    def test_details_contract_without_prices(self) -> None:
        contract = EventContract(**{"symbol": _YES, "predictedOutcome": "YES"})
        assert contract.bid is None
        assert contract.ask is None
        assert contract.last is None
        assert contract.probability is None

    def test_details_settled_outcome(self) -> None:
        payload = _details_payload(resolved=True)
        payload["outcomes"][0].update(
            state="STATE_SETTLED",
            settledOutcome="SETTLED_OUTCOME_YES",
            trading="DISABLED",
        )
        details = EventDetails(**payload)
        assert details.resolved is True
        outcome = details.outcomes[0]
        assert outcome.state is EventOutcomeState.STATE_SETTLED
        assert outcome.settled_outcome is EventSettledOutcome.SETTLED_OUTCOME_YES
        assert outcome.trading is EventTradingMode.DISABLED

    def test_unknown_enum_values_fall_back(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        payload = _details_payload(exchange="NEWEXCHANGE")
        payload["outcomes"][0].update(
            state="STATE_PAUSED",
            settledOutcome="SETTLED_OUTCOME_VOID",
            trading="CLOSE_ONLY",
        )
        payload["outcomes"][0]["contracts"][0]["predictedOutcome"] = "MAYBE"
        with caplog.at_level("WARNING"):
            details = EventDetails(**payload)
        assert details.exchange is EventExchange.UNKNOWN
        outcome = details.outcomes[0]
        assert outcome.state is EventOutcomeState.UNKNOWN
        assert outcome.settled_outcome is EventSettledOutcome.UNKNOWN
        assert outcome.trading is EventTradingMode.UNKNOWN
        assert outcome.contracts[0].predicted_outcome is EventContractSide.UNKNOWN
        assert "Unrecognised EventExchange 'NEWEXCHANGE'" in caplog.text

    def test_unknown_category_frequency_falls_back(self) -> None:
        payload = _categories_payload()
        payload["categories"][0]["eventFrequency"]["frequencies"] = ["FIVE_MINUTES"]
        response = EventCategoriesResponse(**payload)
        assert response.categories[0].event_frequency is not None
        assert response.categories[0].event_frequency.frequencies == [
            EventFrequency.UNKNOWN
        ]

    def test_details_round_trip_by_alias(self) -> None:
        details = EventDetails(**_details_payload())
        dumped = details.model_dump(by_alias=True, mode="json")
        assert dumped["eventSymbol"] == _EVENT
        assert dumped["outcomeCount"] == 12
        assert (
            dumped["cftcContract"]["contractTermsUrl"]
            == "https://example.com/terms.pdf"
        )
        assert dumped["outcomes"][0]["outcomeId"] == _OUTCOME
        assert dumped["outcomes"][0]["contracts"][0]["predictedOutcome"] == "YES"
        assert EventDetails(**dumped) == details


# ---------------------------------------------------------------------------
# Sync client
# ---------------------------------------------------------------------------


class TestGetEventCategories:
    def test_get_categories(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_categories_payload())
        response = client.get_event_categories()
        client.api_client.get.assert_called_once_with(_CATEGORIES_URL)
        client.auth_manager.refresh_token_if_needed.assert_called_once()
        assert [c.category for c in response.categories] == ["Economics", "Politics"]


class TestGetEventSummary:
    def test_default_request(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value=_summary_payload(_EVENT))
        page = client.get_event_summary()
        assert client.api_client.post.call_args[0][0] == _SUMMARY_URL
        assert client.api_client.post.call_args.kwargs["json_data"] == {
            "sortingMode": "VOLUME"
        }
        client.auth_manager.refresh_token_if_needed.assert_called_once()
        assert page.content[0].event_symbol == _EVENT

    def test_does_not_use_account_id(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value=_summary_payload())
        client.get_event_summary(EventSummaryRequest(category="Economics"))
        url = client.api_client.post.call_args[0][0]
        assert "ACC123" not in url
        assert client.api_client.post.call_args.kwargs["json_data"] == {
            "sortingMode": "VOLUME",
            "category": "Economics",
        }

    def test_pagination_with_next_token(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(
            side_effect=[
                _summary_payload("EV1", "EV2", next_token="tok-2"),
                _summary_payload("EV3", next_token="tok-3"),
                _summary_payload("EV4"),
            ]
        )
        request = EventSummaryRequest(sorting_mode=EventSortingMode.EXPIRATION)
        page = client.get_event_summary(request)
        symbols = [event.event_symbol for event in page.content]
        while page.next_token:
            request.next_token = page.next_token
            page = client.get_event_summary(request)
            symbols.extend(event.event_symbol for event in page.content)
        assert symbols == ["EV1", "EV2", "EV3", "EV4"]
        bodies = [c.kwargs["json_data"] for c in client.api_client.post.call_args_list]
        assert [b.get("nextToken") for b in bodies] == [None, "tok-2", "tok-3"]
        assert all(b["sortingMode"] == "EXPIRATION" for b in bodies)

    def test_empty_response(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(return_value={})
        page = client.get_event_summary()
        assert page.content == []
        assert page.next_token is None

    def test_bad_request_propagates(self) -> None:
        client = _make_client()
        client.api_client.post = Mock(
            side_effect=ValidationError("sortingMode must not be null", 400, {})
        )
        with pytest.raises(ValidationError):
            client.get_event_summary()


class TestGetEventDetails:
    def test_default_includes_all_outcomes(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_details_payload())
        details = client.get_event_details(_EVENT)
        client.api_client.get.assert_called_once_with(
            _DETAILS_URL, params={"includeAllOutcomes": "true"}
        )
        client.auth_manager.refresh_token_if_needed.assert_called_once()
        assert details.event_symbol == _EVENT

    def test_short_outcome_list(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_details_payload())
        client.get_event_details(_EVENT, include_all_outcomes=False)
        assert client.api_client.get.call_args.kwargs["params"] == {
            "includeAllOutcomes": "false"
        }

    def test_symbol_is_stripped(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_details_payload())
        client.get_event_details(f"  {_EVENT} ")
        assert client.api_client.get.call_args[0][0] == _DETAILS_URL

    @pytest.mark.parametrize("symbol", ["", "   "])
    def test_empty_symbol_raises_before_request(self, symbol: str) -> None:
        client = _make_client()
        client.api_client.get = Mock()
        with pytest.raises(ValueError, match="event_symbol is required"):
            client.get_event_details(symbol)
        client.api_client.get.assert_not_called()

    def test_unknown_event_raises_validation_error_with_code(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(
            side_effect=ValidationError(
                "Event not found",
                400,
                {"errorCode": "7004", "message": "Event not found"},
            )
        )
        with pytest.raises(ValidationError) as exc_info:
            client.get_event_details("KALSHI.NOPE")
        assert exc_info.value.status_code == 400
        assert exc_info.value.error_code == "7004"


class TestHttpErrorMapping:
    """A 400 from the details endpoint reaches callers as ValidationError."""

    def test_400_maps_to_validation_error(self) -> None:
        body = {"errorCode": "7004", "message": "No event found"}
        response = Mock()
        response.status_code = 400
        response.content = json.dumps(body).encode()
        response.json = Mock(return_value=body)
        api_client = ApiClient.__new__(ApiClient)
        with pytest.raises(ValidationError) as exc_info:
            api_client._handle_response(response)
        assert exc_info.value.error_code == "7004"
        assert exc_info.value.message == "No event found"


# ---------------------------------------------------------------------------
# Async client
# ---------------------------------------------------------------------------


class TestAsyncEventContractDiscovery:
    @pytest.mark.asyncio
    async def test_get_categories(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_categories_payload())
        response = await client.get_event_categories()
        client.api_client.get.assert_awaited_once_with(_CATEGORIES_URL)
        client.auth_manager.refresh_token_if_needed.assert_awaited_once()
        assert len(response.categories) == 2

    @pytest.mark.asyncio
    async def test_get_summary(self) -> None:
        client = _make_async_client()
        client.api_client.post = AsyncMock(
            return_value=_summary_payload(_EVENT, next_token="tok-2")
        )
        page = await client.get_event_summary(
            EventSummaryRequest(
                filters=EventSummaryFilters(
                    event_symbols=[_EVENT], frequencies=[EventFrequency.ALL]
                )
            )
        )
        assert client.api_client.post.call_args[0][0] == _SUMMARY_URL
        assert client.api_client.post.call_args.kwargs["json_data"] == {
            "sortingMode": "VOLUME",
            "filters": {"eventSymbols": [_EVENT], "frequencies": ["ALL"]},
        }
        client.auth_manager.refresh_token_if_needed.assert_awaited_once()
        assert page.next_token == "tok-2"
        assert page.content[0].event_symbol == _EVENT

    @pytest.mark.asyncio
    async def test_get_summary_default_request(self) -> None:
        client = _make_async_client()
        client.api_client.post = AsyncMock(return_value=_summary_payload())
        await client.get_event_summary()
        assert client.api_client.post.call_args.kwargs["json_data"] == {
            "sortingMode": "VOLUME"
        }

    @pytest.mark.asyncio
    async def test_get_details(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_details_payload())
        details = await client.get_event_details(_EVENT, include_all_outcomes=False)
        client.api_client.get.assert_awaited_once_with(
            _DETAILS_URL, params={"includeAllOutcomes": "false"}
        )
        client.auth_manager.refresh_token_if_needed.assert_awaited_once()
        assert details.outcomes[0].contracts[0].symbol == _YES

    @pytest.mark.asyncio
    async def test_get_details_empty_symbol(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock()
        with pytest.raises(ValueError, match="event_symbol is required"):
            await client.get_event_details("")
        client.api_client.get.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_get_details_unknown_event(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(
            side_effect=ValidationError("Event not found", 400, {"errorCode": "7004"})
        )
        with pytest.raises(ValidationError) as exc_info:
            await client.get_event_details("KALSHI.NOPE")
        assert exc_info.value.error_code == "7004"
