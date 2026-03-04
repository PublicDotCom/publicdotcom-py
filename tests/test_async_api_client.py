"""Tests for AsyncApiClient — the httpx-based async HTTP layer."""

import json
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

import httpx
import pytest

from public_api_sdk.async_api_client import AsyncApiClient
from public_api_sdk.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_httpx_response(
    status_code: int,
    data: object = None,
    headers: Optional[dict] = None,
    empty_body: bool = False,
) -> Mock:
    """Build a mock httpx.Response."""
    response = Mock(spec=httpx.Response)
    response.status_code = status_code
    response.content = b"" if empty_body else b'{"key": "val"}'
    response.json.return_value = data if data is not None else {}
    response.headers = headers or {}
    response.text = ""
    return response


def _make_client() -> AsyncApiClient:
    return AsyncApiClient(base_url="https://api.example.com")


# ---------------------------------------------------------------------------
# Initialisation
# ---------------------------------------------------------------------------


class TestAsyncApiClientInit:
    def test_base_url_trailing_slash_stripped(self) -> None:
        client = AsyncApiClient(base_url="https://api.example.com/")
        assert client.base_url == "https://api.example.com"

    def test_base_url_stored(self) -> None:
        client = AsyncApiClient(base_url="https://api.example.com")
        assert client.base_url == "https://api.example.com"

    def test_default_headers_set(self) -> None:
        client = AsyncApiClient(base_url="https://api.example.com")
        headers = dict(client._client.headers)
        assert headers.get("content-type") == "application/json"
        assert "user-agent" in headers
        assert "x-app-version" in headers

    def test_user_agent_contains_sdk_name(self) -> None:
        client = AsyncApiClient(base_url="https://api.example.com")
        headers = dict(client._client.headers)
        assert "public-python-api-sdk" in headers.get("user-agent", "")


# ---------------------------------------------------------------------------
# Auth header management
# ---------------------------------------------------------------------------


class TestAsyncApiClientAuthHeaders:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_set_auth_header(self) -> None:
        self.client.set_auth_header("my_token")
        assert self.client._auth_header == "Bearer my_token"

    def test_set_auth_header_overwrites_previous(self) -> None:
        self.client.set_auth_header("token_1")
        self.client.set_auth_header("token_2")
        assert self.client._auth_header == "Bearer token_2"

    def test_remove_auth_header(self) -> None:
        self.client.set_auth_header("my_token")
        self.client.remove_auth_header()
        assert self.client._auth_header is None

    def test_remove_auth_header_when_not_set(self) -> None:
        self.client.remove_auth_header()  # should not raise
        assert self.client._auth_header is None

    def test_get_request_headers_with_auth(self) -> None:
        self.client.set_auth_header("tok")
        hdrs = self.client._get_request_headers()
        assert hdrs == {"Authorization": "Bearer tok"}

    def test_get_request_headers_without_auth(self) -> None:
        hdrs = self.client._get_request_headers()
        assert hdrs == {}


# ---------------------------------------------------------------------------
# URL building and HTTPS enforcement
# ---------------------------------------------------------------------------


class TestAsyncApiClientUrlBuilding:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_build_url_with_leading_slash(self) -> None:
        url = self.client._build_url("/endpoint")
        assert url == "https://api.example.com/endpoint"

    def test_build_url_without_leading_slash(self) -> None:
        url = self.client._build_url("endpoint")
        assert url == "https://api.example.com/endpoint"

    def test_build_url_nested_path(self) -> None:
        url = self.client._build_url("/foo/bar/baz")
        assert url == "https://api.example.com/foo/bar/baz"

    def test_http_url_raises_runtime_error(self) -> None:
        client = AsyncApiClient(base_url="http://insecure.example.com")
        with pytest.raises(RuntimeError, match="Insecure HTTP"):
            client._build_url("/endpoint")


# ---------------------------------------------------------------------------
# _handle_response
# ---------------------------------------------------------------------------


class TestAsyncApiClientHandleResponse:
    def setup_method(self) -> None:
        self.client = _make_client()

    def test_200_returns_data(self) -> None:
        response = _make_httpx_response(200, data={"key": "value"})
        result = self.client._handle_response(response)
        assert result == {"key": "value"}

    def test_200_empty_body_returns_empty_dict(self) -> None:
        response = _make_httpx_response(200, empty_body=True)
        result = self.client._handle_response(response)
        assert result == {}

    def test_401_raises_authentication_error(self) -> None:
        response = _make_httpx_response(401, data={"message": "Unauthorized"})
        with pytest.raises(AuthenticationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 401
        assert exc_info.value.message == "Unauthorized"

    def test_400_raises_validation_error(self) -> None:
        response = _make_httpx_response(400, data={"message": "Bad request"})
        with pytest.raises(ValidationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 400

    def test_404_raises_not_found_error(self) -> None:
        response = _make_httpx_response(404, data={"message": "Not found"})
        with pytest.raises(NotFoundError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 404

    def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        response = _make_httpx_response(
            429,
            data={"message": "Too many requests"},
            headers={"Retry-After": "30"},
        )
        with pytest.raises(RateLimitError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.retry_after == 30

    def test_429_without_retry_after_header(self) -> None:
        response = _make_httpx_response(
            429, data={"message": "Rate limited"}, headers={}
        )
        with pytest.raises(RateLimitError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.retry_after is None

    def test_500_raises_server_error(self) -> None:
        response = _make_httpx_response(500, data={"message": "Internal error"})
        with pytest.raises(ServerError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 500

    def test_503_raises_server_error(self) -> None:
        response = _make_httpx_response(503, data={"message": "Unavailable"})
        with pytest.raises(ServerError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 503

    def test_unknown_4xx_raises_api_error(self) -> None:
        response = _make_httpx_response(418, data={"message": "I'm a teapot"})
        with pytest.raises(APIError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 418

    def test_missing_message_field_uses_default(self) -> None:
        response = _make_httpx_response(400, data={"code": "INVALID"})
        with pytest.raises(ValidationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.message == "Unknown error"

    def test_dict_message_is_stringified(self) -> None:
        response = _make_httpx_response(400, data={"message": {"nested": "err"}})
        with pytest.raises(ValidationError) as exc_info:
            self.client._handle_response(response)
        assert isinstance(exc_info.value.message, str)

    def test_error_response_data_stored_on_exception(self) -> None:
        body = {"message": "Not found", "detail": "ORDER-1"}
        response = _make_httpx_response(404, data=body)
        with pytest.raises(NotFoundError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.response_data == body

    def test_invalid_json_falls_back_to_raw_content(self) -> None:
        response = Mock(spec=httpx.Response)
        response.status_code = 400
        response.content = b"not json"
        response.json.side_effect = json.JSONDecodeError("", "", 0)
        response.text = "not json"
        response.headers = {}
        with pytest.raises(ValidationError):
            self.client._handle_response(response)


# ---------------------------------------------------------------------------
# HTTP methods (mock httpx transport)
# ---------------------------------------------------------------------------


class TestAsyncApiClientHttpMethods:
    def setup_method(self) -> None:
        self.client = _make_client()
        self.ok_response = _make_httpx_response(200, data={"result": "ok"})

    @pytest.mark.asyncio
    async def test_get_returns_data(self) -> None:
        self.client._client.request = AsyncMock(return_value=self.ok_response)
        result = await self.client.get("/endpoint")
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_get_builds_correct_url(self) -> None:
        self.client._client.request = AsyncMock(return_value=self.ok_response)
        await self.client.get("/trading/account")
        call_args = self.client._client.request.call_args
        assert "https://api.example.com/trading/account" in call_args[0]

    @pytest.mark.asyncio
    async def test_get_passes_params(self) -> None:
        self.client._client.request = AsyncMock(return_value=self.ok_response)
        await self.client.get("/endpoint", params={"foo": "bar"})
        call_kwargs = self.client._client.request.call_args[1]
        assert call_kwargs["params"] == {"foo": "bar"}

    @pytest.mark.asyncio
    async def test_get_includes_auth_header(self) -> None:
        self.client.set_auth_header("test_token")
        self.client._client.request = AsyncMock(return_value=self.ok_response)
        await self.client.get("/endpoint")
        call_kwargs = self.client._client.request.call_args[1]
        assert call_kwargs["headers"].get("Authorization") == "Bearer test_token"

    @pytest.mark.asyncio
    async def test_post_returns_data(self) -> None:
        self.client._client.request = AsyncMock(return_value=self.ok_response)
        result = await self.client.post("/endpoint", json_data={"key": "val"})
        assert result == {"result": "ok"}

    @pytest.mark.asyncio
    async def test_post_passes_json_data(self) -> None:
        self.client._client.request = AsyncMock(return_value=self.ok_response)
        payload = {"instruments": [{"symbol": "AAPL"}]}
        await self.client.post("/quotes", json_data=payload)
        call_kwargs = self.client._client.request.call_args[1]
        assert call_kwargs["json"] == payload

    @pytest.mark.asyncio
    async def test_delete_returns_data(self) -> None:
        delete_response = _make_httpx_response(200, data={})
        self.client._client.request = AsyncMock(return_value=delete_response)
        result = await self.client.delete("/endpoint")
        assert result == {}

    @pytest.mark.asyncio
    async def test_delete_builds_correct_url(self) -> None:
        delete_response = _make_httpx_response(200, data={})
        self.client._client.request = AsyncMock(return_value=delete_response)
        await self.client.delete("/trading/ACC123/order/ORDER-456")
        call_args = self.client._client.request.call_args
        assert "ORDER-456" in call_args[0][1]  # 2nd positional arg is URL

    @pytest.mark.asyncio
    async def test_get_raises_on_api_error(self) -> None:
        self.client._client.request = AsyncMock(
            return_value=_make_httpx_response(401, data={"message": "Unauthorized"})
        )
        with pytest.raises(AuthenticationError):
            await self.client.get("/protected")

    @pytest.mark.asyncio
    async def test_post_raises_on_validation_error(self) -> None:
        self.client._client.request = AsyncMock(
            return_value=_make_httpx_response(400, data={"message": "Invalid"})
        )
        with pytest.raises(ValidationError):
            await self.client.post("/endpoint", json_data={})


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestAsyncApiClientRetry:
    def setup_method(self) -> None:
        self.client = AsyncApiClient(
            base_url="https://api.example.com",
            max_retries=2,
            backoff_factor=0.01,  # fast backoff for tests
        )

    @pytest.mark.asyncio
    async def test_get_retries_on_500_and_eventually_succeeds(self) -> None:
        fail = _make_httpx_response(500, data={"message": "error"})
        success = _make_httpx_response(200, data={"ok": True})
        self.client._client.request = AsyncMock(side_effect=[fail, success])
        result = await self.client.get("/endpoint")
        assert result == {"ok": True}
        assert self.client._client.request.call_count == 2

    @pytest.mark.asyncio
    async def test_get_raises_after_max_retries_exhausted(self) -> None:
        fail = _make_httpx_response(500, data={"message": "error"})
        self.client._client.request = AsyncMock(side_effect=[fail, fail, fail])
        with pytest.raises(ServerError):
            await self.client.get("/endpoint")

    @pytest.mark.asyncio
    async def test_post_retries_on_500(self) -> None:
        """POST should now retry on 5xx responses (all methods retry on transient errors)."""
        fail = _make_httpx_response(500, data={"message": "error"})
        self.client._client.request = AsyncMock(return_value=fail)
        with pytest.raises(ServerError):
            await self.client.post("/endpoint", json_data={})
        # max_retries=2 in setup_method → 3 total attempts
        assert self.client._client.request.call_count == 3

    @pytest.mark.asyncio
    async def test_transport_error_retried_for_get(self) -> None:
        success = _make_httpx_response(200, data={"ok": True})
        self.client._client.request = AsyncMock(
            side_effect=[httpx.ConnectError("refused"), success]
        )
        result = await self.client.get("/endpoint")
        assert result == {"ok": True}

    @pytest.mark.asyncio
    async def test_transport_error_raises_after_max_retries(self) -> None:
        self.client._client.request = AsyncMock(
            side_effect=httpx.ConnectError("refused")
        )
        with pytest.raises(APIError):
            await self.client.get("/endpoint")


# ---------------------------------------------------------------------------
# Close
# ---------------------------------------------------------------------------


class TestAsyncApiClientClose:
    @pytest.mark.asyncio
    async def test_aclose_closes_httpx_client(self) -> None:
        client = _make_client()
        client._client.aclose = AsyncMock()
        await client.aclose()
        client._client.aclose.assert_called_once()
