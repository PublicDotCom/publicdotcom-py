"""Stream order updates and trades over the account WebSocket.

Read-only: this example places no orders. Place or cancel an order in the
Public app (or with another example) while it runs to see events arrive.

Environment:
    API_SECRET_KEY           required
    DEFAULT_ACCOUNT_NUMBER   optional; without it every account is streamed
    STREAM_SECONDS           optional; how long to run (default 120)
    STREAM_MODE              "sync" (default) or "async"
"""

import asyncio
import os
import time
from typing import Dict

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    OrderUpdateEvent,
    PublicApiClient,
    PublicApiClientConfiguration,
    StreamConnectedEvent,
    StreamDisconnectedEvent,
    StreamError,
    StreamOrder,
    TradeEvent,
)

load_dotenv()

RUN_SECONDS = float(os.environ.get("STREAM_SECONDS", "120"))


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


def run_sync() -> None:
    """Callbacks on a background thread."""
    client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key=_secret()),
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )
    # Our view of the open orders, kept current by the stream.
    orders: Dict[str, str] = {}

    def on_connect(event: StreamConnectedEvent) -> None:
        # Nothing is replayed after a disconnect: rebuild the view from REST.
        # Events that arrive meanwhile are delivered after this returns.
        word = "Reconnected" if event.is_reconnect else "Connected"
        print(f"{word} to {event.account_ids} for {event.channels}")
        for account_id in event.account_ids:
            if account_id == "*":
                continue  # use get_accounts() to list them when streaming "*"
            for order in client.get_portfolio(account_id).orders:
                orders[order.order_id] = str(order.status)
        print(f"  {len(orders)} open order(s) loaded from REST")

    def on_order(event: OrderUpdateEvent) -> None:
        orders[event.order.order_id] = str(event.order.status)
        print("ORDER ", _describe(event.order))

    def on_trade(event: TradeEvent) -> None:
        trade = event.trade
        print(
            f"TRADE  [{trade.account_number}] {trade.trade_id} {trade.status}: "
            f"{trade.side} {trade.quantity} {trade.instrument.symbol} @ {trade.price} "
            f"on {trade.market_identification_code or 'n/a'} (order {trade.order_id})"
        )

    def on_disconnect(event: StreamDisconnectedEvent) -> None:
        retry = f", retrying in {event.reconnect_in:.1f}s" if event.will_reconnect else ""
        print(f"Disconnected ({event.status_code or event.close_code}: {event.reason}){retry}")

    stream = client.stream(
        on_order=on_order,
        on_trade=on_trade,
        on_connect=on_connect,
        on_disconnect=on_disconnect,
        on_error=lambda error: print(f"Stream stopped: {error}"),
    )
    print(f"Streaming for {RUN_SECONDS:.0f}s ... (Ctrl+C to stop)")
    try:
        stream.wait(RUN_SECONDS)
    except StreamError:
        pass  # already reported by on_error
    except KeyboardInterrupt:
        pass
    finally:
        client.close()  # closes the stream too


async def run_async() -> None:
    """An async iterator in the caller's event loop."""
    async with AsyncPublicApiClient(
        ApiKeyAuthConfig(api_secret_key=_secret()),
        config=AsyncPublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    ) as client:
        deadline = time.monotonic() + RUN_SECONDS
        async with client.stream() as stream:
            print(f"Streaming for {RUN_SECONDS:.0f}s ...")
            try:
                while True:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    try:
                        event = await asyncio.wait_for(stream.__anext__(), remaining)
                    except (asyncio.TimeoutError, StopAsyncIteration):
                        break
                    if isinstance(event, StreamConnectedEvent):
                        word = "Reconnected" if event.is_reconnect else "Connected"
                        print(f"{word} to {event.account_ids}")
                    elif isinstance(event, OrderUpdateEvent):
                        print("ORDER ", _describe(event.order))
                    elif isinstance(event, TradeEvent):
                        t = event.trade
                        print(f"TRADE  {t.trade_id} {t.status}: {t.side} {t.quantity} @ {t.price}")
                    elif isinstance(event, StreamDisconnectedEvent):
                        print(f"Disconnected: {event.reason}")
            except StreamError as error:
                print(f"Stream stopped: {error}")


if __name__ == "__main__":
    if os.environ.get("STREAM_MODE", "sync").lower() == "async":
        asyncio.run(run_async())
    else:
        run_sync()
