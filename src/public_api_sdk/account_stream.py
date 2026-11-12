"""Sync account stream: order and trade events over a WebSocket, on a thread."""

import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, List, Optional, Tuple, TypeVar

from websockets.exceptions import ConnectionClosed, InvalidHandshake, InvalidStatus
from websockets.sync.client import connect
from websockets.sync.connection import Connection

from .exceptions import StreamError
from .models.stream import (
    OrderUpdateEvent,
    StreamConnectedEvent,
    StreamDisconnectedEvent,
    TradeEvent,
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

_T = TypeVar("_T")

OrderCallback = Callable[[OrderUpdateEvent], None]
TradeCallback = Callable[[TradeEvent], None]
ConnectCallback = Callable[[StreamConnectedEvent], None]
DisconnectCallback = Callable[[StreamDisconnectedEvent], None]
ErrorCallback = Callable[[Exception], None]
SyncTokenProvider = Callable[[bool], str]
"""Returns an access token; the argument asks for a new one (after a 401)."""


class AccountStream:
    """Order and trade events of one or more accounts, pushed over a WebSocket.

    Create one with :meth:`PublicApiClient.stream`. The stream runs on a
    background thread and calls your callbacks from that thread. It sends a
    heartbeat every ``ping_interval`` seconds and reconnects on its own, with
    backoff, whenever the connection closes (the server closes connections
    after 10 idle minutes and after 2 hours at the latest).

    Delivery is at-most-once and nothing is replayed after a reconnect. Use
    ``on_connect`` to load the current state from the REST API: it is called
    on the first connect and after every reconnect, before the events of that
    connection are delivered, so events that arrive while you load are
    delivered after it returns.

    Example::

        def on_order(event):
            print(event.order.order_id, event.order.status)

        stream = client.stream(on_order=on_order)
        ...
        stream.close()
    """

    def __init__(
        self,
        *,
        base_url: str,
        account_ids: List[str],
        channels: List[str],
        token_provider: SyncTokenProvider,
        on_order: Optional[OrderCallback] = None,
        on_trade: Optional[TradeCallback] = None,
        on_connect: Optional[ConnectCallback] = None,
        on_disconnect: Optional[DisconnectCallback] = None,
        on_error: Optional[ErrorCallback] = None,
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
        self._on_order = on_order
        self._on_trade = on_trade
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        self._on_error = on_error

        self._parser = FrameParser(deduplicate=deduplicate)
        self._policy = ReconnectPolicy(
            min_delay=min_reconnect_delay,
            max_delay=max_reconnect_delay,
            max_attempts=max_reconnect_attempts,
        )

        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._done = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._ws: Optional[Connection] = None
        self._connect_count = 0
        self._error: Optional[Exception] = None
        # monotonic time of the last frame received; None while a callback runs
        self._last_received = 0.0
        self._in_callback = False

    # ------------------------------------------------------------------ #
    # Lifecycle                                                            #
    # ------------------------------------------------------------------ #

    def start(self) -> "AccountStream":
        """Start the background thread. Called by ``client.stream()``."""
        with self._lock:
            if self._stop.is_set():
                raise RuntimeError("a closed stream cannot be restarted")
            if self._thread is not None:
                return self
            self._thread = threading.Thread(
                target=self._run, name="public-account-stream", daemon=True
            )
            self._thread.start()
        return self

    def close(self, timeout: Optional[float] = 10.0) -> None:
        """Close the connection (freeing the account's connection slot) and
        stop the thread. Safe to call more than once and from a callback."""
        self._stop.set()
        with self._lock:
            ws = self._ws
            thread = self._thread
        if ws is not None:
            try:
                ws.close()
            except Exception:  # pylint: disable=broad-except
                logger.debug("Error closing the stream connection", exc_info=True)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        if thread is None:
            self._done.set()

    def wait(self, timeout: Optional[float] = None) -> bool:
        """Block until the stream stops. Returns False on timeout.

        Raises the error that stopped the stream, if one did.
        """
        if not self._done.wait(timeout):
            return False
        if self._error is not None:
            raise self._error
        return True

    def __enter__(self) -> "AccountStream":
        return self.start()

    def __exit__(self, exc_type: object, exc_val: object, exc_tb: object) -> None:
        self.close()

    @property
    def is_running(self) -> bool:
        """True from ``start()`` until the stream stops."""
        return self._thread is not None and not self._done.is_set()

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

    def _run(self) -> None:
        try:
            self._run_loop()
        except Exception as exc:  # pylint: disable=broad-except
            logger.exception("Account stream stopped by an unexpected error")
            self._fail(StreamError(f"Account stream stopped: {exc}"))
        finally:
            with self._lock:
                self._ws = None
            self._done.set()

    def _run_loop(self) -> None:
        while not self._stop.is_set():
            close_code: Optional[int] = None
            reason = ""
            status_code: Optional[int] = None

            try:
                token = self._token_provider(self._policy.force_token_refresh)
            except Exception as exc:  # pylint: disable=broad-except
                self._fail(StreamError(f"Could not get an access token: {exc}"))
                return

            try:
                with connect(
                    self.url,
                    additional_headers=build_headers(token),
                    user_agent_header=user_agent(),
                    open_timeout=self.open_timeout,
                    close_timeout=DEFAULT_CLOSE_TIMEOUT,
                    # the API wants its own JSON heartbeat, not protocol pings
                    ping_interval=None,
                ) as ws:
                    close_code, reason = self._serve(ws)
            except InvalidStatus as exc:
                error = handshake_error(exc.response.status_code, exc.response.body)
                status_code = error.status_code
                reason = error.message
                fatal = self._policy.rejected(error)
                if fatal is not None:
                    self._emit_disconnect(None, reason, status_code, None)
                    self._fail(fatal)
                    return
            except (OSError, TimeoutError, InvalidHandshake, ConnectionClosed) as exc:
                reason = f"{type(exc).__name__}: {exc}"

            if self._stop.is_set():
                return
            delay = self._policy.next_delay()
            self._emit_disconnect(close_code, reason, status_code, delay)
            if delay is None:
                attempts = self._policy.max_attempts
                self._fail(
                    StreamError(
                        f"Gave up after {attempts} reconnect attempts: {reason}",
                        status_code=status_code,
                    )
                )
                return
            logger.info("Account stream reconnecting in %.1fs (%s)", delay, reason)
            self._stop.wait(delay)

    def _serve(self, ws: Connection) -> Tuple[Optional[int], str]:
        """Run one open connection until it closes."""
        with self._lock:
            if self._stop.is_set():
                ws.close()
                return ws.close_code, ws.close_reason or ""
            self._ws = ws
        opened_at = time.monotonic()
        self._last_received = opened_at
        self._policy.connected()

        stop_heartbeat = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat,
            args=(ws, stop_heartbeat),
            name="public-account-stream-heartbeat",
            daemon=True,
        )
        heartbeat.start()
        try:
            self._emit_connect()
            for raw in ws:
                self._last_received = time.monotonic()
                kind, event = self._parser.parse(raw)
                if kind is FrameKind.EVENT and event is not None:
                    self._dispatch(event)
        except ConnectionClosed:
            pass
        finally:
            stop_heartbeat.set()
            with self._lock:
                self._ws = None
            self._policy.connection_ended(time.monotonic() - opened_at)
        return ws.close_code, ws.close_reason or ""

    def _heartbeat(self, ws: Connection, stop: threading.Event) -> None:
        """Send a ping every ``ping_interval`` seconds; drop a dead connection."""
        while not stop.wait(self.ping_interval):
            silent_for = time.monotonic() - self._last_received
            if not self._in_callback and silent_for > 2 * self.ping_interval:
                logger.warning(
                    "No frame for %.0fs despite heartbeats; reconnecting", silent_for
                )
                try:
                    ws.close(code=1011, reason="heartbeat timeout")
                except Exception:  # pylint: disable=broad-except
                    pass
                return
            try:
                ws.send(PING_MESSAGE)
            except ConnectionClosed:
                return

    # ------------------------------------------------------------------ #
    # Callbacks                                                            #
    # ------------------------------------------------------------------ #

    def _dispatch(self, event: Any) -> None:
        if isinstance(event, OrderUpdateEvent):
            self._call(self._on_order, event)
        elif isinstance(event, TradeEvent):
            self._call(self._on_trade, event)

    def _emit_connect(self) -> None:
        event = StreamConnectedEvent(
            account_ids=self.account_ids,
            channels=self.channels,
            is_reconnect=self._connect_count > 0,
            connected_at=datetime.now(timezone.utc),
        )
        self._connect_count += 1
        self._call(self._on_connect, event)

    def _emit_disconnect(
        self,
        close_code: Optional[int],
        reason: str,
        status_code: Optional[int],
        reconnect_in: Optional[float],
    ) -> None:
        self._call(
            self._on_disconnect,
            StreamDisconnectedEvent(
                close_code=close_code,
                reason=reason,
                status_code=status_code,
                will_reconnect=reconnect_in is not None,
                reconnect_in=reconnect_in,
            ),
        )

    def _fail(self, error: Exception) -> None:
        self._error = error
        logger.error("Account stream stopped: %s", error)
        self._call(self._on_error, error)

    def _call(self, callback: Optional[Callable[[_T], None]], arg: _T) -> None:
        if callback is None:
            return
        self._in_callback = True
        try:
            callback(arg)
        except Exception:  # pylint: disable=broad-except
            logger.exception("Error in account stream callback")
        finally:
            self._in_callback = False
            # time spent in a callback is not silence of the connection
            self._last_received = time.monotonic()

    def __repr__(self) -> str:
        state = "connected" if self.is_connected else (
            "running" if self.is_running else "stopped"
        )
        return (
            f"AccountStream(accounts={self.account_ids}, "
            f"channels={self.channels}, {state})"
        )
