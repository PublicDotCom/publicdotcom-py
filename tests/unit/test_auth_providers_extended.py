"""Extended tests for authentication providers."""
import time
from datetime import datetime, timezone
from unittest.mock import Mock, patch

import pytest

from public_api_sdk.api_client import ApiClient
from public_api_sdk.auth_provider import ApiKeyAuthProvider, OAuthAuthProvider
from public_api_sdk.models.auth import OAuthTokenResponse


class TestApiKeyAuthProviderExtended:
    """Extended tests for API key authentication provider."""

    @pytest.fixture
    def mock_api_client(self):
        return Mock(spec=ApiClient)

    def test_validity_minutes_minimum_boundary(self, mock_api_client):
        """validity_minutes must be at least 5."""
        with pytest.raises(ValueError, match="5 and 1440"):
            ApiKeyAuthProvider(
                api_client=mock_api_client,
                api_secret_key="test_secret",
                validity_minutes=4,
            )

    def test_validity_minutes_maximum_boundary(self, mock_api_client):
        """validity_minutes must be at most 1440."""
        with pytest.raises(ValueError, match="5 and 1440"):
            ApiKeyAuthProvider(
                api_client=mock_api_client,
                api_secret_key="test_secret",
                validity_minutes=1441,
            )

    def test_validity_minutes_exact_minimum(self, mock_api_client):
        """validity_minutes=5 should be valid."""
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
            validity_minutes=5,
        )
        assert provider._validity_minutes == 5

    def test_validity_minutes_exact_maximum(self, mock_api_client):
        """validity_minutes=1440 should be valid."""
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
            validity_minutes=1440,
        )
        assert provider._validity_minutes == 1440

    def test_token_creation_payload(self, mock_api_client):
        """Token creation should send correct payload."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="my_secret_key",
            validity_minutes=30,
        )
        
        provider.get_access_token()
        
        mock_api_client.post.assert_called_once_with(
            "/userapiauthservice/personal/access-tokens",
            json_data={
                "secret": "my_secret_key",
                "validityInMinutes": 30,
            }
        )

    def test_token_expiry_calculation(self, mock_api_client):
        """Token expiry should account for safety buffer."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
            validity_minutes=15,
        )
        
        before_call = time.time()
        provider.get_access_token()
        after_call = time.time()
        
        # Expected: (15 - 5) minutes * 60 seconds = 600 seconds from now
        expected_min = before_call + 600
        expected_max = after_call + 600
        
        assert expected_min <= provider._access_token_expires_at <= expected_max

    def test_token_not_valid_initially(self, mock_api_client):
        """Token should not be valid before first fetch."""
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        assert not provider._is_token_valid()

    def test_token_valid_after_fetch(self, mock_api_client):
        """Token should be valid immediately after fetch."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        provider.get_access_token()
        
        assert provider._is_token_valid()

    def test_token_refresh_on_expiry(self, mock_api_client):
        """Token should be refreshed when expired."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
            validity_minutes=5,  # Minimum to make expiry quick
        )
        
        # First fetch
        provider.get_access_token()
        assert mock_api_client.post.call_count == 1
        
        # Simulate expiry by setting past time
        provider._access_token_expires_at = time.time() - 1
        
        # Should trigger refresh
        provider.get_access_token()
        assert mock_api_client.post.call_count == 2

    def test_auth_header_set_on_token_fetch(self, mock_api_client):
        """Auth header should be set when token is fetched."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        
        provider.get_access_token()
        
        mock_api_client.set_auth_header.assert_called_once_with("token123")

    def test_revoke_token_clears_state(self, mock_api_client):
        """Revoke should clear token and remove auth header."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        
        provider.get_access_token()
        assert provider._access_token is not None
        
        provider.revoke_token()
        
        assert provider._access_token is None
        assert provider._access_token_expires_at is None
        mock_api_client.remove_auth_header.assert_called_once()

    def test_refresh_if_needed_creates_new_token(self, mock_api_client):
        """refresh_if_needed should create token if none exists."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        
        provider.refresh_if_needed()
        
        assert provider._access_token == "token123"

    def test_get_access_token_returns_string(self, mock_api_client):
        """get_access_token should return token string."""
        mock_api_client.post.return_value = {"accessToken": "token123"}
        
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        
        token = provider.get_access_token()
        assert token == "token123"
        assert isinstance(token, str)

    def test_default_validity_minutes(self, mock_api_client):
        """Default validity_minutes should be 15."""
        provider = ApiKeyAuthProvider(
            api_client=mock_api_client,
            api_secret_key="test_secret",
        )
        assert provider._validity_minutes == 15


class TestOAuthAuthProviderExtended:
    """Extended tests for OAuth authentication provider."""

    @pytest.fixture
    def mock_api_client(self):
        return Mock(spec=ApiClient)

    def test_pkce_code_verifier_length(self, mock_api_client):
        """PKCE code verifier should be at least 64 characters."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
            use_pkce=True,
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        assert len(provider._code_verifier) >= 64
        assert provider._code_challenge is not None

    def test_pkce_code_challenge_is_base64(self, mock_api_client):
        """PKCE code challenge should be base64url encoded SHA256 hash."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
            use_pkce=True,
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        # Base64url should not have padding
        assert "=" not in provider._code_challenge
        # Should be URL-safe characters only
        import re
        assert re.match(r'^[A-Za-z0-9_-]+$', provider._code_challenge)

    def test_state_csrf_protection_mismatch(self, mock_api_client):
        """State mismatch should raise ValueError."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        with pytest.raises(ValueError, match="CSRF"):
            provider.exchange_code_for_token("code123", state="wrong_state")

    def test_state_csrf_protection_valid(self, mock_api_client):
        """Correct state should allow token exchange."""
        mock_api_client.post.return_value = {
            "access_token": "access123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
        }
        
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        # Should not raise
        provider.exchange_code_for_token("code123", state=state)

    def test_state_optional(self, mock_api_client):
        """State validation should be optional."""
        mock_api_client.post.return_value = {
            "access_token": "access123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
        }
        
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        # Should work without state parameter
        provider.exchange_code_for_token("code123")

    def test_exchange_code_includes_pkce(self, mock_api_client):
        """Token exchange should include PKCE verifier."""
        mock_api_client.post.return_value = {
            "access_token": "access123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
        }
        
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
            use_pkce=True,
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        provider.exchange_code_for_token("code123", state=state)
        
        call_args = mock_api_client.post.call_args
        payload = call_args.kwargs.get('json_data', call_args[1].get('json_data'))
        
        assert payload.get("code_verifier") == provider._code_verifier

    def test_token_expiry_calculation(self, mock_api_client):
        """Token expiry should be calculated with safety buffer."""
        mock_api_client.post.return_value = {
            "access_token": "access123",
            "refresh_token": "refresh123",
            "expires_in": 3600,
        }
        
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        before_call = time.time()
        provider.exchange_code_for_token("code123")
        after_call = time.time()
        
        # Expected: 3600 - 60 seconds safety buffer = 3540 seconds
        expected_min = before_call + 3540
        expected_max = after_call + 3540
        
        assert expected_min <= provider._access_token_expires_at <= expected_max

    def test_refresh_token_without_refresh_token_raises(self, mock_api_client):
        """Refreshing without refresh token should raise clear error."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        # Set expired token without refresh
        provider.set_tokens(access_token="expired", expires_in=-100)
        
        with pytest.raises(ValueError, match="No refresh token"):
            provider.get_access_token()

    def test_set_tokens_manually(self, mock_api_client):
        """set_tokens should allow manual token setting."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        provider.set_tokens(
            access_token="access123",
            refresh_token="refresh123",
            expires_in=3600,
        )
        
        assert provider.get_access_token() == "access123"
        assert provider._refresh_token == "refresh123"

    def test_revoke_token_clears_all_tokens(self, mock_api_client):
        """Revoke should clear all token state."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        provider.set_tokens(
            access_token="access123",
            refresh_token="refresh123",
            expires_in=3600,
        )
        
        provider.revoke_token()
        
        assert provider._access_token is None
        assert provider._refresh_token is None
        assert provider._access_token_expires_at is None
        mock_api_client.remove_auth_header.assert_called_once()

    def test_refresh_access_token_uses_stored_refresh(self, mock_api_client):
        """Token refresh should use stored refresh token."""
        mock_api_client.post.return_value = {
            "access_token": "new_access",
            "refresh_token": "new_refresh",
            "expires_in": 3600,
        }
        
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
            client_secret="secret123",
        )
        
        provider.set_tokens(
            access_token="old_access",
            refresh_token="old_refresh",
            expires_in=-100,  # Expired
        )
        
        provider.get_access_token()  # Should trigger refresh
        
        call_args = mock_api_client.post.call_args
        payload = call_args.kwargs.get('json_data', call_args[1].get('json_data'))
        
        assert payload.get("refresh_token") == "old_refresh"
        assert payload.get("client_id") == "client123"
        assert payload.get("client_secret") == "secret123"

    def test_authorization_url_includes_scope(self, mock_api_client):
        """Authorization URL should include scope if provided."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
            scope="marketdata trading",
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        assert "scope=marketdata+trading" in url

    def test_authorization_url_without_pkce(self, mock_api_client):
        """Authorization URL should not include PKCE when disabled."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
            use_pkce=False,
        )
        
        url, state = provider.get_authorization_url("https://api.public.com")
        
        assert "code_challenge" not in url
        assert "code_challenge_method" not in url

    def test_token_valid_without_expiry(self, mock_api_client):
        """Token should be valid if no expiry is set."""
        provider = OAuthAuthProvider(
            api_client=mock_api_client,
            client_id="client123",
            redirect_uri="https://example.com/callback",
        )
        
        provider.set_tokens(access_token="access123")  # No expires_in
        
        assert provider._is_token_valid()
