"""Stream order updates and trades over the account WebSocket, and time it.

By default this example only listens: it places no orders. Place or cancel an
order in the Public app (or with another example) while it runs to see events
arrive. Set ROUNDTRIP_SYMBOL to have it place an order itself and time the
full round trip.

Environment:
    API_SECRET_KEY           required
    DEFAULT_ACCOUNT_NUMBER   optional; without it every account is streamed
                             (required for the round trip)
    STREAM_SECONDS           optional; how long to run (default 120)
    STREAM_MODE              "sync" (default) or "async"

    ROUNDTRIP_SYMBOL         optional; an equity symbol (e.g. VT). When set,
                             the script PLACES A REAL ORDER once connected.
    ROUNDTRIP_MODE           "limit" (default): BUY a limit order at 80% of the
                             bid, so it should not fill, then cancel it. Times
                             place -> NEW and cancel -> CANCELLED.
                             "market": BUY at market. Times place -> FILLED and
                             the trade. This buys real shares.
    ROUNDTRIP_QUANTITY       optional; shares to order (default 1)

Speed metrics
-------------
Each ORDER/TRADE line ends with three timings:

    server   order last_modified (or trade timestamp) -> frame sent.
             Both are the server's clocks, so this is unaffected by your clock.
    network  frame sent -> received here. Compares the server's clock to
             yours, so clock skew is included (negative = your clock is
             behind). Sync your clock (macOS: System Settings > Date & Time)
             for meaningful numbers.
    total    the change on the server -> received here (server + network).

The round trip is timed with your local monotonic clock only, so it has no
clock skew: it is the latency you would actually see placing an order.

A table with min / median / p95 / max of every metric is printed on exit
(also on Ctrl+C).
"""

import asyncio
import math
import os
import statistics
import threading
import time
import uuid
from datetime import datetime, timezone
from decimal import ROUND_DOWN, Decimal
from typing import Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    InstrumentType,
    OrderExpirationRequest,
    OrderInstrument,
    OrderRequest,
    OrderSide,
    OrderType,
    OrderUpdateEvent,
    PublicApiClient,
    PublicApiClientConfiguration,
    StreamConnectedEvent,
    StreamDisconnectedEvent,
    StreamError,
    StreamOrder,
    TimeInForce,
    TradeEvent,
)
from public_api_sdk.models.quote import Quote

load_dotenv()

RUN_SECONDS = float(os.environ.get("STREAM_SECONDS", "120"))
ROUNDTRIP_TIMEOUT = 30.0  # seconds to wait for each round-trip event
CONNECT_TIMEOUT = 30.0


def _secret() -> str:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")
    return api_secret_key


def _describe(order: StreamOrder) -> str:
    filled = f" filled {order.filled_quantity} @ {order.average_price}" if order.filled_quantity else ""
    return (
        f"[{order.account_number}] {order.side} {order.instrument.symbol} "
        f"{order.type} v{order.version}: {order.status}{filled}"
    )


def _status(value: object) -> str:
    return str(getattr(value, "value", value))


def _ms(seconds: float) -> float:
    return seconds * 1000.0


# --------------------------------------------------------------------------- #
# Metrics                                                                      #
# --------------------------------------------------------------------------- #


class Metrics:
    """Collects timings (in ms) and when each order status / trade was seen.

    Thread-safe: the sync stream calls it from its own thread while the main
    thread runs the round trip.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._samples: Dict[str, List[float]] = {}
        self._first_event: Dict[str, float] = {}  # order_id -> monotonic
        self._status_seen: Dict[Tuple[str, str], float] = {}  # (order_id, status) -> monotonic
        self._trade_seen: Dict[str, float] = {}  # order_id -> monotonic of its first trade

    def add(self, name: str, value_ms: float) -> None:
        with self._lock:
            self._samples.setdefault(name, []).append(value_ms)

    # -- stream events ------------------------------------------------------ #

    def on_order(self, event: OrderUpdateEvent, received: datetime, received_mono: float) -> str:
        order = event.order
        with self._lock:
            self._first_event.setdefault(order.order_id, received_mono)
            self._status_seen.setdefault((order.order_id, _status(order.status)), received_mono)
        return self._latency("order", order.last_modified, event.timestamp, received)

    def on_trade(self, event: TradeEvent, received: datetime, received_mono: float) -> str:
        trade = event.trade
        if trade.order_id:
            with self._lock:
                self._trade_seen.setdefault(trade.order_id, received_mono)
        return self._latency("trade", trade.timestamp, event.timestamp, received)

    def _latency(
        self,
        kind: str,
        changed_at: Optional[datetime],
        sent_at: Optional[datetime],
        received: datetime,
    ) -> str:
        parts = []
        if changed_at is not None and sent_at is not None:
            server = _ms((sent_at - changed_at).total_seconds())
            self.add(f"{kind}: change -> sent (server)", server)
            parts.append(f"server {server:.0f}ms")
        if sent_at is not None:
            network = _ms((received - sent_at).total_seconds())
            self.add(f"{kind}: sent -> received (network)", network)
            parts.append(f"network {network:.0f}ms")
        if changed_at is not None:
            total = _ms((received - changed_at).total_seconds())
            self.add(f"{kind}: change -> received (total)", total)
            parts.append(f"total {total:.0f}ms")
        return f"  [{', '.join(parts)}]" if parts else ""

    # -- round trip lookups ------------------------------------------------- #

    def first_event_at(self, order_id: str) -> Optional[float]:
        with self._lock:
            return self._first_event.get(order_id)

    def status_seen_at(self, order_id: str, status: str) -> Optional[float]:
        with self._lock:
            return self._status_seen.get((order_id, status))

    def trade_seen_at(self, order_id: str) -> Optional[float]:
        with self._lock:
            return self._trade_seen.get(order_id)

    # -- summary ------------------------------------------------------------ #

    def print_summary(self) -> None:
        with self._lock:
            samples = {name: list(values) for name, values in self._samples.items()}
        print("\n=== Speed summary (ms) ===")
        if not samples:
            print("No timings recorded (no connection, orders or trades).")
            return
        width = max(len(name) for name in samples)
        print(f"{'metric':<{width}}  {'n':>4}  {'min':>8}  {'median':>8}  {'p95':>8}  {'max':>8}")
        for name in sorted(samples):
            values = sorted(samples[name])
            p95 = values[max(0, math.ceil(0.95 * len(values)) - 1)]
            print(
                f"{name:<{width}}  {len(values):>4}  {values[0]:>8.1f}  "
                f"{statistics.median(values):>8.1f}  {p95:>8.1f}  {values[-1]:>8.1f}"
            )
        print(
            "network/total compare the server's clock to yours (skew included); "
            "server and roundtrip are not affected by clock skew."
        )


# --------------------------------------------------------------------------- #
# Round trip (places a real order)                                             #
# --------------------------------------------------------------------------- #


class RoundTripPlan:
    def __init__(self, symbol: str, mode: str, quantity: Decimal) -> None:
        self.symbol = symbol
        self.mode = mode
        self.quantity = quantity
        self.instrument = OrderInstrument(symbol=symbol, type=InstrumentType.EQUITY)


def _roundtrip_plan() -> Optional[RoundTripPlan]:
    symbol = os.environ.get("ROUNDTRIP_SYMBOL", "").strip().upper()
    if not symbol:
        return None
    if not os.environ.get("DEFAULT_ACCOUNT_NUMBER"):
        print("ROUNDTRIP skipped: set DEFAULT_ACCOUNT_NUMBER to choose the account to trade in")
        return None
    mode = os.environ.get("ROUNDTRIP_MODE", "limit").strip().lower()
    if mode not in ("limit", "market"):
        raise ValueError("ROUNDTRIP_MODE must be 'limit' or 'market'")
    quantity = Decimal(os.environ.get("ROUNDTRIP_QUANTITY", "1"))
    return RoundTripPlan(symbol, mode, quantity)


def _build_order(plan: RoundTripPlan, quote: Optional[Quote]) -> OrderRequest:
    limit_price: Optional[Decimal] = None
    if plan.mode == "limit":
        reference = (quote.bid or quote.last) if quote else None
        if not reference:
            raise RuntimeError(f"no bid or last price for {plan.symbol}; cannot pick a safe limit price")
        limit_price = (reference * Decimal("0.8")).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
        if limit_price < Decimal("0.01"):
            raise RuntimeError(f"{plan.symbol} is too cheap for a non-filling limit order")
    return OrderRequest(
        order_id=str(uuid.uuid4()),
        instrument=plan.instrument,
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT if limit_price is not None else OrderType.MARKET,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=plan.quantity,
        limit_price=limit_price,
    )


def _order_text(request: OrderRequest) -> str:
    price = f" @ {request.limit_price} limit" if request.limit_price is not None else " at market"
    return f"BUY {request.quantity} {request.instrument.symbol}{price} (order {request.order_id})"


class RoundTrip:
    """The timing steps, shared by the sync and async runners."""

    def __init__(self, metrics: Metrics, order_id: str) -> None:
        self.metrics = metrics
        self.order_id = order_id

    def report(self, label: str, start: float, end: Optional[float]) -> None:
        if end is None:
            print(f"ROUNDTRIP {label}: no event within {ROUNDTRIP_TIMEOUT:.0f}s")
            return
        value = _ms(end - start)
        self.metrics.add(f"roundtrip: {label}", value)
        print(f"ROUNDTRIP {label}: {value:.0f} ms")

    def first_event(self) -> Optional[float]:
        return self.metrics.first_event_at(self.order_id)

    def status(self, status: str) -> Callable[[], Optional[float]]:
        return lambda: self.metrics.status_seen_at(self.order_id, status)

    def trade(self) -> Optional[float]:
        return self.metrics.trade_seen_at(self.order_id)

    def rejected(self) -> bool:
        return self.metrics.status_seen_at(self.order_id, "REJECTED") is not None


def _wait_sync(probe: Callable[[], Optional[float]], timeout: float = ROUNDTRIP_TIMEOUT) -> Optional[float]:
    # The time is captured when the event arrives, so polling here does not
    # affect the measurement.
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seen = probe()
        if seen is not None:
            return seen
        time.sleep(0.005)
    return probe()


async def _wait_async(probe: Callable[[], Optional[float]], timeout: float = ROUNDTRIP_TIMEOUT) -> Optional[float]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        seen = probe()
        if seen is not None:
            return seen
        await asyncio.sleep(0.005)
    return probe()


def run_roundtrip_sync(client: PublicApiClient, plan: RoundTripPlan, metrics: Metrics) -> None:
    try:
        quotes = client.get_quotes([plan.instrument]) if plan.mode == "limit" else []
        request = _build_order(plan, quotes[0] if quotes else None)
    except Exception as error:  # noqa: BLE001 - report and keep streaming
        print(f"ROUNDTRIP skipped: {error}")
        return
    rt = RoundTrip(metrics, request.order_id)
    print(f"ROUNDTRIP placing a REAL order: {_order_text(request)}")
    placed = False
    cancelled = False
    try:
        t_place = time.monotonic()
        client.place_order(request)
        placed = True
        rt.report("place -> REST ack", t_place, time.monotonic())
        rt.report("place -> first order event", t_place, _wait_sync(rt.first_event))
        if plan.mode == "market":
            rt.report("place -> FILLED event", t_place, _wait_sync(rt.status("FILLED")))
            rt.report("place -> TRADE event", t_place, _wait_sync(rt.trade))
            return
        rt.report("place -> NEW event", t_place, _wait_sync(rt.status("NEW")))
        if rt.rejected():
            print("ROUNDTRIP the order was rejected; nothing to cancel")
            cancelled = True
            return
        t_cancel = time.monotonic()
        client.cancel_order(request.order_id)
        cancelled = True
        rt.report("cancel -> REST ack", t_cancel, time.monotonic())
        rt.report("cancel -> CANCELLED event", t_cancel, _wait_sync(rt.status("CANCELLED")))
    except Exception as error:  # noqa: BLE001 - report and keep streaming
        print(f"ROUNDTRIP failed: {error}")
    finally:
        if plan.mode == "limit" and placed and not cancelled:
            try:  # never leave the test order resting
                client.cancel_order(request.order_id)
                print(f"ROUNDTRIP cancelled order {request.order_id}")
            except Exception as error:  # noqa: BLE001
                print(f"ROUNDTRIP could not cancel order {request.order_id}: {error} -- cancel it in the app")


async def run_roundtrip_async(client: AsyncPublicApiClient, plan: RoundTripPlan, metrics: Metrics) -> None:
    try:
        quotes = await client.get_quotes([plan.instrument]) if plan.mode == "limit" else []
        request = _build_order(plan, quotes[0] if quotes else None)
    except Exception as error:  # noqa: BLE001 - report and keep streaming
        print(f"ROUNDTRIP skipped: {error}")
        return
    rt = RoundTrip(metrics, request.order_id)
    print(f"ROUNDTRIP placing a REAL order: {_order_text(request)}")
    placed = False
    cancelled = False
    try:
        t_place = time.monotonic()
        await client.place_order(request)
        placed = True
        rt.report("place -> REST ack", t_place, time.monotonic())
        rt.report("place -> first order event", t_place, await _wait_async(rt.first_event))
        if plan.mode == "market":
            rt.report("place -> FILLED event", t_place, await _wait_async(rt.status("FILLED")))
            rt.report("place -> TRADE event", t_place, await _wait_async(rt.trade))
            return
        rt.report("place -> NEW event", t_place, await _wait_async(rt.status("NEW")))
        if rt.rejected():
            print("ROUNDTRIP the order was rejected; nothing to cancel")
            cancelled = True
            return
        t_cancel = time.monotonic()
        await client.cancel_order(request.order_id)
        cancelled = True
        rt.report("cancel -> REST ack", t_cancel, time.monotonic())
        rt.report("cancel -> CANCELLED event", t_cancel, await _wait_async(rt.status("CANCELLED")))
    except Exception as error:  # noqa: BLE001 - report and keep streaming
        print(f"ROUNDTRIP failed: {error}")
    finally:
        if plan.mode == "limit" and placed and not cancelled:
            try:  # never leave the test order resting
                await client.cancel_order(request.order_id)
                print(f"ROUNDTRIP cancelled order {request.order_id}")
            except Exception as error:  # noqa: BLE001
                print(f"ROUNDTRIP could not cancel order {request.order_id}: {error} -- cancel it in the app")


# --------------------------------------------------------------------------- #
# Runners                                                                      #
# --------------------------------------------------------------------------- #


def run_sync() -> None:
    """Callbacks on a background thread."""
    client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key=_secret()),
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )
    metrics = Metrics()
    plan = _roundtrip_plan()
    connected = threading.Event()
    disconnected_at: List[float] = []  # monotonic time of the last disconnect
    # Our view of the open orders, kept current by the stream.
    orders: Dict[str, str] = {}

    def on_connect(event: StreamConnectedEvent) -> None:
        now = time.monotonic()
        if not event.is_reconnect:
            connect_ms = _ms(now - t_open)
            metrics.add("connect: stream() -> connected", connect_ms)
            timing = f" in {connect_ms:.0f} ms"
        elif disconnected_at:
            gap_ms = _ms(now - disconnected_at[-1])
            metrics.add("reconnect: disconnected -> connected", gap_ms)
            timing = f" after {gap_ms:.0f} ms offline"
        else:
            timing = ""
        word = "Reconnected" if event.is_reconnect else "Connected"
        print(f"{word} to {event.account_ids} for {event.channels}{timing}")
        # Nothing is replayed after a disconnect: rebuild the view from REST.
        # Events that arrive meanwhile are delivered after this returns.
        for account_id in event.account_ids:
            if account_id == "*":
                continue  # use get_accounts() to list them when streaming "*"
            for order in client.get_portfolio(account_id).orders:
                orders[order.order_id] = str(order.status)
        print(f"  {len(orders)} open order(s) loaded from REST")
        connected.set()

    def on_order(event: OrderUpdateEvent) -> None:
        timing = metrics.on_order(event, datetime.now(timezone.utc), time.monotonic())
        orders[event.order.order_id] = str(event.order.status)
        print("ORDER ", _describe(event.order) + timing)

    def on_trade(event: TradeEvent) -> None:
        timing = metrics.on_trade(event, datetime.now(timezone.utc), time.monotonic())
        trade = event.trade
        print(
            f"TRADE  [{trade.account_number}] {trade.trade_id} {trade.status}: "
            f"{trade.side} {trade.quantity} {trade.instrument.symbol} @ {trade.price} "
            f"on {trade.market_identification_code or 'n/a'} (order {trade.order_id})"
            f"{timing}"
        )

    def on_disconnect(event: StreamDisconnectedEvent) -> None:
        disconnected_at.append(time.monotonic())
        retry = f", retrying in {event.reconnect_in:.1f}s" if event.will_reconnect else ""
        print(f"Disconnected ({event.status_code or event.close_code}: {event.reason}){retry}")

    deadline = time.monotonic() + RUN_SECONDS
    t_open = time.monotonic()
    stream = client.stream(
        on_order=on_order,
        on_trade=on_trade,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_error=lambda error: print(f"Stream stopped: {error}"),
    )
    print(f"Streaming for {RUN_SECONDS:.0f}s ... (Ctrl+C to stop)")
    try:
        if plan is not None:
            if connected.wait(CONNECT_TIMEOUT):
                run_roundtrip_sync(client, plan, metrics)
            else:
                print(f"ROUNDTRIP skipped: not connected within {CONNECT_TIMEOUT:.0f}s")
        stream.wait(max(0.0, deadline - time.monotonic()))
    except StreamError:
        pass  # already reported by on_error
    except KeyboardInterrupt:
        pass
    finally:
        client.close()  # closes the stream too
        metrics.print_summary()


async def run_async() -> None:
    """An async iterator in the caller's event loop."""
    metrics = Metrics()
    plan = _roundtrip_plan()
    async with AsyncPublicApiClient(
        ApiKeyAuthConfig(api_secret_key=_secret()),
        config=AsyncPublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    ) as client:
        deadline = time.monotonic() + RUN_SECONDS
        connected = asyncio.Event()
        # The async client fetches its token lazily, so the first connect
        # includes getting an access token.
        t_open = time.monotonic()
        async with client.stream() as stream:
            print(f"Streaming for {RUN_SECONDS:.0f}s ...")

            async def consume() -> None:
                disconnected_at: Optional[float] = None
                try:
                    while True:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            break
                        try:
                            event = await asyncio.wait_for(stream.__anext__(), remaining)
                        except (asyncio.TimeoutError, StopAsyncIteration):
                            break
                        now_mono = time.monotonic()
                        now_wall = datetime.now(timezone.utc)
                        if isinstance(event, StreamConnectedEvent):
                            if not event.is_reconnect:
                                value = _ms(now_mono - t_open)
                                metrics.add("connect: stream() -> connected", value)
                                timing = f" in {value:.0f} ms"
                            elif disconnected_at is not None:
                                value = _ms(now_mono - disconnected_at)
                                metrics.add("reconnect: disconnected -> connected", value)
                                timing = f" after {value:.0f} ms offline"
                            else:
                                timing = ""
                            word = "Reconnected" if event.is_reconnect else "Connected"
                            print(f"{word} to {event.account_ids}{timing}")
                            connected.set()
                        elif isinstance(event, OrderUpdateEvent):
                            timing = metrics.on_order(event, now_wall, now_mono)
                            print("ORDER ", _describe(event.order) + timing)
                        elif isinstance(event, TradeEvent):
                            timing = metrics.on_trade(event, now_wall, now_mono)
                            t = event.trade
                            print(f"TRADE  {t.trade_id} {t.status}: {t.side} {t.quantity} @ {t.price}{timing}")
                        elif isinstance(event, StreamDisconnectedEvent):
                            disconnected_at = now_mono
                            print(f"Disconnected: {event.reason}")
                except StreamError as error:
                    print(f"Stream stopped: {error}")

            consumer = asyncio.create_task(consume())
            try:
                if plan is not None:
                    try:
                        await asyncio.wait_for(connected.wait(), CONNECT_TIMEOUT)
                    except asyncio.TimeoutError:
                        print(f"ROUNDTRIP skipped: not connected within {CONNECT_TIMEOUT:.0f}s")
                    else:
                        await run_roundtrip_async(client, plan, metrics)
                await consumer
            finally:
                consumer.cancel()
                metrics.print_summary()


if __name__ == "__main__":
    try:
        if os.environ.get("STREAM_MODE", "sync").lower() == "async":
            asyncio.run(run_async())
        else:
            run_sync()
    except KeyboardInterrupt:
        pass  # the summary was printed by the runner
