from unittest.mock import Mock

from public_api_sdk.api_client import ApiClient
from public_api_sdk.auth_manager import AuthManager
from public_api_sdk.auth_provider import AuthProvider


class TestAuthManager:
    def setup_method(self) -> None:
        self.api_client = Mock(spec=ApiClient)
        self.auth_provider = Mock(spec=AuthProvider)
        self.auth_manager = AuthManager(
            auth_provider=self.auth_provider,
        )

    def test_initialize_auth(self) -> None:
        """Test auth initialization."""
        # provider returns token successfully
        self.auth_provider.get_access_token.return_value = "token_123"
        self.auth_provider.get_access_token.assert_called_once_with()

    def test_initialize_auth_oauth_no_token(self) -> None:
        """Test auth initialization when OAuth has no token yet."""
        # provider raises error (OAuth not completed yet)
        self.auth_provider.get_access_token.side_effect = ValueError("No token")

        # should not raise, just continue
        auth_manager = AuthManager(
            auth_provider=self.auth_provider,
        )

        assert auth_manager.auth_provider == self.auth_provider

    def test_refresh_token_if_needed(self) -> None:
        """Test token refresh delegation to provider."""
        self.auth_manager.refresh_token_if_needed()

        self.auth_provider.refresh_if_needed.assert_called_once_with()

    def test_revoke_current_token(self) -> None:
        """Test token revocation delegation to provider."""
        self.auth_manager.revoke_current_token()

        self.auth_provider.revoke_token.assert_called_once_with()
