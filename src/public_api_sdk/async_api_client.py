"""Async HTTP client for the Public.com API using httpx."""

import asyncio
import json
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import httpx

from .exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

_RETRY_STATUS_CODES = {429, 500, 502, 503, 504}


class AsyncApiClient:
    """Async HTTP client with error handling and retry logic."""

    def __init__(
        self,
        base_url: str,
        timeout: int = 30,
        max_retries: int = 3,
        backoff_factor: float = 0.3,
    ) -> None:
        """Initialize the async HTTP client.

        Args:
            base_url: Base URL for the API (must be HTTPS)
            timeout: Request timeout in seconds
            max_retries: Maximum number of retries for failed requests
            backoff_factor: Backoff factor for retry delays
        """
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._max_retries = max_retries
        self._backoff_factor = backoff_factor
        self._auth_header: Optional[str] = None

        version = self._get_version()
        self._client = httpx.AsyncClient(
            headers={
                "Content-Type": "application/json",
                "User-Agent": f"public-python-api-sdk-{version}",
                "X-App-Version": f"public-python-api-sdk-{version}",
            },
            timeout=float(timeout),
        )

    def _get_version(self) -> str:
        try:
            from . import __version__

            return __version__
        except (ImportError, AttributeError):
            return "0.1.0"

    def set_auth_header(self, token: str) -> None:
        """Set the Authorization header with a bearer token."""
        self._auth_header = f"Bearer {token}"

    def remove_auth_header(self) -> None:
        """Remove the Authorization header."""
        self._auth_header = None

    def _build_url(self, endpoint: str) -> str:
        url = urljoin(self.base_url + "/", endpoint.lstrip("/"))
        if not url.startswith("https://"):
            raise RuntimeError(
                "Insecure HTTP requests are not allowed. Use HTTPS endpoints only."
            )
        return url

    def _get_request_headers(self) -> Dict[str, str]:
        if self._auth_header:
            return {"Authorization": self._auth_header}
        return {}

    def _handle_response(self, response: httpx.Response) -> Dict[str, Any]:
        """Handle HTTP response and raise appropriate exceptions."""
        try:
            response_data: Dict[str, Any] = response.json() if response.content else {}
        except json.JSONDecodeError:
            response_data = {"raw_content": response.text}

        if response.status_code == 200:
            return response_data

        error_message = response_data.get("message", "Unknown error")
        if isinstance(error_message, dict):
            error_message = str(error_message)

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

    async def _request_with_retry(
        self,
        method: str,
        url: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Execute an HTTP request with retry logic."""
        retries = 0
        while True:
            try:
                response = await self._client.request(method, url, **kwargs)
            except httpx.TransportError as exc:
                if retries >= self._max_retries:
                    raise APIError(str(exc), 0, {}) from exc
                retries += 1
                await asyncio.sleep(self._backoff_factor * (2 ** (retries - 1)))
                continue

            should_retry_status = (
                response.status_code in _RETRY_STATUS_CODES
                and retries < self._max_retries
            )
            if should_retry_status:
                retries += 1
                await asyncio.sleep(self._backoff_factor * (2 ** (retries - 1)))
                continue

            return self._handle_response(response)

    async def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        return await self._request_with_retry(
            "GET", url, params=params, headers=self._get_request_headers(), **kwargs
        )

    async def post(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        return await self._request_with_retry(
            "POST",
            url,
            data=data,
            json=json_data,
            headers=self._get_request_headers(),
            **kwargs,
        )

    async def put(
        self,
        endpoint: str,
        data: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        return await self._request_with_retry(
            "PUT",
            url,
            data=data,
            json=json_data,
            headers=self._get_request_headers(),
            **kwargs,
        )

    async def delete(
        self,
        endpoint: str,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        url = self._build_url(endpoint)
        return await self._request_with_retry(
            "DELETE", url, headers=self._get_request_headers(), **kwargs
        )

    async def aclose(self) -> None:
        """Close the underlying HTTP client and release connections."""
        await self._client.aclose()
