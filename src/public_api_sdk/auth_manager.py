"""Authentication manager for managing access tokens"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .auth_provider import AuthProvider


class AuthManager:
    """Authentication manager that delegates to auth providers"""

    def __init__(self, auth_provider: "AuthProvider") -> None:
        """Initialize the authentication manager.

        Args:
            auth_provider: Authentication provider (already initialized with ApiClient)
        """
        super().__init__()

        self.auth_provider = auth_provider
        self.initialize_auth()

    def initialize_auth(self) -> None:
        """Initialize authentication by getting the first token."""
        try:
            # try to get an access token (will create one for API key auth)
            self.auth_provider.get_access_token()
        except ValueError:
            # for oauth, user needs to complete the flow first
            pass

    def refresh_token_if_needed(self) -> None:
        """Refresh the access token if it's expired or about to expire."""
        self.auth_provider.refresh_if_needed()

    def revoke_current_token(self) -> None:
        """Revoke the current access token and clear it from memory."""
        self.auth_provider.revoke_token()
