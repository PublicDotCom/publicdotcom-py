"""Tests for authentication providers."""

import time
from unittest.mock import Mock
import pytest

from public_api_sdk.api_client import ApiClient
from public_api_sdk.auth_provider import (
    ApiKeyAuthProvider,
    OAuthAuthProvider,
)


class TestApiKeyAuthProvider:
    """Tests for API key authentication provider."""

    def setup_method(self) -> None:
        self.api_client = Mock(spec=ApiClient)
        self.provider = ApiKeyAuthProvider(
            api_client=self.api_client,
            api_secret_key="secret_123",
            validity_minutes=15,
        )

    def test_init_with_invalid_validity(self) -> None:
        """Test initialization with invalid validity."""
        with pytest.raises(
            ValueError, match="Validity must be between 5 and 1440 minutes"
        ):
            ApiKeyAuthProvider(
                api_client=self.api_client,
                api_secret_key="secret_123",
                validity_minutes=2000,
            )

    def test_create_access_token(self) -> None:
        """Test creating an access token."""
        self.api_client.post.return_value = {
            "accessToken": "token_123",
        }

        token = self.provider.get_access_token()

        assert token == "token_123"
        self.api_client.post.assert_called_once_with(
            "/userapiauthservice/personal/access-tokens",
            json_data={
                "secret": "secret_123",
                "validityInMinutes": 15,
            },
        )
        self.api_client.set_auth_header.assert_called_once_with("token_123")

    def test_token_validity_check(self) -> None:
        """Test token validity checking."""
        # No token initially
        assert not self.provider._is_token_valid()

        # Set valid token
        self.provider._access_token = "token_123"
        self.provider._access_token_expires_at = time.time() + 3600
        assert self.provider._is_token_valid()

        # Set expired token
        self.provider._access_token_expires_at = time.time() - 3600
        assert not self.provider._is_token_valid()

    def test_refresh_if_needed(self) -> None:
        """Test token refresh when needed."""
        self.api_client.post.return_value = {
            "accessToken": "new_token_123",
        }

        # Initially no token, should create one
        self.provider.refresh_if_needed()
        self.api_client.post.assert_called_once()

        # Set valid token, should not refresh
        self.api_client.reset_mock()
        self.provider._access_token = "token_123"
        self.provider._access_token_expires_at = time.time() + 3600
        self.provider.refresh_if_needed()
        self.api_client.post.assert_not_called()

    def test_revoke_token(self) -> None:
        """Test token revocation."""
        self.provider._access_token = "token_123"
        self.provider._access_token_expires_at = time.time() + 3600

        self.provider.revoke_token()

        assert self.provider._access_token is None
        assert self.provider._access_token_expires_at is None
        self.api_client.remove_auth_header.assert_called_once()


class TestOAuthAuthProvider:
    """Tests for OAuth authentication provider."""

    def setup_method(self) -> None:
        self.api_client = Mock(spec=ApiClient)
        self.provider = OAuthAuthProvider(
            api_client=self.api_client,
            client_id="client_123",
            client_secret="secret_456",
            redirect_uri="http://localhost:8080/callback",
            scope="trading marketdata",
            use_pkce=True,
        )

    def test_get_authorization_url(self) -> None:
        """Test authorization URL generation."""
        base_url = "https://api.example.com"
        auth_url, state = self.provider.get_authorization_url(base_url)

        # Check URL structure
        assert auth_url.startswith(f"{base_url}/userapiauthservice/oauth2/authorize?")
        assert "client_id=client_123" in auth_url
        assert "redirect_uri=http%3A%2F%2Flocalhost%3A8080%2Fcallback" in auth_url
        assert "response_type=code" in auth_url
        assert f"state={state}" in auth_url
        assert "scope=trading+marketdata" in auth_url

        # Check PKCE parameters
        assert "code_challenge=" in auth_url
        assert "code_challenge_method=S256" in auth_url
        assert self.provider._code_verifier is not None
        assert self.provider._code_challenge is not None

    def test_get_authorization_url_without_pkce(self) -> None:
        """Test authorization URL generation without PKCE."""
        provider = OAuthAuthProvider(
            api_client=self.api_client,
            client_id="client_123",
            redirect_uri="http://localhost:8080/callback",
            use_pkce=False,
        )

        auth_url, state = provider.get_authorization_url("https://api.example.com")

        assert "code_challenge" not in auth_url
        assert "code_challenge_method" not in auth_url
        assert provider._code_verifier is None

    def test_exchange_code_for_token(self) -> None:
        """Test exchanging authorization code for tokens."""
        # Setup state for validation
        self.provider._state = "test_state"
        self.provider._code_verifier = "test_verifier"

        # Mock token response
        self.api_client.post.return_value = {
            "access_token": "access_123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "refresh_456",
            "scope": "trading marketdata",
        }

        response = self.provider.exchange_code_for_token("auth_code_789", "test_state")

        # Verify response
        assert response.access_token == "access_123"
        assert response.refresh_token == "refresh_456"
        assert response.expires_in == 3600

        # Verify tokens are stored
        assert self.provider._access_token == "access_123"
        assert self.provider._refresh_token == "refresh_456"
        assert self.provider._access_token_expires_at is not None

        # Verify API call
        self.api_client.post.assert_called_once_with(
            "/userapiauthservice/oauth2/token",
            json_data={
                "grant_type": "authorization_code",
                "code": "auth_code_789",
                "redirect_uri": "http://localhost:8080/callback",
                "client_id": "client_123",
                "client_secret": "secret_456",
                "code_verifier": "test_verifier",
            },
        )
        self.api_client.set_auth_header.assert_called_once_with("access_123")

    def test_exchange_code_state_mismatch(self) -> None:
        """Test code exchange with state mismatch."""
        self.provider._state = "expected_state"

        with pytest.raises(ValueError, match="State parameter mismatch"):
            self.provider.exchange_code_for_token("auth_code_789", "wrong_state")

    def test_set_tokens(self) -> None:
        """Test manually setting tokens."""
        self.provider.set_tokens(
            access_token="manual_access",
            refresh_token="manual_refresh",
            expires_in=7200,
        )

        assert self.provider._access_token == "manual_access"
        assert self.provider._refresh_token == "manual_refresh"
        assert self.provider._access_token_expires_at is not None

    def test_refresh_access_token(self) -> None:
        """Test refreshing access token with refresh token."""
        # Set initial tokens
        self.provider._refresh_token = "refresh_456"
        self.provider._access_token = "old_access"

        # Mock refresh response
        self.api_client.post.return_value = {
            "access_token": "new_access_123",
            "token_type": "Bearer",
            "expires_in": 3600,
            "refresh_token": "new_refresh_789",
        }

        self.provider._refresh_access_token()

        # Verify tokens are updated
        assert self.provider._access_token == "new_access_123"
        assert self.provider._refresh_token == "new_refresh_789"

        # Verify API call
        self.api_client.post.assert_called_once_with(
            "/userapiauthservice/oauth2/token",
            json_data={
                "grant_type": "refresh_token",
                "refresh_token": "refresh_456",
                "client_id": "client_123",
                "client_secret": "secret_456",
            },
        )
        self.api_client.set_auth_header.assert_called_once_with("new_access_123")

    def test_refresh_without_refresh_token(self) -> None:
        """Test refresh attempt without refresh token."""
        self.provider._refresh_token = None

        with pytest.raises(ValueError, match="No refresh token available"):
            self.provider._refresh_access_token()

    def test_get_access_token_no_token(self) -> None:
        """Test getting access token when none is available."""
        with pytest.raises(ValueError, match="No valid access token available"):
            self.provider.get_access_token()

    def test_get_access_token_with_refresh(self) -> None:
        """Test getting access token with automatic refresh."""
        # Set expired token with refresh token
        self.provider._access_token = "expired_token"
        self.provider._access_token_expires_at = time.time() - 100
        self.provider._refresh_token = "refresh_456"

        # Mock refresh response
        self.api_client.post.return_value = {
            "access_token": "new_access_123",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        token = self.provider.get_access_token()

        assert token == "new_access_123"
        self.api_client.post.assert_called_once()

    def test_revoke_token(self) -> None:
        """Test token revocation."""
        self.provider._access_token = "token_123"
        self.provider._refresh_token = "refresh_456"
        self.provider._access_token_expires_at = time.time() + 3600

        self.provider.revoke_token()

        assert self.provider._access_token is None
        assert self.provider._refresh_token is None
        assert self.provider._access_token_expires_at is None
        self.api_client.remove_auth_header.assert_called_once()
