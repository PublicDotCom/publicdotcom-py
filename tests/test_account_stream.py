"""Integration tests for AccountStream (sync) and AsyncAccountStream (async).

The streams talk to a real WebSocket server on localhost that plays the part
of the gateway: it can reject handshakes with an HTTP status, push scripted
frames, close connections, and answers pings with PONG.
"""

import asyncio
import json
import queue
import threading
import time
from typing import Any, Callable, Iterator, List, Optional, Union
from unittest.mock import Mock, patch

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import Server, ServerConnection, serve

from public_api_sdk import (
    AccountStream,
    ApiKeyAuthConfig,
    AsyncAccountStream,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    OrderUpdateEvent,
    PublicApiClient,
    PublicApiClientConfiguration,
    StreamChannel,
    StreamConnectedEvent,
    StreamDisconnectedEvent,
    StreamError,
    StreamHandshakeError,
    TradeEvent,
)
from public_api_sdk.async_auth_provider import AsyncApiKeyAuthProvider
from public_api_sdk.auth_provider import ApiKeyAuthProvider

from .test_stream_common import order_frame, trade_frame

CLOSE = "<close>"
PING = '{"action":"ping"}'
TIMEOUT = 5.0

Step = Union[str, float]


class FakeGateway:
    """A WebSocket server standing in for the userapigateway stream."""

    def __init__(self) -> None:
        self.reject: List[Optional[int]] = []  # status per handshake, None accepts
        self.scripts: List[List[Step]] = []  # steps per accepted connection
        self.paths: List[str] = []
        self.auth_headers: List[Optional[str]] = []
        self.received: "queue.Queue[str]" = queue.Queue()
        self.close_codes: "queue.Queue[Optional[int]]" = queue.Queue()
        self._server: Optional[Server] = None
        self._thread: Optional[threading.Thread] = None
        self.base_url = ""

    def _process_request(self, connection: ServerConnection, request: Any) -> Any:
        self.paths.append(request.path)
        self.auth_headers.append(request.headers.get("Authorization"))
        status = self.reject.pop(0) if self.reject else None
        if status is not None:
            return connection.respond(status, f"rejected with {status}\n")
        return None

    def _handler(self, ws: ServerConnection) -> None:
        script = self.scripts.pop(0) if self.scripts else []
        try:
            for step in script:
                if step == CLOSE:
                    ws.close()
                    return
                if isinstance(step, float):
                    time.sleep(step)
                    continue
                ws.send(step)
            for message in ws:
                assert isinstance(message, str)
                self.received.put(message)
                if json.loads(message).get("action") == "ping":
                    ws.send('{"type":"PONG"}')
        except ConnectionClosed:
            pass
        finally:
            self.close_codes.put(ws.close_code)

    def __enter__(self) -> "FakeGateway":
        self._server = serve(
            self._handler, "127.0.0.1", 0, process_request=self._process_request
        )
        port = self._server.socket.getsockname()[1]
        self.base_url = f"http://127.0.0.1:{port}"
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        assert self._server is not None and self._thread is not None
        self._server.shutdown()
        self._thread.join(TIMEOUT)


@pytest.fixture
def gateway() -> Iterator[FakeGateway]:
    with FakeGateway() as gw:
        yield gw


def get(q: "queue.Queue[Any]", timeout: float = TIMEOUT) -> Any:
    return q.get(timeout=timeout)


def wait_until(predicate: Callable[[], bool], timeout: float = TIMEOUT) -> None:
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > deadline:
            raise AssertionError("condition not met in time")
        time.sleep(0.01)


# --------------------------------------------------------------------------- #
# Sync stream                                                                  #
# --------------------------------------------------------------------------- #


class Recorder:
    """Collects everything a sync stream reports, in order."""

    def __init__(self) -> None:
        self.events: "queue.Queue[Any]" = queue.Queue()
        self.errors: "queue.Queue[Exception]" = queue.Queue()

    def callbacks(self) -> Any:
        return {
            "on_order": self.events.put,
            "on_trade": self.events.put,
            "on_connect": self.events.put,
            "on_disconnect": self.events.put,
            "on_error": self.errors.put,
        }


def make_sync_stream(
    gw: FakeGateway,
    recorder: Optional[Recorder] = None,
    token_provider: Optional[Callable[[bool], str]] = None,
    **kwargs: Any,
) -> AccountStream:
    options: Any = {
        "base_url": gw.base_url,
        "account_ids": ["5RE12345"],
        "channels": ["order", "trade"],
        "token_provider": token_provider or (lambda force: "tok"),
        "min_reconnect_delay": 0.01,
        "max_reconnect_delay": 0.05,
        "open_timeout": 2.0,
    }
    if recorder is not None:
        options.update(recorder.callbacks())
    options.update(kwargs)
    return AccountStream(**options)


class TestSyncStream:
    def test_connects_and_delivers_order_and_trade_events(self, gateway: FakeGateway) -> None:
        gateway.scripts = [[order_frame(), trade_frame()]]
        rec = Recorder()
        stream = make_sync_stream(gateway, rec).start()
        try:
            connected = get(rec.events)
            assert isinstance(connected, StreamConnectedEvent)
            assert not connected.is_reconnect
            assert connected.account_ids == ["5RE12345"]
            order_event = get(rec.events)
            assert isinstance(order_event, OrderUpdateEvent)
            assert order_event.order.version == 1
            trade_event = get(rec.events)
            assert isinstance(trade_event, TradeEvent)
            assert trade_event.trade.trade_id == "T-1"
            assert stream.is_connected and stream.is_running
        finally:
            stream.close()

        assert gateway.paths == ["/userapigateway?accountIds=5RE12345&channels=order,trade"]
        assert gateway.auth_headers == ["Bearer tok"]
        # a normal close frame frees the account's connection slot right away
        assert get(gateway.close_codes) == 1000
        assert not stream.is_running
        assert stream.wait(0) is True
        assert rec.errors.empty()

    def test_sends_heartbeat_pings(self, gateway: FakeGateway) -> None:
        stream = make_sync_stream(gateway, ping_interval=0.05).start()
        try:
            assert get(gateway.received) == PING
            assert get(gateway.received) == PING
        finally:
            stream.close()
        assert stream.error is None

    def test_reconnects_and_drops_replayed_versions(self, gateway: FakeGateway) -> None:
        gateway.scripts = [
            [order_frame(version=1), CLOSE],
            [order_frame(version=1), order_frame(version=2)],
        ]
        rec = Recorder()
        stream = make_sync_stream(gateway, rec).start()
        try:
            kinds = [get(rec.events) for _ in range(5)]
        finally:
            stream.close()
        assert isinstance(kinds[0], StreamConnectedEvent) and not kinds[0].is_reconnect
        assert isinstance(kinds[1], OrderUpdateEvent) and kinds[1].order.version == 1
        assert isinstance(kinds[2], StreamDisconnectedEvent)
        assert kinds[2].will_reconnect and kinds[2].close_code == 1000
        assert isinstance(kinds[3], StreamConnectedEvent) and kinds[3].is_reconnect
        # the replayed version 1 was dropped
        assert isinstance(kinds[4], OrderUpdateEvent) and kinds[4].order.version == 2
        assert rec.events.empty()

    def test_events_wait_for_on_connect(self, gateway: FakeGateway) -> None:
        """Loading REST state in on_connect does not lose or reorder events."""
        gateway.scripts = [[order_frame(version=1), order_frame(version=2)]]
        seen: "queue.Queue[str]" = queue.Queue()

        def on_connect(event: StreamConnectedEvent) -> None:
            time.sleep(0.3)  # e.g. client.get_portfolio()
            seen.put("connect")

        stream = make_sync_stream(
            gateway,
            on_connect=on_connect,
            on_order=lambda e: seen.put(f"order v{e.order.version}"),
        ).start()
        try:
            assert [get(seen) for _ in range(3)] == ["connect", "order v1", "order v2"]
        finally:
            stream.close()

    @pytest.mark.parametrize("status", [400, 403])
    def test_fatal_handshake_status_stops_the_stream(
        self, gateway: FakeGateway, status: int
    ) -> None:
        gateway.reject = [status]
        rec = Recorder()
        stream = make_sync_stream(gateway, rec).start()
        error = get(rec.errors)
        assert isinstance(error, StreamHandshakeError)
        assert error.status_code == status
        assert error.message == f"rejected with {status}"
        disconnected = get(rec.events)
        assert isinstance(disconnected, StreamDisconnectedEvent)
        assert not disconnected.will_reconnect and disconnected.status_code == status
        with pytest.raises(StreamHandshakeError):
            stream.wait(TIMEOUT)
        assert stream.error is error
        assert len(gateway.paths) == 1

    def test_401_retries_once_with_a_fresh_token(self, gateway: FakeGateway) -> None:
        gateway.reject = [401]
        calls: List[bool] = []

        def token_provider(force: bool) -> str:
            calls.append(force)
            return "fresh" if force else "stale"

        rec = Recorder()
        stream = make_sync_stream(gateway, rec, token_provider=token_provider).start()
        try:
            assert isinstance(get(rec.events), StreamDisconnectedEvent)
            assert isinstance(get(rec.events), StreamConnectedEvent)
        finally:
            stream.close()
        assert calls == [False, True]
        assert gateway.auth_headers == ["Bearer stale", "Bearer fresh"]

    def test_401_twice_is_fatal(self, gateway: FakeGateway) -> None:
        gateway.reject = [401, 401]
        rec = Recorder()
        stream = make_sync_stream(gateway, rec).start()
        error = get(rec.errors)
        assert isinstance(error, StreamHandshakeError) and error.status_code == 401
        stream.close()

    def test_429_and_503_are_retried(self, gateway: FakeGateway) -> None:
        gateway.reject = [429, 503]
        rec = Recorder()
        stream = make_sync_stream(gateway, rec).start()
        try:
            first, second = get(rec.events), get(rec.events)
            assert isinstance(first, StreamDisconnectedEvent) and first.status_code == 429
            assert isinstance(second, StreamDisconnectedEvent) and second.status_code == 503
            assert first.will_reconnect and first.reconnect_in is not None
            assert isinstance(get(rec.events), StreamConnectedEvent)
        finally:
            stream.close()

    def test_gives_up_after_max_reconnect_attempts(self, gateway: FakeGateway) -> None:
        gateway.reject = [503, 503, 503]
        rec = Recorder()
        stream = make_sync_stream(gateway, rec, max_reconnect_attempts=2).start()
        error = get(rec.errors)
        assert type(error) is StreamError
        assert error.status_code == 503
        assert "Gave up after 2" in error.message
        assert len(gateway.paths) == 3
        stream.close()

    def test_unreachable_server_is_retried(self) -> None:
        with FakeGateway() as gw:
            base_url = gw.base_url
        rec = Recorder()
        stream = AccountStream(
            base_url=base_url,  # nothing listens there any more
            account_ids=["5RE12345"],
            channels=["order"],
            token_provider=lambda force: "tok",
            min_reconnect_delay=0.01,
            max_reconnect_delay=0.01,
            max_reconnect_attempts=1,
            **rec.callbacks(),
        ).start()
        error = get(rec.errors)
        assert isinstance(error, StreamError)
        disconnected = get(rec.events)
        assert isinstance(disconnected, StreamDisconnectedEvent)
        assert disconnected.will_reconnect
        stream.close()

    def test_token_error_stops_the_stream(self, gateway: FakeGateway) -> None:
        def token_provider(force: bool) -> str:
            raise ValueError("No valid access token available")

        rec = Recorder()
        stream = make_sync_stream(gateway, rec, token_provider=token_provider).start()
        error = get(rec.errors)
        assert isinstance(error, StreamError)
        assert "access token" in error.message
        assert gateway.paths == []
        stream.close()

    def test_callback_errors_do_not_stop_the_stream(self, gateway: FakeGateway) -> None:
        gateway.scripts = [[order_frame(version=1), order_frame(version=2)]]
        delivered: "queue.Queue[int]" = queue.Queue()

        def on_order(event: OrderUpdateEvent) -> None:
            delivered.put(event.order.version)
            if event.order.version == 1:
                raise RuntimeError("bug in user code")

        stream = make_sync_stream(gateway, on_order=on_order).start()
        try:
            assert [get(delivered), get(delivered)] == [1, 2]
            assert stream.is_connected
        finally:
            stream.close()

    def test_close_from_a_callback(self, gateway: FakeGateway) -> None:
        gateway.scripts = [[order_frame()]]
        holder: List[AccountStream] = []
        stream = make_sync_stream(gateway, on_order=lambda e: holder[0].close())
        holder.append(stream)
        stream.start()
        assert stream.wait(TIMEOUT) is True
        assert not stream.is_running

    def test_context_manager_and_no_restart(self, gateway: FakeGateway) -> None:
        rec = Recorder()
        with make_sync_stream(gateway, rec) as stream:
            assert isinstance(get(rec.events), StreamConnectedEvent)
        assert not stream.is_running
        with pytest.raises(RuntimeError):
            stream.start()

    def test_close_before_start(self, gateway: FakeGateway) -> None:
        stream = make_sync_stream(gateway)
        stream.close()
        assert stream.wait(0) is True
        assert gateway.paths == []

    def test_rejects_non_positive_ping_interval(self, gateway: FakeGateway) -> None:
        with pytest.raises(ValueError):
            make_sync_stream(gateway, ping_interval=0)


# --------------------------------------------------------------------------- #
# Async stream                                                                 #
# --------------------------------------------------------------------------- #


def make_async_stream(
    gw: FakeGateway,
    token_provider: Optional[Callable[[bool], Any]] = None,
    **kwargs: Any,
) -> AsyncAccountStream:
    async def default_token(force: bool) -> str:
        return "tok"

    options: Any = {
        "base_url": gw.base_url,
        "account_ids": ["5RE12345"],
        "channels": ["order", "trade"],
        "token_provider": token_provider or default_token,
        "min_reconnect_delay": 0.01,
        "max_reconnect_delay": 0.05,
        "open_timeout": 2.0,
    }
    options.update(kwargs)
    return AsyncAccountStream(**options)


async def next_event(stream: AsyncAccountStream) -> Any:
    return await asyncio.wait_for(stream.__anext__(), TIMEOUT)


class TestAsyncStream:
    @pytest.mark.asyncio
    async def test_yields_connect_order_and_trade_events(self, gateway: FakeGateway) -> None:
        gateway.scripts = [[order_frame(), trade_frame()]]
        async with make_async_stream(gateway) as stream:
            connected = await next_event(stream)
            assert isinstance(connected, StreamConnectedEvent)
            assert not connected.is_reconnect
            assert isinstance(await next_event(stream), OrderUpdateEvent)
            assert isinstance(await next_event(stream), TradeEvent)
            assert stream.is_connected
        assert not stream.is_running
        assert gateway.paths == ["/userapigateway?accountIds=5RE12345&channels=order,trade"]
        assert gateway.auth_headers == ["Bearer tok"]
        assert await asyncio.to_thread(get, gateway.close_codes) == 1000

    @pytest.mark.asyncio
    async def test_iteration_ends_after_close(self, gateway: FakeGateway) -> None:
        gateway.scripts = [[order_frame()]]
        stream = make_async_stream(gateway)
        seen: List[Any] = []
        async for event in stream:
            seen.append(event)
            if isinstance(event, OrderUpdateEvent):
                await stream.close()
        assert [type(e) for e in seen] == [StreamConnectedEvent, OrderUpdateEvent]
        # iterating a finished stream stops right away
        with pytest.raises(StopAsyncIteration):
            await next_event(stream)

    @pytest.mark.asyncio
    async def test_sends_heartbeat_pings(self, gateway: FakeGateway) -> None:
        async with make_async_stream(gateway, ping_interval=0.05) as stream:
            assert await asyncio.to_thread(get, gateway.received) == PING
            assert await asyncio.to_thread(get, gateway.received) == PING
            assert isinstance(await next_event(stream), StreamConnectedEvent)
        assert stream.error is None

    @pytest.mark.asyncio
    async def test_reconnects_and_drops_replayed_versions(self, gateway: FakeGateway) -> None:
        gateway.scripts = [
            [order_frame(version=1), CLOSE],
            [order_frame(version=1), order_frame(version=2)],
        ]
        async with make_async_stream(gateway) as stream:
            events = [await next_event(stream) for _ in range(5)]
        assert isinstance(events[0], StreamConnectedEvent)
        assert isinstance(events[1], OrderUpdateEvent) and events[1].order.version == 1
        assert isinstance(events[2], StreamDisconnectedEvent) and events[2].will_reconnect
        assert isinstance(events[3], StreamConnectedEvent) and events[3].is_reconnect
        assert isinstance(events[4], OrderUpdateEvent) and events[4].order.version == 2

    @pytest.mark.asyncio
    async def test_events_are_queued_while_state_loads(self, gateway: FakeGateway) -> None:
        gateway.scripts = [[order_frame(version=1), order_frame(version=2)]]
        async with make_async_stream(gateway) as stream:
            assert isinstance(await next_event(stream), StreamConnectedEvent)
            await asyncio.sleep(0.3)  # e.g. await client.get_portfolio()
            first, second = await next_event(stream), await next_event(stream)
        assert (first.order.version, second.order.version) == (1, 2)

    @pytest.mark.asyncio
    async def test_fatal_handshake_raises_from_iteration(self, gateway: FakeGateway) -> None:
        gateway.reject = [403]
        stream = make_async_stream(gateway)
        disconnected = await next_event(stream)
        assert isinstance(disconnected, StreamDisconnectedEvent)
        assert not disconnected.will_reconnect
        with pytest.raises(StreamHandshakeError) as info:
            await next_event(stream)
        assert info.value.status_code == 403
        assert stream.error is info.value
        with pytest.raises(StopAsyncIteration):
            await next_event(stream)
        await stream.close()

    @pytest.mark.asyncio
    async def test_401_retries_once_with_a_fresh_token(self, gateway: FakeGateway) -> None:
        gateway.reject = [401]
        calls: List[bool] = []

        async def token_provider(force: bool) -> str:
            calls.append(force)
            return "fresh" if force else "stale"

        async with make_async_stream(gateway, token_provider=token_provider) as stream:
            assert isinstance(await next_event(stream), StreamDisconnectedEvent)
            assert isinstance(await next_event(stream), StreamConnectedEvent)
        assert calls == [False, True]
        assert gateway.auth_headers == ["Bearer stale", "Bearer fresh"]

    @pytest.mark.asyncio
    async def test_gives_up_after_max_reconnect_attempts(self, gateway: FakeGateway) -> None:
        gateway.reject = [429, 429]
        stream = make_async_stream(gateway, max_reconnect_attempts=1)
        assert isinstance(await next_event(stream), StreamDisconnectedEvent)
        assert isinstance(await next_event(stream), StreamDisconnectedEvent)
        with pytest.raises(StreamError, match="Gave up after 1"):
            await next_event(stream)
        await stream.close()

    @pytest.mark.asyncio
    async def test_token_error_stops_the_stream(self, gateway: FakeGateway) -> None:
        async def token_provider(force: bool) -> str:
            raise ValueError("No valid access token available")

        stream = make_async_stream(gateway, token_provider=token_provider)
        with pytest.raises(StreamError, match="access token"):
            await next_event(stream)
        await stream.close()

    @pytest.mark.asyncio
    async def test_close_before_start_is_a_no_op(self, gateway: FakeGateway) -> None:
        stream = make_async_stream(gateway)
        await stream.close()
        assert not stream.is_running
        with pytest.raises(RuntimeError):
            await stream.start()


# --------------------------------------------------------------------------- #
# Client wiring                                                                #
# --------------------------------------------------------------------------- #


def make_sync_client(base_url: str, default_account: Optional[str]) -> PublicApiClient:
    with patch("public_api_sdk.public_api_client.ApiClient"), patch(
        "public_api_sdk.public_api_client.AuthManager"
    ):
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="key"),
            config=PublicApiClientConfiguration(default_account_number=default_account),
        )
    client.api_client.base_url = base_url
    provider = Mock(spec=ApiKeyAuthProvider)
    provider.get_access_token.return_value = "rest-token"
    client.auth_manager.auth_provider = provider
    return client


def make_async_client(base_url: str, default_account: Optional[str]) -> AsyncPublicApiClient:
    with patch("public_api_sdk.async_public_api_client.AsyncApiClient"), patch(
        "public_api_sdk.async_public_api_client.AsyncAuthManager"
    ):
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="key"),
            config=AsyncPublicApiClientConfiguration(
                default_account_number=default_account
            ),
        )
    client.api_client.base_url = base_url
    client.api_client.aclose = Mock(side_effect=lambda: asyncio.sleep(0))
    provider = Mock(spec=AsyncApiKeyAuthProvider)
    provider.get_access_token = Mock(side_effect=lambda: asyncio.sleep(0, "rest-token"))
    provider._create_personal_access_token = Mock(side_effect=lambda: asyncio.sleep(0))
    client.auth_manager.auth_provider = provider
    return client


class TestClientWiring:
    def test_sync_client_stream_uses_rest_token_and_default_account(
        self, gateway: FakeGateway
    ) -> None:
        client = make_sync_client(gateway.base_url, "5RE12345")
        connected: "queue.Queue[StreamConnectedEvent]" = queue.Queue()
        stream = client.stream(channels=[StreamChannel.ORDER], on_connect=connected.put)
        assert isinstance(stream, AccountStream)
        assert get(connected).account_ids == ["5RE12345"]
        assert gateway.paths == ["/userapigateway?accountIds=5RE12345&channels=order"]
        assert gateway.auth_headers == ["Bearer rest-token"]
        # client.close() closes its streams
        client.close()
        assert not stream.is_running

    def test_sync_client_defaults_to_all_accounts_and_channels(
        self, gateway: FakeGateway
    ) -> None:
        client = make_sync_client(gateway.base_url, None)
        stream = client.stream(start=False)
        assert stream.account_ids == ["*"]
        assert stream.channels == ["order", "trade"]
        assert not stream.is_running
        client.close()

    def test_sync_client_refreshes_api_key_token_after_401(
        self, gateway: FakeGateway
    ) -> None:
        gateway.reject = [401]
        client = make_sync_client(gateway.base_url, "5RE12345")
        connected: "queue.Queue[StreamConnectedEvent]" = queue.Queue()
        stream = client.stream(on_connect=connected.put)
        try:
            get(connected)
        finally:
            stream.close()
        provider = client.auth_manager.auth_provider
        provider._create_personal_access_token.assert_called_once_with()  # type: ignore[attr-defined]
        client.close()

    @pytest.mark.asyncio
    async def test_async_client_stream(self, gateway: FakeGateway) -> None:
        gateway.reject = [401]
        client = make_async_client(gateway.base_url, None)
        stream = client.stream(accounts=["5RE1", "5RE2"])
        assert isinstance(stream, AsyncAccountStream)
        assert isinstance(await next_event(stream), StreamDisconnectedEvent)
        connected = await next_event(stream)
        assert isinstance(connected, StreamConnectedEvent)
        assert connected.account_ids == ["5RE1", "5RE2"]
        assert gateway.paths[-1] == "/userapigateway?accountIds=5RE1,5RE2&channels=order,trade"
        assert gateway.auth_headers == ["Bearer rest-token", "Bearer rest-token"]
        provider = client.auth_manager.auth_provider
        provider._create_personal_access_token.assert_called_once_with()  # type: ignore[attr-defined]
        await client.close()
        assert not stream.is_running
