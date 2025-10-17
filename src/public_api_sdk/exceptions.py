from typing import Any, Dict, Optional


class APIError(Exception):
    """Base exception for API errors"""

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

    def __str__(self) -> str:
        if self.status_code:
            return f"API Error {self.status_code}: {self.message}"
        return f"API Error: {self.message}"


class AuthenticationError(APIError):
    """Raised when authentication fails."""

    def __init__(
        self,
        message: str = "Authentication failed",
        status_code: Optional[int] = 401,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)


class RateLimitError(APIError):
    """Raised when rate limit is exceeded."""

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
    """Raised when request validation fails."""

    def __init__(
        self,
        message: str = "Request validation failed",
        status_code: int = 400,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)


class NotFoundError(APIError):
    """Raised when a resource is not found."""

    def __init__(
        self,
        message: str = "Resource not found",
        status_code: int = 404,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)


class ServerError(APIError):
    """Raised when server returns a 5xx error."""

    def __init__(
        self,
        message: str = "Internal server error",
        status_code: int = 500,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message, status_code, response_data)
