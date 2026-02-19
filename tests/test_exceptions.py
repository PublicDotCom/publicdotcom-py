"""Tests for exception classes and their hierarchy."""

import pytest

from public_api_sdk.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


class TestAPIError:
    def test_str_with_status_code(self) -> None:
        err = APIError("Something failed", status_code=500)
        assert str(err) == "API Error 500: Something failed"

    def test_str_without_status_code(self) -> None:
        err = APIError("Something failed")
        assert str(err) == "API Error: Something failed"

    def test_message_attribute(self) -> None:
        err = APIError("bad thing happened")
        assert err.message == "bad thing happened"

    def test_response_data_stored(self) -> None:
        err = APIError("err", status_code=400, response_data={"detail": "bad"})
        assert err.response_data == {"detail": "bad"}

    def test_response_data_defaults_to_empty_dict(self) -> None:
        err = APIError("err")
        assert err.response_data == {}

    def test_status_code_none_by_default(self) -> None:
        err = APIError("err")
        assert err.status_code is None

    def test_is_exception(self) -> None:
        assert issubclass(APIError, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(APIError) as exc_info:
            raise APIError("test", status_code=418)
        assert exc_info.value.status_code == 418


class TestAuthenticationError:
    def test_is_api_error(self) -> None:
        assert issubclass(AuthenticationError, APIError)

    def test_default_status_code(self) -> None:
        err = AuthenticationError()
        assert err.status_code == 401

    def test_default_message(self) -> None:
        err = AuthenticationError()
        assert err.message == "Authentication failed"

    def test_custom_message(self) -> None:
        err = AuthenticationError("Token expired")
        assert err.message == "Token expired"

    def test_catchable_as_api_error(self) -> None:
        with pytest.raises(APIError):
            raise AuthenticationError()


class TestValidationError:
    def test_is_api_error(self) -> None:
        assert issubclass(ValidationError, APIError)

    def test_default_status_code(self) -> None:
        err = ValidationError()
        assert err.status_code == 400

    def test_default_message(self) -> None:
        err = ValidationError()
        assert err.message == "Request validation failed"

    def test_custom_message_and_data(self) -> None:
        err = ValidationError("Invalid field", response_data={"field": "quantity"})
        assert err.message == "Invalid field"
        assert err.response_data == {"field": "quantity"}


class TestNotFoundError:
    def test_is_api_error(self) -> None:
        assert issubclass(NotFoundError, APIError)

    def test_default_status_code(self) -> None:
        err = NotFoundError()
        assert err.status_code == 404

    def test_default_message(self) -> None:
        err = NotFoundError()
        assert err.message == "Resource not found"


class TestRateLimitError:
    def test_is_api_error(self) -> None:
        assert issubclass(RateLimitError, APIError)

    def test_default_status_code(self) -> None:
        err = RateLimitError()
        assert err.status_code == 429

    def test_retry_after_stored(self) -> None:
        err = RateLimitError(retry_after=60)
        assert err.retry_after == 60

    def test_retry_after_none_by_default(self) -> None:
        err = RateLimitError()
        assert err.retry_after is None

    def test_custom_message(self) -> None:
        err = RateLimitError("Slow down", retry_after=30)
        assert err.message == "Slow down"
        assert err.retry_after == 30

    def test_catchable_as_api_error(self) -> None:
        with pytest.raises(APIError):
            raise RateLimitError(retry_after=5)


class TestServerError:
    def test_is_api_error(self) -> None:
        assert issubclass(ServerError, APIError)

    def test_default_status_code(self) -> None:
        err = ServerError()
        assert err.status_code == 500

    def test_default_message(self) -> None:
        err = ServerError()
        assert err.message == "Internal server error"

    def test_custom_status_code(self) -> None:
        err = ServerError("Service unavailable", status_code=503)
        assert err.status_code == 503

    def test_catchable_as_api_error(self) -> None:
        with pytest.raises(APIError):
            raise ServerError("boom")
