import base64
import hashlib
import secrets
import time
from abc import ABC, abstractmethod
from typing import Optional, Tuple
from urllib.parse import urlencode

from .api_client import ApiClient
from .models.auth import OAuthTokenResponse


class AuthProvider(ABC):
    """Abstract base class for authentication providers."""

    def __init__(self, api_client: ApiClient) -> None:
        """Initialize the auth provider.
        
        Args:
            api_client: API client for making HTTP requests
        """
        self.api_client = api_client

    @abstractmethod
    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary.

        Returns:
            Valid access token
        """

    @abstractmethod
    def refresh_if_needed(self) -> None:
        """Refresh the access token if needed."""

    @abstractmethod
    def revoke_token(self) -> None:
        """Revoke the current access token."""


class ApiKeyAuthProvider(AuthProvider):
    """Authentication provider for first party API key authentication."""

    def __init__(self, api_client: ApiClient, api_secret_key: str, validity_minutes: int = 15) -> None:
        """Initialize the API key auth provider.

        Args:
            api_client: API client for making HTTP requests
            api_secret_key: API secret key
            validity_minutes: Token validity in minutes (5-1440)
        """
        super().__init__(api_client)

        if not 5 <= validity_minutes <= 1440:
            raise ValueError("Validity must be between 5 and 1440 minutes")

        self._secret = api_secret_key
        self._validity_minutes = validity_minutes

        self._access_token: Optional[str] = None
        self._access_token_expires_at: Optional[float] = None

    def get_access_token(self) -> str:
        """Get a valid access token, creating one if necessary."""
        if not self._is_token_valid():
            self._create_personal_access_token()
        return self._access_token or ""

    def refresh_if_needed(self) -> None:
        """Refresh the access token if it's expired or about to expire."""
        if not self._is_token_valid():
            self._create_personal_access_token()

    def revoke_token(self) -> None:
        """Revoke the current access token."""
        self._access_token = None
        self._access_token_expires_at = None
        self.api_client.remove_auth_header()

    def _is_token_valid(self) -> bool:
        """Check if the current access token is valid."""
        if not self._access_token or not self._access_token_expires_at:
            return False
        return time.time() < self._access_token_expires_at

    def _create_personal_access_token(self) -> None:
        """Create a new access token using the API key."""
        payload = {
            "secret": self._secret,
            "validityInMinutes": self._validity_minutes,
        }

        response = self.api_client.post(
            "/userapiauthservice/personal/access-tokens", json_data=payload
        )

        # store token and expiry time
        self._access_token = response.get("accessToken")
        if self._access_token:
            # calculate expiry time (subtract 5 minutes for safety buffer)
            expires_in_seconds = (self._validity_minutes - 5) * 60
            self._access_token_expires_at = time.time() + expires_in_seconds

            self.api_client.set_auth_header(self._access_token)


class OAuthAuthProvider(AuthProvider):
    """Authentication provider for OAuth2 authentication."""

    def __init__(
        self,
        api_client: ApiClient,
        client_id: str,
        redirect_uri: str,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        use_pkce: bool = True,
        authorization_base_url: str = "/userapiauthservice/oauth2/authorize",
        token_url: str = "/userapiauthservice/oauth2/token",
    ) -> None:
        """Initialize the OAuth auth provider.

        Args:
            api_client: API client for making HTTP requests
            client_id: OAuth client ID
            redirect_uri: Redirect URI for OAuth flow
            client_secret: OAuth client secret (optional for public clients)
            scope: Space-separated list of scopes
            use_pkce: Whether to use PKCE for enhanced security
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

        # Token storage
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._access_token_expires_at: Optional[float] = None

        # PKCE parameters
        self._code_verifier: Optional[str] = None
        self._code_challenge: Optional[str] = None
        self._state: Optional[str] = None

    def get_authorization_url(self, base_url: str) -> Tuple[str, str]:
        """Generate the OAuth authorization URL.

        Args:
            base_url: Base URL of the API

        Returns:
            Tuple of (authorization_url, state)
        """
        # Generate state for CSRF protection
        self._state = secrets.token_urlsafe(32)

        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "state": self._state,
        }

        if self.scope:
            params["scope"] = self.scope

        # Add PKCE parameters if enabled
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
        return auth_url, self._state

    def exchange_code_for_token(
        self,
        authorization_code: str,
        state: Optional[str] = None,
    ) -> OAuthTokenResponse:
        """Exchange authorization code for access token.

        Args:
            authorization_code: The authorization code from the OAuth callback
            state: State parameter from the callback (for validation)

        Returns:
            Token response containing access and refresh tokens

        Raises:
            ValueError: If state doesn't match
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

        response = self.api_client.post(self.token_url, json_data=payload)
        token_response = OAuthTokenResponse(**response)

        # Store tokens
        self._access_token = token_response.access_token
        self._refresh_token = token_response.refresh_token

        # Calculate expiry time (subtract 60 seconds for safety buffer)
        if token_response.expires_in:
            self._access_token_expires_at = time.time() + token_response.expires_in - 60

        # Set auth header
        self.api_client.set_auth_header(self._access_token)

        return token_response

    def set_tokens(
        self,
        access_token: str,
        refresh_token: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> None:
        """Manually set tokens (useful for restoring saved tokens).

        Args:
            access_token: Access token
            refresh_token: Refresh token
            expires_in: Token expiry in seconds
        """
        self._access_token = access_token
        self._refresh_token = refresh_token

        if expires_in:
            self._access_token_expires_at = time.time() + expires_in - 60

    def get_access_token(self) -> str:
        """Get a valid access token, refreshing if necessary."""
        if not self._is_token_valid():
            if self._refresh_token:
                self._refresh_access_token()
            else:
                raise ValueError(
                    "No valid access token available. Please complete OAuth flow first."
                )
        return self._access_token or ""

    def refresh_if_needed(self) -> None:
        """Refresh the access token if it's expired or about to expire."""
        if not self._is_token_valid() and self._refresh_token:
            self._refresh_access_token()

    def revoke_token(self) -> None:
        """Revoke the current access token."""
        self._access_token = None
        self._refresh_token = None
        self._access_token_expires_at = None
        self.api_client.remove_auth_header()

    def _is_token_valid(self) -> bool:
        """Check if the current access token is valid."""
        if not self._access_token:
            return False

        # If no expiry time is set, assume token is valid
        if not self._access_token_expires_at:
            return True

        return time.time() < self._access_token_expires_at

    def _refresh_access_token(self) -> None:
        """Refresh the access token using the refresh token."""
        if not self._refresh_token:
            raise ValueError("No refresh token available")

        payload = {
            "grant_type": "refresh_token",
            "refresh_token": self._refresh_token,
            "client_id": self.client_id,
        }

        if self.client_secret:
            payload["client_secret"] = self.client_secret

        response = self.api_client.post(self.token_url, json_data=payload)
        token_response = OAuthTokenResponse(**response)

        # Update tokens
        self._access_token = token_response.access_token
        if token_response.refresh_token:
            self._refresh_token = token_response.refresh_token

        # Update expiry time
        if token_response.expires_in:
            self._access_token_expires_at = time.time() + token_response.expires_in - 60

        # Update auth header
        self.api_client.set_auth_header(self._access_token)
