"""Query-param serialization and error-message extraction, end to end.

Unlike most client tests, these keep the real ``ApiClient`` / ``AsyncApiClient``
and capture the outgoing request at the transport, so the URL the gateway would
actually receive is asserted. httpx calls ``str()`` on query values, which for a
``(str, Enum)`` member used to give ``"InstrumentType.CRYPTO"`` rather than
``"CRYPTO"``.
"""

from enum import Enum
from typing import Any, Iterator, List, Optional, Tuple
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import requests
from requests.adapters import BaseAdapter

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.api_client import ApiClient
from public_api_sdk.async_api_client import AsyncApiClient
from public_api_sdk.exceptions import (
    APIError,
    NotFoundError,
    ServerError,
    ValidationError,
)
from public_api_sdk.models.bond import (
    BondRating,
    BondSearchRequest,
    BondStatus,
    BondType,
    CouponFrequency,
    RatingCategory,
    SortDirection,
    SpCreditwatch,
    SpOutlook,
    TreasurySubtype,
)
from public_api_sdk.models.event_contract import EventFrequency, EventSortingMode
from public_api_sdk.models.instrument import InstrumentsRequest, TradingPermission
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.order import (
    EquityMarketSession,
    LegInstrumentType,
    OpenCloseIndicator,
    OrderClass,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
)

BASE_URL = "https://gateway.test"

INSTRUMENTS_REQUEST = InstrumentsRequest(
    type_filter=[InstrumentType.CRYPTO],
    trading_filter=[TradingPermission.BUY_AND_SELL],
)
BONDS_REQUEST = BondSearchRequest(
    sort_direction=SortDirection.ASC,
    bond_status=[BondStatus.LIQUIDATED],
    bond_type=[BondType.TREASURY],
)
INSTRUMENTS_BODY = {"instruments": []}
BONDS_BODY = {"content": [], "pageNumber": 0, "pageSize": 0, "totalElements": 0}


# ---------------------------------------------------------------------------
# Transports
# ---------------------------------------------------------------------------


class _CaptureAdapter(BaseAdapter):
    """requests adapter that records each request and replies with a fixed body."""

    def __init__(self, status: int = 200, body: bytes = b"{}") -> None:
        super().__init__()
        self.status = status
        self.body = body
        self.urls: List[str] = []

    def send(  # type: ignore[override]
        self, request: requests.PreparedRequest, **kwargs: Any
    ) -> requests.Response:
        self.urls.append(str(request.url))
        response = requests.Response()
        response.status_code = self.status
        response._content = self.body
        response.url = str(request.url)
        response.request = request
        return response

    def close(self) -> None:
        pass


def _sync_client(adapter: _CaptureAdapter) -> PublicApiClient:
    with patch("public_api_sdk.public_api_client.AuthManager"):
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=PublicApiClientConfiguration(
                default_account_number="ACC123", base_url=BASE_URL
            ),
        )
    client.api_client.session.mount("https://", adapter)
    return client


def _async_client(
    status: int = 200, body: Any = None
) -> Tuple[AsyncPublicApiClient, List[httpx.Request]]:
    captured: List[httpx.Request] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(request)
        return httpx.Response(status, json=body if body is not None else {})

    with patch("public_api_sdk.async_public_api_client.AsyncAuthManager"):
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=AsyncPublicApiClientConfiguration(
                default_account_number="ACC123", base_url=BASE_URL
            ),
            http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        )
    client.auth_manager.refresh_token_if_needed = AsyncMock()
    return client, captured


# ---------------------------------------------------------------------------
# Enum query params reach the gateway as their values
# ---------------------------------------------------------------------------


class TestAsyncQueryParams:
    @pytest.mark.asyncio
    async def test_get_all_instruments_sends_enum_values(self) -> None:
        client, captured = _async_client(body=INSTRUMENTS_BODY)
        await client.get_all_instruments(INSTRUMENTS_REQUEST)
        url = str(captured[0].url)
        assert "typeFilter=CRYPTO" in url
        assert "tradingFilter=BUY_AND_SELL" in url
        assert "InstrumentType" not in url
        assert "TradingPermission" not in url

    @pytest.mark.asyncio
    async def test_get_all_instruments_repeats_list_params(self) -> None:
        client, captured = _async_client(body=INSTRUMENTS_BODY)
        await client.get_all_instruments(
            InstrumentsRequest(
                type_filter=[InstrumentType.EQUITY, InstrumentType.CRYPTO]
            )
        )
        assert captured[0].url.params.get_list("typeFilter") == ["EQUITY", "CRYPTO"]

    @pytest.mark.asyncio
    async def test_get_all_instruments_without_filters_has_no_query(self) -> None:
        client, captured = _async_client(body=INSTRUMENTS_BODY)
        await client.get_all_instruments()
        assert captured[0].url.query == b""

    @pytest.mark.asyncio
    async def test_search_bonds_sends_enum_values(self) -> None:
        client, captured = _async_client(body=BONDS_BODY)
        await client.search_bonds(BONDS_REQUEST)
        params = captured[0].url.params
        assert params["sortDirection"] == "ASC"
        assert params.get_list("bondStatus") == ["LIQUIDATED"]
        assert params.get_list("bondType") == ["TREASURY"]


class TestSyncQueryParams:
    def test_get_all_instruments_sends_enum_values(self) -> None:
        adapter = _CaptureAdapter(body=b'{"instruments": []}')
        _sync_client(adapter).get_all_instruments(INSTRUMENTS_REQUEST)
        assert "typeFilter=CRYPTO" in adapter.urls[0]
        assert "tradingFilter=BUY_AND_SELL" in adapter.urls[0]

    def test_search_bonds_sends_enum_values(self) -> None:
        adapter = _CaptureAdapter(
            body=b'{"content": [], "pageNumber": 0, "pageSize": 0, "totalElements": 0}'
        )
        _sync_client(adapter).search_bonds(BONDS_REQUEST)
        url = adapter.urls[0]
        assert "sortDirection=ASC" in url
        assert "bondStatus=LIQUIDATED" in url
        assert "bondType=TREASURY" in url


# ---------------------------------------------------------------------------
# Request enums stringify to their values
# ---------------------------------------------------------------------------

REQUEST_ENUMS = [
    BondRating,
    BondStatus,
    BondType,
    CouponFrequency,
    RatingCategory,
    SortDirection,
    SpCreditwatch,
    SpOutlook,
    TreasurySubtype,
    EventFrequency,
    EventSortingMode,
    TradingPermission,
    InstrumentType,
    EquityMarketSession,
    LegInstrumentType,
    OpenCloseIndicator,
    OrderClass,
    OrderSide,
    OrderStatus,
    OrderType,
    TimeInForce,
]


def _members() -> Iterator[Enum]:
    for enum_cls in REQUEST_ENUMS:
        yield from enum_cls


class TestRequestEnumStr:
    @pytest.mark.parametrize("member", list(_members()), ids=repr)
    def test_str_and_format_give_value(self, member: Enum) -> None:
        assert str(member) == member.value
        assert f"{member}" == member.value
        assert "%s" % member == member.value

    def test_repr_unchanged(self) -> None:
        assert repr(InstrumentType.CRYPTO) == "<InstrumentType.CRYPTO: 'CRYPTO'>"

    def test_still_compares_equal_to_value(self) -> None:
        assert InstrumentType.CRYPTO == "CRYPTO"
        assert OrderType("LIMIT") is OrderType.LIMIT


# ---------------------------------------------------------------------------
# Error messages surface the gateway's error text
# ---------------------------------------------------------------------------

ERROR_CASES: List[Tuple[int, Optional[bytes], type, str]] = [
    (400, b'{"message": "bad filter"}', ValidationError, "bad filter"),
    (400, b'{"error": "Bad Request", "status": 400}', ValidationError, "Bad Request"),
    (404, b'{"detail": "no such account"}', NotFoundError, "no such account"),
    (
        400,
        b'{"errors": ["typeFilter: invalid value"]}',
        ValidationError,
        "['typeFilter: invalid value']",
    ),
    (400, b'{"code": "INVALID"}', ValidationError, '{"code": "INVALID"}'),
    (502, b"<html>Bad Gateway</html>", ServerError, "<html>Bad Gateway</html>"),
    (418, b"", APIError, "Unknown error"),
    (400, b'["first", "second"]', ValidationError, '["first", "second"]'),
]


class TestErrorMessages:
    @pytest.mark.parametrize("status,body,exc_cls,expected", ERROR_CASES)
    def test_sync(self, status: int, body: bytes, exc_cls: type, expected: str) -> None:
        response = requests.Response()
        response.status_code = status
        response._content = body
        with pytest.raises(exc_cls) as exc_info:
            ApiClient(base_url=BASE_URL)._handle_response(response)
        assert exc_info.value.message == expected
        assert expected in str(exc_info.value)

    @pytest.mark.parametrize("status,body,exc_cls,expected", ERROR_CASES)
    def test_async(
        self, status: int, body: bytes, exc_cls: type, expected: str
    ) -> None:
        response = httpx.Response(status, content=body)
        with pytest.raises(exc_cls) as exc_info:
            AsyncApiClient(base_url=BASE_URL)._handle_response(response)
        assert exc_info.value.message == expected
        assert expected in str(exc_info.value)

    def test_message_key_takes_precedence(self) -> None:
        response = httpx.Response(400, json={"error": "Bad Request", "message": "x"})
        with pytest.raises(ValidationError) as exc_info:
            AsyncApiClient(base_url=BASE_URL)._handle_response(response)
        assert exc_info.value.message == "x"

    def test_long_body_is_truncated(self) -> None:
        response = httpx.Response(500, content=b"x" * 5000)
        with pytest.raises(ServerError) as exc_info:
            AsyncApiClient(base_url=BASE_URL)._handle_response(response)
        assert len(exc_info.value.message) <= 501
        assert exc_info.value.message.endswith("…")

    def test_response_data_unchanged(self) -> None:
        response = httpx.Response(400, json={"error": "Bad Request", "status": 400})
        with pytest.raises(ValidationError) as exc_info:
            AsyncApiClient(base_url=BASE_URL)._handle_response(response)
        assert exc_info.value.response_data == {"error": "Bad Request", "status": 400}

    @pytest.mark.asyncio
    async def test_end_to_end_gateway_error_visible(self) -> None:
        client, _ = _async_client(status=400, body={"error": "Bad Request"})
        with pytest.raises(ValidationError, match="Bad Request"):
            await client.get_all_instruments(INSTRUMENTS_REQUEST)
