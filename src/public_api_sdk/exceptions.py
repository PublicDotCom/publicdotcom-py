import json
from typing import Any, Dict, Optional

_ERROR_MESSAGE_KEYS = ("message", "error", "detail", "errors")
_MAX_ERROR_MESSAGE_LENGTH = 500


def _truncate(text: str) -> str:
    if len(text) <= _MAX_ERROR_MESSAGE_LENGTH:
        return text
    return text[:_MAX_ERROR_MESSAGE_LENGTH] + "…"


def extract_error_message(response_data: Dict[str, Any]) -> str:
    """Pick a human-readable message out of a parsed error response body.

    Tries the common error keys in order (``message``, ``error``, ``detail``,
    ``errors``), then the raw body of a non-JSON response, then the JSON body
    itself, so the gateway's actual error text ends up in ``str(exception)``.
    Long values are truncated. Returns ``"Unknown error"`` for an empty body.
    """
    for key in _ERROR_MESSAGE_KEYS:
        value = response_data.get(key)
        if value is not None and value != "" and value != [] and value != {}:
            return _truncate(value if isinstance(value, str) else str(value))
    raw_content = response_data.get("raw_content")
    if isinstance(raw_content, str) and raw_content.strip():
        return _truncate(raw_content.strip())
    if response_data:
        return _truncate(json.dumps(response_data, default=str))
    return "Unknown error"


class APIError(Exception):
    """Base exception for all Public API errors.

    All SDK exceptions inherit from this class, so catching ``APIError`` will
    catch every error raised by the SDK (except local ``ValueError`` raised by
    input validation before any network call is made).

    Attributes:
        message: Human-readable description of the error.
        status_code: HTTP status code returned by the API, or ``None`` for
            non-HTTP errors (e.g. network timeouts).
        response_data: Raw response body parsed as a dict, useful for
            extracting additional error detail provided by the API.
        error_code: Machine-readable error code from the API response body
            (the ``errorCode`` field), or ``None`` when absent.
    """

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.response_data = response_data or {}
        self.error_code: Optional[str] = self.response_data.get("errorCode")

    def __str__(self) -> str:
        if self.status_code:
            return f"API Error {self.status_code}: {self.message}"
        return f"API Error: {self.message}"


class AuthenticationError(APIError):
    """Raised when the API rejects the request due to invalid credentials.

    Typically corresponds to HTTP 401.  Common causes:

    - The API key or OAuth token is missing, expired, or has been revoked.
    - The token was not refreshed before the request was sent.

    The SDK refreshes tokens automatically before each request, so this error
    usually means the underlying credentials (API key / refresh token) are no
    longer valid and new credentials need to be generated.

    Example::

        from public_api_sdk.exceptions import AuthenticationError

        try:
            accounts = client.get_accounts()
        except AuthenticationError:
            # Re-generate or rotate your API key in the Public dashboard
            print("Invalid or expired credentials.")
    """

    def __init__(
        self,
        message: str = "Authentication failed",
        status_code: Optional[int] = 401,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)


class RateLimitError(APIError):
    """Raised when the API returns HTTP 429 (Too Many Requests).

    Attributes:
        retry_after: Number of seconds to wait before retrying, if provided
            by the API in the ``Retry-After`` response header.  May be
            ``None`` if the header was absent.

    Example::

        import time
        from public_api_sdk.exceptions import RateLimitError

        try:
            quotes = client.get_quotes(instruments)
        except RateLimitError as e:
            wait = e.retry_after or 5
            print(f"Rate limited — waiting {wait}s before retry")
            time.sleep(wait)
            quotes = client.get_quotes(instruments)
    """

    def __init__(
        self,
        message: str = "Rate limit exceeded",
        status_code: int = 429,
        retry_after: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)
        self.retry_after = retry_after


class ValidationError(APIError):
    """Raised when the API rejects the request due to invalid parameters (HTTP 400).

    This is the most common error when building orders or preflight requests.
    Common causes include:

    - Invalid or unsupported symbol.
    - Strike price or expiration date that does not exist in the option chain.
    - Order parameters that violate exchange or account rules (e.g. insufficient
      buying power, limit price outside allowed range).
    - Incorrect ``limit_price`` sign (e.g. positive price sent for a credit spread).
    - Quantity or price precision exceeds the allowed number of decimal places.

    The ``response_data`` attribute contains the full API response body and
    often includes a more specific error description from the exchange.

    Example::

        from public_api_sdk.exceptions import ValidationError

        try:
            result = client.strategy_preflight.credit_spread(...)
        except ValidationError as e:
            print(f"Bad request: {e.message}")
            print(f"Details: {e.response_data}")
    """

    def __init__(
        self,
        message: str = "Request validation failed",
        status_code: int = 400,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)


class NotFoundError(APIError):
    """Raised when the requested resource does not exist (HTTP 404).

    Common causes:

    - An ``order_id`` that does not belong to the account, or that has not yet
      been indexed after asynchronous placement.  Wait briefly and retry
      ``get_order()`` — the order may still be propagating.
    - An instrument symbol that is not supported for trading.
    - An account ID that does not exist or is not accessible with the current
      credentials.

    Example::

        from public_api_sdk.exceptions import NotFoundError

        try:
            order = client.get_order(order_id="abc-123")
        except NotFoundError:
            # Order placement is async — the order may not be indexed yet.
            # Retry after a short delay.
            print("Order not found yet; retrying...")
    """

    def __init__(
        self,
        message: str = "Resource not found",
        status_code: int = 404,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)


class ServerError(APIError):
    """Raised when the API returns an unexpected server-side error (HTTP 5xx).

    These errors are transient in most cases.  A brief wait followed by a
    single retry is usually sufficient.  If the error persists, check the
    Public API status page.

    Example::

        from public_api_sdk.exceptions import ServerError

        try:
            order = client.place_order(order_request)
        except ServerError:
            # Transient — wait and retry once
            import time
            time.sleep(2)
            order = client.place_order(order_request)
    """

    def __init__(
        self,
        message: str = "Internal server error",
        status_code: int = 500,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)
