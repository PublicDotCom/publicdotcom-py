"""Tests for the ApiClient HTTP layer."""

import json
from typing import Optional
from unittest.mock import Mock

import pytest
import requests

from public_api_sdk.api_client import ApiClient, BlockHTTPAdapter
from public_api_sdk.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


def _make_response(
    status_code: int,
    data: object = None,
    headers: Optional[dict] = None,
    empty_body: bool = False,
) -> Mock:
    """Build a mock requests.Response."""
    response = Mock(spec=requests.Response)
    response.status_code = status_code
    response.content = b"" if empty_body else b'{"key": "val"}'
    response.json.return_value = data if data is not None else {}
    response.headers = headers or {}
    response.text = ""
    return response


class TestApiClientInit:
    def test_base_url_trailing_slash_stripped(self) -> None:
        client = ApiClient(base_url="https://api.example.com/")
        assert client.base_url == "https://api.example.com"

    def test_base_url_stored(self) -> None:
        client = ApiClient(base_url="https://api.example.com")
        assert client.base_url == "https://api.example.com"

    def test_default_headers_set(self) -> None:
        client = ApiClient(base_url="https://api.example.com")
        assert client.session.headers["Content-Type"] == "application/json"
        assert "User-Agent" in client.session.headers
        assert "X-App-Version" in client.session.headers

    def test_user_agent_contains_sdk_name(self) -> None:
        client = ApiClient(base_url="https://api.example.com")
        assert "public-python-api-sdk" in client.session.headers["User-Agent"]

    def test_http_adapter_is_blocking(self) -> None:
        client = ApiClient(base_url="https://api.example.com")
        adapter = client.session.get_adapter("http://example.com")
        assert isinstance(adapter, BlockHTTPAdapter)

    def test_http_requests_are_blocked(self) -> None:
        client = ApiClient(base_url="https://api.example.com")
        with pytest.raises(RuntimeError, match="Insecure HTTP"):
            client.session.get("http://insecure.example.com/endpoint", timeout=1)


class TestApiClientAuthHeaders:
    def setup_method(self) -> None:
        self.client = ApiClient(base_url="https://api.example.com")

    def test_set_auth_header(self) -> None:
        self.client.set_auth_header("my_token")
        assert self.client.session.headers["Authorization"] == "Bearer my_token"

    def test_set_auth_header_overwrites_previous(self) -> None:
        self.client.set_auth_header("token_1")
        self.client.set_auth_header("token_2")
        assert self.client.session.headers["Authorization"] == "Bearer token_2"

    def test_remove_auth_header(self) -> None:
        self.client.set_auth_header("my_token")
        self.client.remove_auth_header()
        assert "Authorization" not in self.client.session.headers

    def test_remove_auth_header_when_not_set(self) -> None:
        # should not raise
        self.client.remove_auth_header()
        assert "Authorization" not in self.client.session.headers


class TestApiClientUrlBuilding:
    def setup_method(self) -> None:
        self.client = ApiClient(base_url="https://api.example.com")

    def test_build_url_with_leading_slash(self) -> None:
        url = self.client._build_url("/endpoint")
        assert url == "https://api.example.com/endpoint"

    def test_build_url_without_leading_slash(self) -> None:
        url = self.client._build_url("endpoint")
        assert url == "https://api.example.com/endpoint"

    def test_build_url_nested_path(self) -> None:
        url = self.client._build_url("/foo/bar/baz")
        assert url == "https://api.example.com/foo/bar/baz"

    def test_build_url_with_path_segments(self) -> None:
        url = self.client._build_url("/trading/ACC123/order/ORDER-456")
        assert url == "https://api.example.com/trading/ACC123/order/ORDER-456"


class TestApiClientHandleResponse:
    def setup_method(self) -> None:
        self.client = ApiClient(base_url="https://api.example.com")

    def test_200_returns_data(self) -> None:
        response = _make_response(200, data={"key": "value"})
        result = self.client._handle_response(response)
        assert result == {"key": "value"}

    def test_200_empty_body_returns_empty_dict(self) -> None:
        response = _make_response(200, empty_body=True)
        result = self.client._handle_response(response)
        assert result == {}

    def test_401_raises_authentication_error(self) -> None:
        response = _make_response(401, data={"message": "Unauthorized"})
        with pytest.raises(AuthenticationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 401
        assert exc_info.value.message == "Unauthorized"

    def test_400_raises_validation_error(self) -> None:
        response = _make_response(400, data={"message": "Bad request body"})
        with pytest.raises(ValidationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 400
        assert exc_info.value.message == "Bad request body"

    def test_404_raises_not_found_error(self) -> None:
        response = _make_response(404, data={"message": "Order not found"})
        with pytest.raises(NotFoundError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 404

    def test_429_raises_rate_limit_error_with_retry_after(self) -> None:
        response = _make_response(
            429,
            data={"message": "Too many requests"},
            headers={"Retry-After": "30"},
        )
        with pytest.raises(RateLimitError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 429
        assert exc_info.value.retry_after == 30

    def test_429_without_retry_after_header(self) -> None:
        response = _make_response(429, data={"message": "Rate limited"}, headers={})
        with pytest.raises(RateLimitError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.retry_after is None

    def test_500_raises_server_error(self) -> None:
        response = _make_response(500, data={"message": "Internal server error"})
        with pytest.raises(ServerError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 500

    def test_503_raises_server_error(self) -> None:
        response = _make_response(503, data={"message": "Service unavailable"})
        with pytest.raises(ServerError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 503

    def test_unknown_4xx_raises_api_error(self) -> None:
        response = _make_response(418, data={"message": "I'm a teapot"})
        with pytest.raises(APIError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.status_code == 418

    def test_error_response_data_stored_on_exception(self) -> None:
        body = {"message": "Not found", "detail": "Order ORDER-1 not found"}
        response = _make_response(404, data=body)
        with pytest.raises(NotFoundError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.response_data == body

    def test_missing_message_field_uses_default(self) -> None:
        response = _make_response(400, data={"code": "INVALID"})
        with pytest.raises(ValidationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.message == "Unknown error"

    def test_dict_message_field_is_stringified(self) -> None:
        response = _make_response(400, data={"message": {"nested": "error"}})
        with pytest.raises(ValidationError) as exc_info:
            self.client._handle_response(response)
        assert exc_info.value.message is not None
        assert isinstance(exc_info.value.message, str)

    def test_invalid_json_falls_back_to_raw_content(self) -> None:
        response = Mock(spec=requests.Response)
        response.status_code = 400
        response.content = b"not valid json"
        response.json.side_effect = json.JSONDecodeError("No JSON", "", 0)
        response.text = "not valid json"
        response.headers = {}
        with pytest.raises(ValidationError):
            self.client._handle_response(response)


class TestApiClientHttpMethods:
    def setup_method(self) -> None:
        self.client = ApiClient(base_url="https://api.example.com")
        self.ok_response = _make_response(200, data={"result": "ok"})

    def test_get_calls_session_get(self) -> None:
        self.client.session.get = Mock(return_value=self.ok_response)
        result = self.client.get("/endpoint")
        self.client.session.get.assert_called_once()
        assert result == {"result": "ok"}

    def test_get_builds_correct_url(self) -> None:
        self.client.session.get = Mock(return_value=self.ok_response)
        self.client.get("/trading/account")
        call_args = self.client.session.get.call_args
        assert "https://api.example.com/trading/account" in call_args[0]

    def test_get_passes_params(self) -> None:
        self.client.session.get = Mock(return_value=self.ok_response)
        self.client.get("/endpoint", params={"foo": "bar", "page": 2})
        call_kwargs = self.client.session.get.call_args[1]
        assert call_kwargs["params"] == {"foo": "bar", "page": 2}

    def test_get_passes_timeout(self) -> None:
        self.client.session.get = Mock(return_value=self.ok_response)
        self.client.get("/endpoint")
        call_kwargs = self.client.session.get.call_args[1]
        assert "timeout" in call_kwargs

    def test_post_calls_session_post(self) -> None:
        self.client.session.post = Mock(return_value=self.ok_response)
        result = self.client.post("/endpoint", json_data={"key": "val"})
        self.client.session.post.assert_called_once()
        assert result == {"result": "ok"}

    def test_post_passes_json_data(self) -> None:
        self.client.session.post = Mock(return_value=self.ok_response)
        payload = {"instruments": [{"symbol": "AAPL", "type": "EQUITY"}]}
        self.client.post("/quotes", json_data=payload)
        call_kwargs = self.client.session.post.call_args[1]
        assert call_kwargs["json"] == payload

    def test_delete_calls_session_delete(self) -> None:
        delete_response = _make_response(200, data={})
        self.client.session.delete = Mock(return_value=delete_response)
        self.client.delete("/endpoint")
        self.client.session.delete.assert_called_once()

    def test_delete_builds_correct_url(self) -> None:
        delete_response = _make_response(200, data={})
        self.client.session.delete = Mock(return_value=delete_response)
        self.client.delete("/trading/ACC123/order/ORDER-456")
        call_args = self.client.session.delete.call_args
        assert "ORDER-456" in call_args[0][0]

    def test_close_closes_session(self) -> None:
        self.client.session.close = Mock()
        self.client.close()
        self.client.session.close.assert_called_once()

    def test_get_raises_on_api_error(self) -> None:
        self.client.session.get = Mock(
            return_value=_make_response(401, data={"message": "Unauthorized"})
        )
        with pytest.raises(AuthenticationError):
            self.client.get("/protected/endpoint")

    def test_post_raises_on_validation_error(self) -> None:
        self.client.session.post = Mock(
            return_value=_make_response(400, data={"message": "Invalid body"})
        )
        with pytest.raises(ValidationError):
            self.client.post("/endpoint", json_data={"bad": "data"})
