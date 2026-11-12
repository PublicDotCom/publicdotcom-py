"""Async account stream: order and trade events over a WebSocket, as an async iterator."""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Awaitable, Callable, List, Optional, Tuple, Union

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus

from .exceptions import StreamError
from .models.stream import (
    StreamConnectedEvent,
    StreamDisconnectedEvent,
    StreamEvent,
)
from .stream_common import (
    DEFAULT_CLOSE_TIMEOUT,
    DEFAULT_MAX_RECONNECT_DELAY,
    DEFAULT_MIN_RECONNECT_DELAY,
    DEFAULT_OPEN_TIMEOUT,
    DEFAULT_PING_INTERVAL,
    PING_MESSAGE,
    FrameKind,
    FrameParser,
    ReconnectPolicy,
    build_headers,
    build_stream_url,
    handshake_error,
    user_agent,
)

logger = logging.getLogger(__name__)

AsyncTokenProvider = Callable[[bool], Awaitable[str]]
"""Returns an access token; the argument asks for a new one (after a 401)."""


class _End:
    """Queue marker: the stream stopped, optionally with an error."""

    def __init__(self, error: Optional[Exception] = None) -> None:
        self.error = error


class AsyncAccountStream:
    """Order and trade events of one or more accounts, pushed over a WebSocket.

    Create one with :meth:`AsyncPublicApiClient.stream` and iterate it. The
    connection runs as an asyncio task in your event loop; it sends a
    heartbeat every ``ping_interval`` seconds and reconnects on its own, with
    backoff, whenever the connection closes.

    Besides :class:`OrderUpdateEvent` and :class:`TradeEvent` the iterator
    yields a :class:`StreamConnectedEvent` on the first connect and after
    every reconnect, and a :class:`StreamDisconnectedEvent` when a connection
    ends. Nothing is replayed after a reconnect, so load the current state
    from the REST API when you see a ``StreamConnectedEvent``; events that
    arrive meanwhile are queued and come next.

    Example::

        async with client.stream() as stream:
            async for event in stream:
                if isinstance(event, StreamConnectedEvent):
                    portfolio = await client.get_portfolio()
                elif isinstance(event, OrderUpdateEvent):
                    print(event.order.order_id, event.order.status)

    Iteration ends after :meth:`close`, and raises :class:`StreamError` when
    the stream gives up (a fatal handshake status, or
    ``max_reconnect_attempts`` exhausted).
    """

    def __init__(
        self,
        *,
        base_url: str,
        account_ids: List[str],
        channels: List[str],
        token_provider: AsyncTokenProvider,
        ping_interval: float = DEFAULT_PING_INTERVAL,
        max_reconnect_attempts: Optional[int] = None,
        min_reconnect_delay: float = DEFAULT_MIN_RECONNECT_DELAY,
        max_reconnect_delay: float = DEFAULT_MAX_RECONNECT_DELAY,
        deduplicate: bool = True,
        open_timeout: float = DEFAULT_OPEN_TIMEOUT,
    ) -> None:
        if ping_interval <= 0:
            raise ValueError("ping_interval must be positive")
        self.account_ids = list(account_ids)
        self.channels = list(channels)
        self.url = build_stream_url(base_url, self.account_ids, self.channels)
        self.ping_interval = ping_interval
        self.open_timeout = open_timeout

        self._token_provider = token_provider
        self._parser = FrameParser(deduplicate=deduplicate)
        self._policy = ReconnectPolicy(
            min_delay=min_reconnect_delay,
            max_delay=max_reconnect_delay,
            max_attempts=max_reconnect_attempts,
        )

        # created in start() so they bind to the running loop (Python 3.9)
        self._queue: Optional["asyncio.Queue[Union[StreamEvent, _End]]"] = None
        self._closing: Optional[asyncio.Event] = None
        self._task: Optional["asyncio.Task[None]"] = None
        self._ws: Optional[ClientConnection] = None
        self._connect_count = 0
        self._error: Optional[Exception] = None
        self._finished = False
        self._last_received = 0.0

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    async def start(self) -> "AsyncAccountStream":
        """Start the connection task. Iterating or ``async with`` does this."""
        if self._task is None:
            if self._finished:
                raise RuntimeError("a closed stream cannot be restarted")
            self._queue = asyncio.Queue()
            self._closing = asyncio.Event()
            self._task = asyncio.ensure_future(self._run())
        return self

    async def close(self) -> None:
        """Close the connection (freeing the account's connection slot) and
        stop the task. Safe to call more than once."""
        self._finished = True
        if self._task is None:
            return
        assert self._closing is not None
        self._closing.set()
        ws = self._ws
        if ws is not None:
            try:
                await ws.close()
            except Exception:  # pylint: disable=broad-except
                logger.debug("Error closing the stream connection", exc_info=True)
        if self._task is not asyncio.current_task() and not self._task.done():
            try:
                await asyncio.wait_for(
                    asyncio.shield(self._task), DEFAULT_CLOSE_TIMEOUT * 2
                )
            except asyncio.TimeoutError:
                self._task.cancel()

    async def __aenter__(self) -> "AsyncAccountStream":
        return await self.start()

    async def __aexit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        await self.close()

    def __aiter__(self) -> "AsyncAccountStream":
        return self

    async def __anext__(self) -> StreamEvent:
        await self.start()
        assert self._queue is not None
        item = await self._queue.get()
        if isinstance(item, _End):
            # keep the marker for anyone iterating again
            self._queue.put_nowait(_End())
            if item.error is not None:
                raise item.error
            raise StopAsyncIteration
        return item

    @property
    def is_running(self) -> bool:
        return self._task is not None and not self._task.done()

    @property
    def is_connected(self) -> bool:
        return self._ws is not None

    @property
    def error(self) -> Optional[Exception]:
        """The error that stopped the stream, if one did."""
        return self._error

    # ------------------------------------------------------------------ #
    # Connection loop                                                      #
    # ------------------------------------------------------------------ #

    async def _run(self) -> None:
        error: Optional[Exception] = None
        try:
            error = await self._run_loop()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Account stream stopped by an unexpected error")
            error = StreamError(f"Account stream stopped: {exc}")
        finally:
            self._ws = None
            self._finished = True
            if error is not None:
                self._error = error
                logger.error("Account stream stopped: %s", error)
            assert self._queue is not None
            self._queue.put_nowait(_End(error))

    async def _run_loop(self) -> Optional[Exception]:
        assert self._closing is not None
        while not self._closing.is_set():
            close_code: Optional[int] = None
            reason = ""
            status_code: Optional[int] = None

            try:
                token = await self._token_provider(self._policy.force_token_refresh)
            except Exception as exc:  # pylint: disable=broad-except
                return StreamError(f"Could not get an access token: {exc}")

            try:
                async with connect(
                    self.url,
                    additional_headers=build_headers(token),
                    user_agent_header=user_agent(),
                    open_timeout=self.open_timeout,
                    close_timeout=DEFAULT_CLOSE_TIMEOUT,
                    # the API wants its own JSON heartbeat, not protocol pings
                    ping_interval=None,
                ) as ws:
                    close_code, reason = await self._serve(ws)
            except InvalidStatus as exc:
                error = handshake_error(exc.response.status_code, exc.response.body)
                status_code = error.status_code
                reason = error.message
                fatal = self._policy.rejected(error)
                if fatal is not None:
                    self._emit_disconnect(None, reason, status_code, None)
                    return fatal
            except (
                OSError,
                asyncio.TimeoutError,
                TimeoutError,
                InvalidHandshake,
                ConnectionClosed,
            ) as exc:
                reason = f"{type(exc).__name__}: {exc}"

            if self._closing.is_set():
                return None
            delay = self._policy.next_delay()
            self._emit_disconnect(close_code, reason, status_code, delay)
            if delay is None:
                return StreamError(
                    f"Gave up after {self._policy.max_attempts} reconnect attempts: "
                    f"{reason}",
                    status_code=status_code,
                )
            logger.info("Account stream reconnecting in %.1fs (%s)", delay, reason)
            try:
                await asyncio.wait_for(self._closing.wait(), delay)
            except asyncio.TimeoutError:
                pass
        return None

    async def _serve(self, ws: ClientConnection) -> Tuple[Optional[int], str]:
        """Run one open connection until it closes."""
        assert self._closing is not None and self._queue is not None
        if self._closing.is_set():
            await ws.close()
            return ws.close_code, ws.close_reason or ""
        self._ws = ws
        opened_at = time.monotonic()
        self._last_received = opened_at
        self._policy.connected()

        heartbeat = asyncio.ensure_future(self._heartbeat(ws))
        try:
            self._queue.put_nowait(
                StreamConnectedEvent(
                    account_ids=self.account_ids,
                    channels=self.channels,
                    is_reconnect=self._connect_count > 0,
                    connected_at=datetime.now(timezone.utc),
                )
            )
            self._connect_count += 1
            async for raw in ws:
                self._last_received = time.monotonic()
                kind, event = self._parser.parse(raw)
                if kind is FrameKind.EVENT and event is not None:
                    self._queue.put_nowait(event)
        except ConnectionClosed:
            pass
        finally:
            heartbeat.cancel()
            self._ws = None
            self._policy.connection_ended(time.monotonic() - opened_at)
        return ws.close_code, ws.close_reason or ""

    async def _heartbeat(self, ws: ClientConnection) -> None:
        """Send a ping every ``ping_interval`` seconds; drop a dead connection."""
        try:
            while True:
                await asyncio.sleep(self.ping_interval)
                silent_for = time.monotonic() - self._last_received
                if silent_for > 2 * self.ping_interval:
                    logger.warning(
                        "No frame for %.0fs despite heartbeats; reconnecting",
                        silent_for,
                    )
                    await ws.close(code=1011, reason="heartbeat timeout")
                    return
                await ws.send(PING_MESSAGE)
        except ConnectionClosed:
            return

    def _emit_disconnect(
        self,
        close_code: Optional[int],
        reason: str,
        status_code: Optional[int],
        reconnect_in: Optional[float],
    ) -> None:
        assert self._queue is not None
        self._queue.put_nowait(
            StreamDisconnectedEvent(
                close_code=close_code,
                reason=reason,
                status_code=status_code,
                will_reconnect=reconnect_in is not None,
                reconnect_in=reconnect_in,
            )
        )

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else (
            "running" if self.is_running else "stopped"
        )
        return (
            f"AsyncAccountStream(accounts={self.account_ids}, "
            f"channels={self.channels}, {state})"
        )
