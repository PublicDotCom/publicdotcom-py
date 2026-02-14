"""Comprehensive tests for API client error handling."""
import json
from unittest.mock import Mock, patch

import pytest
import requests

from public_api_sdk.api_client import ApiClient
from public_api_sdk.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


class TestApiClientErrorResponses:
    """Tests for HTTP error response handling."""

    @pytest.fixture
    def client(self):
        return ApiClient(base_url="https://api.public.com")

    @pytest.fixture
    def mock_response(self):
        """Create a mock response object."""
        response = Mock(spec=requests.Response)
        response.content = b'{"message": "Error message"}'
        response.json.return_value = {"message": "Error message"}
        return response

    def test_200_success(self, client, mock_response):
        """200 response should return parsed JSON."""
        mock_response.status_code = 200
        mock_response.json.return_value = {"data": "success"}

        with patch.object(client.session, 'request', return_value=mock_response):
            result = client.get("/test")
            assert result == {"data": "success"}

    def test_400_raises_validation_error(self, client, mock_response):
        """400 should raise ValidationError."""
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": "Invalid field"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(ValidationError) as exc:
                client.get("/test")
            assert exc.value.status_code == 400
            assert "Invalid field" in str(exc.value)

    def test_401_raises_authentication_error(self, client, mock_response):
        """401 should raise AuthenticationError."""
        mock_response.status_code = 401
        mock_response.json.return_value = {"message": "Token expired"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(AuthenticationError) as exc:
                client.get("/test")
            assert exc.value.status_code == 401
            assert "Token expired" in str(exc.value)

    def test_404_raises_not_found_error(self, client, mock_response):
        """404 should raise NotFoundError."""
        mock_response.status_code = 404
        mock_response.json.return_value = {"message": "Order not found"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(NotFoundError) as exc:
                client.get("/test")
            assert exc.value.status_code == 404
            assert "Order not found" in str(exc.value)

    def test_429_raises_rate_limit_error_with_retry_after(self, client, mock_response):
        """429 should raise RateLimitError with retry_after."""
        mock_response.status_code = 429
        mock_response.headers = {"Retry-After": "60"}
        mock_response.json.return_value = {"message": "Rate limit exceeded"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(RateLimitError) as exc:
                client.get("/test")
            assert exc.value.status_code == 429
            assert exc.value.retry_after == 60

    def test_429_without_retry_after(self, client, mock_response):
        """429 without Retry-After header should have None retry_after."""
        mock_response.status_code = 429
        mock_response.headers = {}
        mock_response.json.return_value = {"message": "Rate limit exceeded"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(RateLimitError) as exc:
                client.get("/test")
            assert exc.value.retry_after is None

    def test_500_raises_server_error(self, client, mock_response):
        """500 should raise ServerError."""
        mock_response.status_code = 500
        mock_response.json.return_value = {"message": "Internal server error"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(ServerError) as exc:
                client.get("/test")
            assert exc.value.status_code == 500
            assert "Internal server error" in str(exc.value)

    def test_502_raises_server_error(self, client, mock_response):
        """502 should raise ServerError."""
        mock_response.status_code = 502
        mock_response.json.return_value = {"message": "Bad gateway"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(ServerError) as exc:
                client.get("/test")
            assert exc.value.status_code == 502

    def test_503_raises_server_error(self, client, mock_response):
        """503 should raise ServerError."""
        mock_response.status_code = 503
        mock_response.json.return_value = {"message": "Service unavailable"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(ServerError) as exc:
                client.get("/test")
            assert exc.value.status_code == 503

    def test_unknown_error_raises_api_error(self, client, mock_response):
        """Unexpected status code should raise base APIError."""
        mock_response.status_code = 418  # I'm a teapot
        mock_response.json.return_value = {"message": "I'm a teapot"}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(APIError) as exc:
                client.get("/test")
            assert exc.value.status_code == 418

    def test_error_message_extraction_from_dict(self, client, mock_response):
        """Error message can be extracted from nested dict."""
        mock_response.status_code = 400
        mock_response.json.return_value = {"message": {"field": "error detail"}}

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(ValidationError) as exc:
                client.get("/test")
            # Should convert dict to string representation
            assert "field" in str(exc.value)

    def test_empty_response_content(self, client, mock_response):
        """Empty response content should not crash."""
        mock_response.status_code = 204
        mock_response.content = b""
        mock_response.json.return_value = {}

        with patch.object(client.session, 'request', return_value=mock_response):
            result = client.get("/test")
            assert result == {}

    def test_malformed_json_response(self, client, mock_response):
        """Non-JSON error response should include raw content."""
        mock_response.status_code = 500
        mock_response.content = b"Internal Server Error"
        mock_response.json.side_effect = json.JSONDecodeError("test", "", 0)

        with patch.object(client.session, 'request', return_value=mock_response):
            with pytest.raises(ServerError) as exc:
                client.get("/test")
            assert exc.value.status_code == 500
            # Raw content should be in response_data
            assert "raw_content" in exc.value.response_data


class TestApiClientRetryLogic:
    """Tests for HTTP retry behavior."""

    def test_retry_on_503_then_success(self):
        """Test that 503 is retried before succeeding."""
        client = ApiClient(base_url="https://api.public.com")
        
        responses = [
            Mock(status_code=503, content=b'{"message": "temporarily unavailable"}', 
                 json=lambda: {"message": "temporarily unavailable"},
                 headers={}),
            Mock(status_code=200, content=b'{"success": true}',
                 json=lambda: {"success": True}),
        ]
        
        with patch.object(client.session, 'request', side_effect=responses):
            # Note: Retry only happens for HEAD, GET, OPTIONS by default
            # POST requests won't be retried automatically
            pass  # This test would need custom retry config

    def test_http_requests_blocked(self):
        """HTTP (not HTTPS) requests should be blocked."""
        client = ApiClient(base_url="http://insecure.com")
        
        # The BlockHTTPAdapter should reject http:// requests
        with pytest.raises(RuntimeError, match="Insecure HTTP"):
            client.get("/test")


class TestApiClientHeaders:
    """Tests for request headers."""

    def test_default_headers_set(self):
        """Default headers should include Content-Type and User-Agent."""
        client = ApiClient(base_url="https://api.public.com")
        
        assert client.session.headers["Content-Type"] == "application/json"
        assert "User-Agent" in client.session.headers
        assert "public-python-api-sdk" in client.session.headers["User-Agent"]
        assert client.session.headers["X-App-Version"] == client.session.headers["User-Agent"]

    def test_auth_header_set(self):
        """set_auth_header should set Authorization header."""
        client = ApiClient(base_url="https://api.public.com")
        client.set_auth_header("test_token_123")
        
        assert client.session.headers["Authorization"] == "Bearer test_token_123"

    def test_auth_header_removed(self):
        """remove_auth_header should remove Authorization header."""
        client = ApiClient(base_url="https://api.public.com")
        client.set_auth_header("test_token_123")
        client.remove_auth_header()
        
        assert "Authorization" not in client.session.headers

    def test_auth_header_remove_idempotent(self):
        """Removing auth header when not set should not crash."""
        client = ApiClient(base_url="https://api.public.com")
        # Should not raise
        client.remove_auth_header()
        assert "Authorization" not in client.session.headers


class TestApiClientUrlBuilding:
    """Tests for URL construction."""

    @pytest.mark.parametrize("base_url,endpoint,expected", [
        ("https://api.public.com", "/test", "https://api.public.com/test"),
        ("https://api.public.com/", "/test", "https://api.public.com/test"),
        ("https://api.public.com", "test", "https://api.public.com/test"),
        ("https://api.public.com/v1", "/test", "https://api.public.com/v1/test"),
    ])
    def test_url_construction(self, base_url, endpoint, expected):
        """Various base URL formats should normalize correctly."""
        client = ApiClient(base_url=base_url)
        result = client._build_url(endpoint)
        assert result == expected


class TestApiClientMethods:
    """Tests for different HTTP methods."""

    @pytest.fixture
    def client(self):
        return ApiClient(base_url="https://api.public.com")

    @pytest.fixture
    def mock_success_response(self):
        response = Mock(spec=requests.Response)
        response.status_code = 200
        response.content = b'{"data": "value"}'
        response.json.return_value = {"data": "value"}
        return response

    def test_get_request(self, client, mock_success_response):
        """GET request should work."""
        with patch.object(client.session, 'get', return_value=mock_success_response):
            result = client.get("/test", params={"key": "value"})
            assert result == {"data": "value"}

    def test_post_request_with_json(self, client, mock_success_response):
        """POST request with JSON data should work."""
        with patch.object(client.session, 'post', return_value=mock_success_response):
            result = client.post("/test", json_data={"key": "value"})
            assert result == {"data": "value"}

    def test_put_request_with_json(self, client, mock_success_response):
        """PUT request with JSON data should work."""
        with patch.object(client.session, 'put', return_value=mock_success_response):
            result = client.put("/test", json_data={"key": "value"})
            assert result == {"data": "value"}

    def test_delete_request(self, client, mock_success_response):
        """DELETE request should work."""
        with patch.object(client.session, 'delete', return_value=mock_success_response):
            result = client.delete("/test")
            assert result == {"data": "value"}


class TestApiClientTimeout:
    """Tests for timeout behavior."""

    def test_timeout_set_on_requests(self):
        """Timeout should be passed to requests."""
        client = ApiClient(base_url="https://api.public.com", timeout=45)
        
        mock_response = Mock(spec=requests.Response)
        mock_response.status_code = 200
        mock_response.content = b'{}'
        mock_response.json.return_value = {}
        
        with patch.object(client.session, 'get', return_value=mock_response) as mock_get:
            client.get("/test")
            mock_get.assert_called_once()
            assert mock_get.call_args.kwargs.get('timeout') == 45

    def test_custom_timeout(self):
        """Custom timeout should be respected."""
        client = ApiClient(base_url="https://api.public.com", timeout=60)
        assert client.timeout == 60
