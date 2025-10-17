# pylint: disable=protected-access,no-member
# Tests need to access private methods to verify implementation details

from unittest.mock import Mock
import pytest

from public_api_sdk.api_client import ApiClient
from public_api_sdk.auth_config import ApiKeyAuthConfig, OAuthAuthConfig
from public_api_sdk.auth_provider import ApiKeyAuthProvider, OAuthAuthProvider


class TestApiKeyAuthConfig:
    def test_create_provider(self) -> None:
        """Test creating an API key auth provider."""
        api_client = Mock(spec=ApiClient)
        config = ApiKeyAuthConfig(api_secret_key="secret_123", validity_minutes=15)

        provider = config.create_provider(api_client)

        assert isinstance(provider, ApiKeyAuthProvider)
        assert provider.api_client == api_client
        assert provider._secret == "secret_123"
        assert provider._validity_minutes == 15

    def test_invalid_validity(self) -> None:
        """Test configuration with invalid validity."""
        with pytest.raises(
            ValueError, match="Validity must be between 5 and 1440 minutes"
        ):
            ApiKeyAuthConfig(api_secret_key="secret_123", validity_minutes=2000)


class TestOAuthAuthConfig:
    """Tests for OAuth auth configuration."""

    def test_create_provider(self) -> None:
        """Test creating an OAuth auth provider."""
        api_client = Mock(spec=ApiClient)
        config = OAuthAuthConfig(
            client_id="client_123",
            client_secret="secret_456",
            redirect_uri="http://localhost:8080/callback",
            scope="trading marketdata",
            use_pkce=True,
        )

        provider = config.create_provider(api_client)

        assert isinstance(provider, OAuthAuthProvider)
        assert provider.api_client == api_client
        assert provider.client_id == "client_123"
        assert provider.client_secret == "secret_456"
        assert provider.redirect_uri == "http://localhost:8080/callback"
        assert provider.scope == "trading marketdata"
        assert provider.use_pkce is True

    def test_create_provider_without_optional_params(self) -> None:
        """Test creating OAuth provider with minimum configuration."""
        api_client = Mock(spec=ApiClient)
        config = OAuthAuthConfig(
            client_id="client_123", redirect_uri="http://localhost:8080/callback"
        )

        provider = config.create_provider(api_client)

        assert isinstance(provider, OAuthAuthProvider)
        assert provider.client_secret is None
        assert provider.scope is None
        assert provider.use_pkce is True  # Default value
