"""Transport-independent pieces of the account stream.

Both :class:`~public_api_sdk.account_stream.AccountStream` (sync, thread) and
:class:`~public_api_sdk.async_account_stream.AsyncAccountStream` (asyncio)
use this module for the URL, the frame parsing and deduplication, and the
reconnect policy, so the two only differ in how they do I/O.
"""

import json
import logging
import random
from decimal import Decimal
from enum import Enum
from typing import (
    Callable,
    Dict,
    Iterable,
    List,
    Optional,
    Set,
    Tuple,
    Union,
)
from urllib.parse import quote, urlsplit, urlunsplit

from pydantic import ValidationError as PydanticValidationError

from .exceptions import StreamError, StreamHandshakeError
from .models.stream import OrderUpdateEvent, StreamChannel, TradeEvent

logger = logging.getLogger(__name__)

STREAM_PATH = "/userapigateway"
ALL_ACCOUNTS = "*"
PING_MESSAGE = '{"action":"ping"}'

DEFAULT_PING_INTERVAL = 60.0
"""Seconds between heartbeats. The server closes a connection idle for 10 minutes."""
DEFAULT_MIN_RECONNECT_DELAY = 1.0
DEFAULT_MAX_RECONNECT_DELAY = 30.0
DEFAULT_OPEN_TIMEOUT = 10.0
DEFAULT_CLOSE_TIMEOUT = 5.0

STABLE_CONNECTION_SECONDS = 60.0
"""A connection open at least this long resets the reconnect backoff."""

# Statuses that would fail the same way again: raise instead of retrying.
_FATAL_STATUSES = frozenset({400, 403})
_UNAUTHORIZED = 401

AccountsArg = Union[str, Iterable[str], None]
ChannelsArg = Optional[Iterable[Union[StreamChannel, str]]]
StreamDataEvent = Union[OrderUpdateEvent, TradeEvent]


def normalize_accounts(accounts: AccountsArg, default_account: Optional[str]) -> List[str]:
    """Turn the ``accounts`` argument into the list sent as ``accountIds``.

    ``None`` means the client's default account when one is configured, and
    all of the user's accounts (``*``) otherwise.
    """
    if accounts is None:
        return [default_account] if default_account else [ALL_ACCOUNTS]
    items = [accounts] if isinstance(accounts, str) else list(accounts)
    result: List[str] = []
    for item in items:
        if not isinstance(item, str):
            raise TypeError(f"account ids must be strings, got {type(item).__name__}")
        for part in item.split(","):
            part = part.strip()
            if part and part not in result:
                result.append(part)
    if not result:
        raise ValueError("accounts must name at least one account, or '*' for all")
    if ALL_ACCOUNTS in result and len(result) > 1:
        raise ValueError("'*' (all accounts) cannot be combined with account numbers")
    return result


def normalize_channels(channels: ChannelsArg) -> List[str]:
    """Turn the ``channels`` argument into the list sent as ``channels``.

    ``None`` subscribes to every channel the SDK knows (``order`` and
    ``trade``). Unknown channel names are passed through, so a channel added
    by the API can be used before the SDK knows it.
    """
    if channels is None:
        return [channel.value for channel in StreamChannel]
    if isinstance(channels, (str, StreamChannel)):
        channels = [channels]
    result: List[str] = []
    for channel in channels:
        value = channel.value if isinstance(channel, StreamChannel) else str(channel)
        value = value.strip().lower()
        if value and value not in result:
            result.append(value)
    if not result:
        raise ValueError("channels must name at least one channel")
    return result


def build_stream_url(base_url: str, account_ids: List[str], channels: List[str]) -> str:
    """Build the WebSocket URL from the REST base URL.

    ``https://api.public.com`` becomes
    ``wss://api.public.com/userapigateway?accountIds=...&channels=...``.
    """
    parts = urlsplit(base_url.rstrip("/"))
    scheme = {"https": "wss", "http": "ws"}.get(parts.scheme.lower(), parts.scheme)
    if scheme not in ("wss", "ws"):
        raise ValueError(f"cannot derive a WebSocket URL from base URL {base_url!r}")
    query = "accountIds={}&channels={}".format(
        quote(",".join(account_ids), safe=",*"),
        quote(",".join(channels), safe=","),
    )
    return urlunsplit((scheme, parts.netloc, parts.path + STREAM_PATH, query, ""))


def build_headers(token: str) -> Dict[str, str]:
    """Headers for the handshake. The token is never put in the URL."""
    return {
        "Authorization": f"Bearer {token}",
        "X-App-Version": f"public-python-api-sdk-{_sdk_version()}",
    }


def user_agent() -> str:
    return f"public-python-api-sdk-{_sdk_version()}"


def _sdk_version() -> str:
    try:
        from . import __version__  # pylint: disable=import-outside-toplevel

        return __version__
    except (ImportError, AttributeError):  # pragma: no cover
        return "unknown"


def handshake_error(status_code: int, body: bytes) -> StreamHandshakeError:
    """The error for a handshake rejected with an HTTP status.

    The body is a short plain-text message, not meant to be parsed.
    """
    text = body.decode("utf-8", errors="replace").strip() if body else ""
    message = text[:500] or f"WebSocket handshake rejected with HTTP {status_code}"
    return StreamHandshakeError(message, status_code=status_code)


class FrameKind(Enum):
    EVENT = "event"
    PONG = "pong"
    IGNORED = "ignored"


class FrameParser:
    """Parses frames into events and drops repeats.

    - Order events whose ``version`` is not higher than the last delivered
      version of that order are dropped. After a restart on the server side,
      events already sent can be sent again, including older versions.
    - Trade events repeating the last delivered status of a trade are dropped.
    - ``PONG``, unknown channels and unknown event types are ignored, as are
      frames that cannot be parsed (they are logged).

    The state survives reconnects, so a replay after a reconnect is dropped too.
    """

    def __init__(self, deduplicate: bool = True) -> None:
        self.deduplicate = deduplicate
        self._order_versions: Dict[str, int] = {}
        self._trade_statuses: Set[Tuple[str, str]] = set()

    def parse(self, raw: Union[str, bytes]) -> Tuple[FrameKind, Optional[StreamDataEvent]]:
        try:
            # Prices and quantities of orders are JSON numbers: keep them exact.
            frame = json.loads(raw, parse_float=Decimal)
        except (TypeError, ValueError):
            logger.warning("Ignoring a stream frame that is not JSON: %.200r", raw)
            return FrameKind.IGNORED, None
        if not isinstance(frame, dict):
            return FrameKind.IGNORED, None

        frame_type = frame.get("type")
        if frame_type == "PONG":
            return FrameKind.PONG, None

        channel = frame.get("channel")
        payload = frame.get("payload")
        if not isinstance(payload, dict):
            payload = {}
        try:
            if channel == StreamChannel.ORDER.value and frame_type == "ORDER_UPDATE":
                order_event = OrderUpdateEvent.model_validate(
                    {
                        "channel": channel,
                        "type": frame_type,
                        "timestamp": frame.get("timestamp"),
                        "order": payload.get("order"),
                    }
                )
                if self._is_new_order_version(order_event):
                    return FrameKind.EVENT, order_event
                return FrameKind.IGNORED, None
            if channel == StreamChannel.TRADE.value and frame_type == "TRADE":
                trade_event = TradeEvent.model_validate(
                    {
                        "channel": channel,
                        "type": frame_type,
                        "timestamp": frame.get("timestamp"),
                        "trade": payload,
                    }
                )
                if self._is_new_trade_status(trade_event):
                    return FrameKind.EVENT, trade_event
                return FrameKind.IGNORED, None
        except PydanticValidationError as exc:
            logger.warning(
                "Ignoring a %s/%s stream frame that could not be parsed: %s",
                channel,
                frame_type,
                exc,
            )
            return FrameKind.IGNORED, None

        logger.debug("Ignoring stream frame of channel %r and type %r", channel, frame_type)
        return FrameKind.IGNORED, None

    def _is_new_order_version(self, event: OrderUpdateEvent) -> bool:
        if not self.deduplicate:
            return True
        order = event.order
        last = self._order_versions.get(order.order_id)
        if last is not None and order.version <= last:
            logger.debug(
                "Dropping order %s version %s (already delivered version %s)",
                order.order_id,
                order.version,
                last,
            )
            return False
        self._order_versions[order.order_id] = order.version
        return True

    def _is_new_trade_status(self, event: TradeEvent) -> bool:
        if not self.deduplicate:
            return True
        key = (event.trade.trade_id, event.trade.status.value)
        if key in self._trade_statuses:
            logger.debug("Dropping repeated trade %s with status %s", *key)
            return False
        self._trade_statuses.add(key)
        return True


class ReconnectPolicy:
    """Decides whether and when to reconnect.

    - 400 and 403 are fatal: the same handshake would fail again.
    - 401 is retried once with a fresh token, then fatal.
    - 429, 5xx, network errors and closes of an open connection are retried
      with exponential backoff and jitter (by default 1, 2, 4 ... up to 30 s).
    - The backoff resets after a connection that stayed open for
      :data:`STABLE_CONNECTION_SECONDS`.
    - ``max_attempts`` caps the consecutive attempts that fail or end early;
      ``None`` retries forever.
    """

    def __init__(
        self,
        min_delay: float = DEFAULT_MIN_RECONNECT_DELAY,
        max_delay: float = DEFAULT_MAX_RECONNECT_DELAY,
        max_attempts: Optional[int] = None,
        rand: Callable[[], float] = random.random,
    ) -> None:
        if min_delay < 0 or max_delay < min_delay:
            raise ValueError("need 0 <= min_reconnect_delay <= max_reconnect_delay")
        if max_attempts is not None and max_attempts < 0:
            raise ValueError("max_reconnect_attempts must be >= 0 or None")
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_attempts = max_attempts
        self._rand = rand
        self.attempt = 0
        self._unauthorized = 0

    @property
    def force_token_refresh(self) -> bool:
        """True right after a 401: the next attempt should use a new token."""
        return self._unauthorized > 0

    def connected(self) -> None:
        self._unauthorized = 0

    def connection_ended(self, open_seconds: float) -> None:
        if open_seconds >= STABLE_CONNECTION_SECONDS:
            self.attempt = 0

    def rejected(self, error: StreamHandshakeError) -> Optional[StreamError]:
        """Record a rejected handshake; return the error if it is fatal."""
        status = error.status_code
        if status in _FATAL_STATUSES:
            return error
        if status == _UNAUTHORIZED:
            self._unauthorized += 1
            if self._unauthorized > 1:
                return error
        return None

    def next_delay(self) -> Optional[float]:
        """Seconds to wait before the next attempt, or None to give up."""
        if self.max_attempts is not None and self.attempt >= self.max_attempts:
            return None
        delay = min(self.max_delay, self.min_delay * (2.0 ** self.attempt))
        self.attempt += 1
        # jitter: between half and all of the delay
        return delay * (0.5 + self._rand() / 2)
