from typing import Optional, Protocol, TYPE_CHECKING

from .auth_provider import ApiKeyAuthProvider, OAuthAuthProvider

if TYPE_CHECKING:
    from .api_client import ApiClient
    from .auth_provider import AuthProvider


class AuthConfig(Protocol):  # pylint: disable=too-few-public-methods
    """Protocol for authentication configuration."""

    def create_provider(self, api_client: "ApiClient") -> "AuthProvider":
        """Create an auth provider instance with the given API client.

        Args:
            api_client: API client for making HTTP requests

        Returns:
            Configured auth provider instance
        """


class ApiKeyAuthConfig:  # pylint: disable=too-few-public-methods
    """Configuration for API key authentication."""

    def __init__(self, api_secret_key: str, validity_minutes: int = 15) -> None:
        """Initialize API key auth configuration.

        Args:
            api_secret_key: API secret key generated in the Public API settings page (secret)
            validity_minutes: Token validity in minutes (5-1440)
        """
        if not 5 <= validity_minutes <= 1440:
            raise ValueError("Validity must be between 5 and 1440 minutes")

        self.api_secret_key = api_secret_key
        self.validity_minutes = validity_minutes

    def create_provider(self, api_client: "ApiClient") -> "AuthProvider":
        return ApiKeyAuthProvider(
            api_client=api_client,
            api_secret_key=self.api_secret_key,
            validity_minutes=self.validity_minutes,
        )


class OAuthAuthConfig:  # pylint: disable=too-few-public-methods
    """Configuration for OAuth2 authentication."""

    def __init__(
        self,
        client_id: str,
        redirect_uri: str,
        client_secret: Optional[str] = None,
        scope: Optional[str] = None,
        use_pkce: bool = True,
        authorization_base_url: str = "/userapiauthservice/oauth2/authorize",
        token_url: str = "/userapiauthservice/oauth2/token",
    ) -> None:
        """Initialize OAuth auth configuration.

        Args:
            client_id: OAuth client ID
            redirect_uri: Redirect URI for OAuth flow
            client_secret: OAuth client secret (optional for public clients)
            scope: Space-separated list of scopes
            use_pkce: Whether to use PKCE for enhanced security
            authorization_base_url: Authorization endpoint path
            token_url: Token exchange endpoint path
        """
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.scope = scope
        self.use_pkce = use_pkce
        self.authorization_base_url = authorization_base_url
        self.token_url = token_url

    def create_provider(self, api_client: "ApiClient") -> "AuthProvider":
        return OAuthAuthProvider(
            api_client=api_client,
            client_id=self.client_id,
            client_secret=self.client_secret,
            redirect_uri=self.redirect_uri,
            scope=self.scope,
            use_pkce=self.use_pkce,
            authorization_base_url=self.authorization_base_url,
            token_url=self.token_url,
        )
