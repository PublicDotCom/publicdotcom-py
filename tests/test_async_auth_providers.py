"""Tests for async authentication providers and manager."""

import time
from unittest.mock import AsyncMock, Mock

import pytest

from public_api_sdk.async_api_client import AsyncApiClient
from public_api_sdk.async_auth_provider import (
    AsyncApiKeyAuthProvider,
    AsyncAuthManager,
    AsyncOAuthAuthProvider,
)


# ---------------------------------------------------------------------------
# AsyncApiKeyAuthProvider
# ---------------------------------------------------------------------------


class TestAsyncApiKeyAuthProvider:
    def setup_method(self) -> None:
        self.api_client = Mock(spec=AsyncApiClient)
        self.api_client.post = AsyncMock(return_value={"accessToken": "token_123"})
        self.provider = AsyncApiKeyAuthProvider(
            api_client=self.api_client,
            api_secret_key="secret_key",
            validity_minutes=15,
        )

    def test_init_rejects_invalid_validity_too_low(self) -> None:
        with pytest.raises(ValueError, match="Validity must be between 5 and 1440"):
            AsyncApiKeyAuthProvider(
                api_client=self.api_client,
                api_secret_key="key",
                validity_minutes=4,
            )

    def test_init_rejects_invalid_validity_too_high(self) -> None:
        with pytest.raises(ValueError, match="Validity must be between 5 and 1440"):
            AsyncApiKeyAuthProvider(
                api_client=self.api_client,
                api_secret_key="key",
                validity_minutes=1441,
            )

    def test_token_initially_invalid(self) -> None:
        assert not self.provider._is_token_valid()

    def test_token_valid_after_setting(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() + 600
        assert self.provider._is_token_valid()

    def test_expired_token_invalid(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() - 1
        assert not self.provider._is_token_valid()

    @pytest.mark.asyncio
    async def test_get_access_token_creates_token(self) -> None:
        token = await self.provider.get_access_token()
        assert token == "token_123"
        self.api_client.post.assert_called_once_with(
            "/userapiauthservice/personal/access-tokens",
            json_data={"secret": "secret_key", "validityInMinutes": 15},
        )

    @pytest.mark.asyncio
    async def test_get_access_token_sets_auth_header(self) -> None:
        await self.provider.get_access_token()
        self.api_client.set_auth_header.assert_called_once_with("token_123")

    @pytest.mark.asyncio
    async def test_get_access_token_does_not_recreate_valid_token(self) -> None:
        self.provider._access_token = "existing_token"
        self.provider._access_token_expires_at = time.time() + 600
        token = await self.provider.get_access_token()
        assert token == "existing_token"
        self.api_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_if_needed_creates_token_when_missing(self) -> None:
        await self.provider.refresh_if_needed()
        self.api_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_if_needed_skips_when_valid(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() + 600
        await self.provider.refresh_if_needed()
        self.api_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_if_needed_refreshes_expired_token(self) -> None:
        self.provider._access_token = "old"
        self.provider._access_token_expires_at = time.time() - 1
        await self.provider.refresh_if_needed()
        self.api_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_token_clears_state(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() + 600
        await self.provider.revoke_token()
        assert self.provider._access_token is None
        assert self.provider._access_token_expires_at is None
        self.api_client.remove_auth_header.assert_called_once()

    @pytest.mark.asyncio
    async def test_token_expiry_applies_five_minute_buffer(self) -> None:
        # validity_minutes=15 → expires_in = (15-5)*60 = 600 seconds
        await self.provider.get_access_token()
        assert self.provider._access_token_expires_at is not None
        remaining = self.provider._access_token_expires_at - time.time()
        assert 595 < remaining <= 600


# ---------------------------------------------------------------------------
# AsyncOAuthAuthProvider
# ---------------------------------------------------------------------------


class TestAsyncOAuthAuthProvider:
    def setup_method(self) -> None:
        self.api_client = Mock(spec=AsyncApiClient)
        self.api_client.post = AsyncMock()
        self.provider = AsyncOAuthAuthProvider(
            api_client=self.api_client,
            client_id="client_id_123",
            redirect_uri="https://app.example.com/callback",
            client_secret="client_secret",
            scope="trading marketdata",
            use_pkce=True,
        )

    def test_token_initially_invalid(self) -> None:
        assert not self.provider._is_token_valid()

    def test_token_valid_when_no_expiry_set(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = None
        assert self.provider._is_token_valid()

    def test_token_valid_before_expiry(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() + 3600
        assert self.provider._is_token_valid()

    def test_token_invalid_after_expiry(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() - 1
        assert not self.provider._is_token_valid()

    def test_get_authorization_url_contains_client_id(self) -> None:
        url, state = self.provider.get_authorization_url("https://api.example.com")
        assert "client_id=client_id_123" in url
        assert state is not None and len(state) > 0

    def test_get_authorization_url_contains_redirect_uri(self) -> None:
        url, _ = self.provider.get_authorization_url("https://api.example.com")
        assert "redirect_uri=" in url

    def test_get_authorization_url_contains_scope(self) -> None:
        url, _ = self.provider.get_authorization_url("https://api.example.com")
        assert "scope=" in url

    def test_get_authorization_url_includes_pkce_challenge(self) -> None:
        url, _ = self.provider.get_authorization_url("https://api.example.com")
        assert "code_challenge=" in url
        assert "code_challenge_method=S256" in url

    def test_get_authorization_url_generates_unique_state(self) -> None:
        _, state1 = self.provider.get_authorization_url("https://api.example.com")
        _, state2 = self.provider.get_authorization_url("https://api.example.com")
        assert state1 != state2

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_calls_token_endpoint(self) -> None:
        self.api_client.post.return_value = {
            "access_token": "access_tok",
            "refresh_token": "refresh_tok",
            "expires_in": 3600,
        }
        self.provider.get_authorization_url("https://api.example.com")
        response = await self.provider.exchange_code_for_token("auth_code_xyz")
        self.api_client.post.assert_called_once()
        assert response.access_token == "access_tok"

    @pytest.mark.asyncio
    async def test_exchange_code_for_token_sets_auth_header(self) -> None:
        self.api_client.post.return_value = {
            "access_token": "access_tok",
            "refresh_token": "refresh_tok",
            "expires_in": 3600,
        }
        self.provider.get_authorization_url("https://api.example.com")
        await self.provider.exchange_code_for_token("auth_code_xyz")
        self.api_client.set_auth_header.assert_called_once_with("access_tok")

    @pytest.mark.asyncio
    async def test_exchange_code_raises_on_state_mismatch(self) -> None:
        self.provider.get_authorization_url("https://api.example.com")
        with pytest.raises(ValueError, match="State parameter mismatch"):
            await self.provider.exchange_code_for_token(
                "auth_code", state="wrong_state"
            )

    def test_set_tokens_stores_access_token(self) -> None:
        self.provider.set_tokens("access_tok", "refresh_tok", expires_in=3600)
        assert self.provider._access_token == "access_tok"
        assert self.provider._refresh_token == "refresh_tok"

    @pytest.mark.asyncio
    async def test_get_access_token_raises_without_oauth_flow(self) -> None:
        with pytest.raises(ValueError, match="No valid access token"):
            await self.provider.get_access_token()

    @pytest.mark.asyncio
    async def test_get_access_token_returns_valid_token(self) -> None:
        self.provider._access_token = "valid_tok"
        self.provider._access_token_expires_at = time.time() + 3600
        token = await self.provider.get_access_token()
        assert token == "valid_tok"

    @pytest.mark.asyncio
    async def test_get_access_token_refreshes_via_refresh_token(self) -> None:
        self.provider._access_token = "old"
        self.provider._access_token_expires_at = time.time() - 1
        self.provider._refresh_token = "refresh_tok"
        self.api_client.post.return_value = {
            "access_token": "new_tok",
            "expires_in": 3600,
        }
        token = await self.provider.get_access_token()
        assert token == "new_tok"

    @pytest.mark.asyncio
    async def test_refresh_if_needed_skips_when_valid(self) -> None:
        self.provider._access_token = "tok"
        self.provider._access_token_expires_at = time.time() + 3600
        await self.provider.refresh_if_needed()
        self.api_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_refresh_if_needed_refreshes_when_expired_and_refresh_token_present(
        self,
    ) -> None:
        self.provider._access_token = "old"
        self.provider._access_token_expires_at = time.time() - 1
        self.provider._refresh_token = "refresh_tok"
        self.api_client.post.return_value = {
            "access_token": "new_tok",
            "expires_in": 3600,
        }
        await self.provider.refresh_if_needed()
        self.api_client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_refresh_if_needed_skips_when_expired_but_no_refresh_token(
        self,
    ) -> None:
        self.provider._access_token = "old"
        self.provider._access_token_expires_at = time.time() - 1
        # No refresh token — should not raise, just skip
        await self.provider.refresh_if_needed()
        self.api_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_revoke_token_clears_all_tokens(self) -> None:
        self.provider._access_token = "tok"
        self.provider._refresh_token = "refresh"
        self.provider._access_token_expires_at = time.time() + 3600
        await self.provider.revoke_token()
        assert self.provider._access_token is None
        assert self.provider._refresh_token is None
        assert self.provider._access_token_expires_at is None
        self.api_client.remove_auth_header.assert_called_once()


# ---------------------------------------------------------------------------
# AsyncAuthManager
# ---------------------------------------------------------------------------


class TestAsyncAuthManager:
    def setup_method(self) -> None:
        self.mock_provider = Mock()
        self.mock_provider.refresh_if_needed = AsyncMock()
        self.mock_provider.revoke_token = AsyncMock()
        self.manager = AsyncAuthManager(auth_provider=self.mock_provider)

    def test_auth_provider_stored(self) -> None:
        assert self.manager.auth_provider is self.mock_provider

    @pytest.mark.asyncio
    async def test_refresh_token_if_needed_delegates_to_provider(self) -> None:
        await self.manager.refresh_token_if_needed()
        self.mock_provider.refresh_if_needed.assert_called_once()

    @pytest.mark.asyncio
    async def test_revoke_current_token_delegates_to_provider(self) -> None:
        await self.manager.revoke_current_token()
        self.mock_provider.revoke_token.assert_called_once()
