import json
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from requests.adapters import HTTPAdapter, BaseAdapter
from urllib3.util.retry import Retry

from .exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


class BlockHTTPAdapter(BaseAdapter):
    def send(self, request, **kwargs):
        raise RuntimeError("Insecure HTTP requests are not allowed. Use HTTPS endpoints only.")

    def close(self):
        pass


class ApiClient:
    """HTTP client with error handling and retry logic."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.3,
    ) -> None:
        """Initialize the base client.

        Args:
            base_url: Base URL for the API
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            backoff_factor: Backoff factor for retry delays
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

        # create session with retry strategy
        self.session = requests.Session()
        retry_strategy = Retry(
            total=max_retries,
            status_forcelist=[429, 500, 502, 503, 504],
            backoff_factor=backoff_factor,
            allowed_methods=["HEAD", "GET", "OPTIONS"],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        self.session.mount("http://", BlockHTTPAdapter())
        self.session.mount("https://", adapter)

        # default headers
        version = self._get_version()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "User-Agent": f"public-python-api-sdk-{version}",
                "X-App-Version": f"public-python-api-sdk-{version}",
            }
        )

    def _get_version(self) -> str:
        """Get the package version."""
        try:
            # Import here to avoid circular import during module initialization
            from . import __version__
            return __version__
        except (ImportError, AttributeError):
            # Fallback if version is not available
            return "0.1.0"

    def set_auth_header(self, token: str) -> None:
        """Set the `Authorization` header with a bearer token."""
        self.session.headers["Authorization"] = f"Bearer {token}"

    def remove_auth_header(self) -> None:
        """Remove the Authorization header."""
        self.session.headers.pop("Authorization", None)

    def _build_url(self, endpoint: str) -> str:
        """Build full URL from endpoint."""
        return urljoin(self.base_url + "/", endpoint.lstrip("/"))

    def _handle_response(self, response: requests.Response) -> Dict[str, Any]:
        """Handle HTTP response and raise appropriate exceptions."""
        try:
            response_data = response.json() if response.content else {}
        except json.JSONDecodeError:
            response_data = {"raw_content": response.text}

        if response.status_code == 200:
            return response_data

        # extract error message from response
        error_message = response_data.get("message", "Unknown error")
        if isinstance(error_message, dict):
            error_message = str(error_message)

        # raise specific exceptions based on status code
        if response.status_code == 401:
            raise AuthenticationError(
                error_message, response.status_code, response_data
            )
        elif response.status_code == 400:
            raise ValidationError(error_message, response.status_code, response_data)
        elif response.status_code == 404:
            raise NotFoundError(error_message, response.status_code, response_data)
        elif response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            retry_after_int = int(retry_after) if retry_after else None
            raise RateLimitError(
                error_message, response.status_code, retry_after_int, response_data
            )
        elif 500 <= response.status_code < 600:
            raise ServerError(error_message, response.status_code, response_data)
        else:
            raise APIError(error_message, response.status_code, response_data)

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        response = self.session.get(url, params=params, timeout=self.timeout, **kwargs)
        return self._handle_response(response)

    def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        response = self.session.post(
            url,
            data=data,
            json=json_data,
            timeout=self.timeout,
            **kwargs,
        )
        return self._handle_response(response)

    def put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        response = self.session.put(
            url,
            data=data,
            json=json_data,
            timeout=self.timeout,
            **kwargs,
        )
        return self._handle_response(response)

    def delete(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        response = self.session.delete(url, timeout=self.timeout, **kwargs)
        return self._handle_response(response)

    def close(self) -> None:
        self.session.close()
