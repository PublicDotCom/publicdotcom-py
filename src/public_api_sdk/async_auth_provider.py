"""Async authentication providers and manager for the Public.com API."""

import base64
import hashlib
import secrets
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from urllib.parse import urlencode

from .async_api_client import AsyncApiClient
from .models.auth import OAuthTokenResponse


class AsyncAuthProvider(ABC):
    """Abstract base class for async authentication providers."""

    def __init__(self, api_client: AsyncApiClient) -> None:
        self.api_client = api_client

    @abstractmethod
    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""

    @abstractmethod
    async def refresh_if_needed(self) -> None:
        """Refresh the access token if it is expired or about to expire."""

    @abstractmethod
    async def revoke_token(self) -> None:
        """Revoke the current access token and clear it from memory."""


class AsyncApiKeyAuthProvider(AsyncAuthProvider):
    """Async authentication provider for first-party API key authentication."""

    def __init__(
        self,
        api_client: AsyncApiClient,
        api_secret_key: str,
        validity_minutes: int = 15,
    ) -> None:
        """Initialize the async API key auth provider.

        Args:
            api_client: Async HTTP client for making requests
            api_secret_key: API secret key
            validity_minutes: Token validity in minutes (5–1440)
        """
        super().__init__(api_client)

        if not 5 <= validity_minutes <= 1440:
            raise ValueError("Validity must be between 5 and 1440 minutes")

        self._secret = api_secret_key
        self._validity_minutes = validity_minutes
        self._access_token: Optional[str] = None
        self._access_token_expires_at: Optional[float] = None

    async def get_access_token(self) -> str:
        """Get a valid access token, creating one if necessary."""
        if not self._is_token_valid():
            await self._create_personal_access_token()
        return self._access_token or ""

    async def refresh_if_needed(self) -> None:
        """Create a new token if the current one is missing or about to expire."""
        if not self._is_token_valid():
            await self._create_personal_access_token()

    async def revoke_token(self) -> None:
        """Clear the stored token and remove the Authorization header."""
        self._access_token = None
        self._access_token_expires_at = None
        self.api_client.remove_auth_header()

    def _is_token_valid(self) -> bool:
        if not self._access_token or not self._access_token_expires_at:
            return False
        return time.time() < self._access_token_expires_at

    async def _create_personal_access_token(self) -> None:
        response = await self.api_client.post(
            "/userapiauthservice/personal/access-tokens",
            json_data={
                "secret": self._secret,
                "validityInMinutes": self._validity_minutes,
            },
        )
        self._access_token = response.get("accessToken")
        if self._access_token:
            # subtract 5-minute safety buffer before declaring token valid
            expires_in_seconds = (self._validity_minutes - 5) * 60
            self._access_token_expires_at = time.time() + expires_in_seconds
            self.api_client.set_auth_header(self._access_token)


class AsyncOAuthAuthProvider(AsyncAuthProvider):
    """Async authentication provider for OAuth2 authentication."""

    def __init__(
        self,
        api_client: AsyncApiClient,
        client_id: str,
        redirect_uri: str,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        use_pkce: bool = True,
        authorization_base_url: str = "/userapiauthservice/oauth2/authorize",
        token_url: str = "/userapiauthservice/oauth2/token",
    ) -> None:
        """Initialize the async OAuth auth provider.

        Args:
            api_client: Async HTTP client for making requests
            client_id: OAuth client ID
            redirect_uri: Redirect URI for the OAuth callback
            client_secret: OAuth client secret (optional for public clients)
            scope: Space-separated list of scopes
            use_pkce: Whether to use PKCE (recommended)
            authorization_base_url: Authorization endpoint path
            token_url: Token exchange endpoint path
        """
        super().__init__(api_client)

        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.use_pkce = use_pkce
        self.authorization_base_url = authorization_base_url
        self.token_url = token_url

        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_token_expires_at: Optional[float] = None

        self._code_verifier: Optional[str] = None
        self._code_challenge: Optional[str] = None
        self._state: Optional[str] = None

    def get_authorization_url(self, base_url: str) -> Tuple[str, str]:
        """Generate the OAuth authorization URL (no I/O required).

        Args:
            base_url: Base URL of the API

        Returns:
            Tuple of (authorization_url, state)
        """
        self._state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": self._state,
        }

        if self.scope:
            params["scope"] = self.scope

        if self.use_pkce:
            self._code_verifier = secrets.token_urlsafe(64)
            challenge_bytes = hashlib.sha256(self._code_verifier.encode()).digest()
            self._code_challenge = (
                base64.urlsafe_b64encode(challenge_bytes).decode().rstrip("=")
            )
            params["code_challenge"] = self._code_challenge
            params["code_challenge_method"] = "S256"

        auth_url = (
            f"{base_url.rstrip('/')}{self.authorization_base_url}?{urlencode(params)}"
        )
        return auth_url, self._state or ""

    async def exchange_code_for_token(
        self,
        authorization_code: str,
        state: Optional[str] = None,
    ) -> OAuthTokenResponse:
        """Exchange an authorization code for access and refresh tokens.

        Args:
            authorization_code: The authorization code from the OAuth callback
            state: State parameter from the callback (for CSRF validation)

        Returns:
            Token response containing access and refresh tokens
        """
        if state and state != self._state:
            raise ValueError("State parameter mismatch - possible CSRF attack")

        payload = {
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": self.redirect_uri,
            "client_id": self.client_id,
        }

        if self.client_secret:
            payload["client_secret"] = self.client_secret

        if self.use_pkce and self._code_verifier:
            payload["code_verifier"] = self._code_verifier

        response = await self.api_client.post(self.token_url, json_data=payload)
        token_response = OAuthTokenResponse(**response)

        self._access_token = token_response.access_token
        self._refresh_token = token_response.refresh_token

        if token_response.expires_in:
            self._access_token_expires_at = time.time() + token_response.expires_in - 60

        self.api_client.set_auth_header(self._access_token)
        return token_response

    def set_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> None:
        """Manually set tokens (useful for restoring previously saved tokens).

        Args:
            access_token: Access token
            refresh_token: Refresh token
            expires_in: Token expiry in seconds from now
        """
        self._access_token = access_token
        self._refresh_token = refresh_token
        if expires_in:
            self._access_token_expires_at = time.time() + expires_in - 60

    async def get_access_token(self) -> str:
        """Get a valid access token, refreshing via refresh token if needed."""
        if not self._is_token_valid():
            if self._refresh_token:
                await self._refresh_access_token()
            else:
                raise ValueError(
                    "No valid access token available. Please complete OAuth flow first."
                )
        return self._access_token or ""

    async def refresh_if_needed(self) -> None:
        """Refresh the access token if expired and a refresh token is available."""
        if not self._is_token_valid() and self._refresh_token:
            await self._refresh_access_token()

    async def revoke_token(self) -> None:
        """Clear all stored tokens and remove the Authorization header."""
        self._access_token = None
        self._refresh_token = None
        self._access_token_expires_at = None
        self.api_client.remove_auth_header()

    def _is_token_valid(self) -> bool:
        if not self._access_token:
            return False
        if not self._access_token_expires_at:
            return True
        return time.time() < self._access_token_expires_at

    async def _refresh_access_token(self) -> None:
        if not self._refresh_token:
            raise ValueError("No refresh token available")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self.client_id,
        }

        if self.client_secret:
            payload["client_secret"] = self.client_secret

        response = await self.api_client.post(self.token_url, json_data=payload)
        token_response = OAuthTokenResponse(**response)

        self._access_token = token_response.access_token
        if token_response.refresh_token:
            self._refresh_token = token_response.refresh_token

        if token_response.expires_in:
            self._access_token_expires_at = time.time() + token_response.expires_in - 60

        self.api_client.set_auth_header(self._access_token)


class AsyncAuthManager:
    """Async authentication manager that delegates to an auth provider.

    Unlike the sync AuthManager, this does NOT eagerly fetch a token on
    construction — tokens are fetched lazily on the first API call.
    """

    def __init__(self, auth_provider: AsyncAuthProvider) -> None:
        self.auth_provider = auth_provider

    async def refresh_token_if_needed(self) -> None:
        """Ensure a valid token is in place before making an API request."""
        await self.auth_provider.refresh_if_needed()

    async def revoke_current_token(self) -> None:
        """Revoke the current access token and clear it from memory."""
        await self.auth_provider.revoke_token()
