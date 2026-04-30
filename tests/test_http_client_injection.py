"""Tests for injecting a custom httpx.AsyncClient into the SDK."""

import httpx
import pytest

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
)


@pytest.mark.asyncio
async def test_inject_http_client_uses_provided() -> None:
    """When the caller provides an httpx client, the SDK uses it for outbound requests."""
    captured: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        captured.append(str(request.url))
        return httpx.Response(200, json={"accounts": []})

    mock = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key="test"),
        config=AsyncPublicApiClientConfiguration(base_url="https://example.test"),
        http_client=mock,
    )

    await client.api_client.get("/anything")

    assert captured == ["https://example.test/anything"]
    await mock.aclose()


@pytest.mark.asyncio
async def test_injected_http_client_not_closed_by_sdk() -> None:
    """SDK close() must not close an injected httpx client — caller owns lifecycle."""
    mock = httpx.AsyncClient(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, json={}))
    )
    client = AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key="test"),
        config=AsyncPublicApiClientConfiguration(base_url="https://example.test"),
        http_client=mock,
    )

    await client.close()

    assert not mock.is_closed
    await mock.aclose()


@pytest.mark.asyncio
async def test_owned_http_client_is_closed_by_sdk() -> None:
    """When the SDK owns the httpx client (no injection), close() does close it."""
    client = AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key="test"),
        config=AsyncPublicApiClientConfiguration(base_url="https://example.test"),
    )
    inner = client.api_client._client

    await client.close()

    assert inner.is_closed


@pytest.mark.asyncio
async def test_default_construction_unchanged() -> None:
    """Backwards compat: callers that don't pass http_client see no change."""
    client = AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key="test"),
        config=AsyncPublicApiClientConfiguration(base_url="https://example.test"),
    )

    assert isinstance(client.api_client._client, httpx.AsyncClient)
    assert client.api_client._owns_http_client is True

    await client.close()
