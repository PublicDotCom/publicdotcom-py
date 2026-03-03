"""Async client example: Live price subscriptions for MSFT and NVDA.

Demonstrates the AsyncPublicApiClient, including:

  - API-key authentication via async context manager (no manual cleanup needed)
  - Concurrent account + portfolio fetch with asyncio.gather
  - One-off quote snapshot before subscribing
  - Cancel-and-replace an open order (crypto/options only; equity coming soon)
  - Two independent async price subscriptions (one per symbol, 1-second polling)
  - Async callbacks with bid-ask spread and percentage-change tracking
  - Mid-run pause and resume of an individual subscription
  - Dynamic polling-frequency adjustment without re-subscribing
  - Subscription-info inspection at runtime
  - Summary stats printed at the end

Run:
    API_SECRET_KEY=<key> DEFAULT_ACCOUNT_NUMBER=<acct> python examples/example_async_client.py
"""

import asyncio
import os
import uuid
from decimal import Decimal
from typing import Dict, List, Optional

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    CancelAndReplaceRequest,
    InstrumentType,
    OrderExpirationRequest,
    OrderInstrument,
    OrderRequest,
    OrderSide,
    OrderType,
    PriceChange,
    SubscriptionConfig,
    TimeInForce,
)


# ---------------------------------------------------------------------------
# Instruments
# ---------------------------------------------------------------------------

MSFT = OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY)
NVDA = OrderInstrument(symbol="NVDA", type=InstrumentType.EQUITY)


# ---------------------------------------------------------------------------
# Stat tracker — collects live price and spread data per symbol
# ---------------------------------------------------------------------------


class QuoteTracker:
    """Accumulates price updates for a single symbol."""

    def __init__(self, symbol: str) -> None:
        self.symbol = symbol
        self.update_count: int = 0
        self.last_price: Optional[Decimal] = None
        self.min_price: Optional[Decimal] = None
        self.max_price: Optional[Decimal] = None
        self.spreads: List[Decimal] = []
        self.significant_moves: int = 0  # moves > 0.5 %

    def record(self, change: PriceChange) -> None:
        self.update_count += 1
        price = change.new_quote.last
        bid = change.new_quote.bid
        ask = change.new_quote.ask

        if price:
            # track range
            self.last_price = price
            if self.min_price is None or price < self.min_price:
                self.min_price = price
            if self.max_price is None or price > self.max_price:
                self.max_price = price

            # detect significant moves
            if change.old_quote and change.old_quote.last:
                old = change.old_quote.last
                pct = abs((price - old) / old * 100)
                if pct >= Decimal("0.5"):
                    self.significant_moves += 1

        if bid and ask and ask > 0:
            self.spreads.append(ask - bid)

    def summary(self) -> str:
        if self.last_price is None:
            return f"{self.symbol}: no updates received"
        avg_spread = (
            sum(self.spreads) / len(self.spreads) if self.spreads else Decimal(0)
        )
        return (
            f"{self.symbol:>5}: {self.update_count:3} updates | "
            f"last=${self.last_price:>9.2f} | "
            f"range=[${ self.min_price:.2f}, ${self.max_price:.2f}] | "
            f"avg spread=${avg_spread:.4f} | "
            f"significant moves: {self.significant_moves}"
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _price_direction(change: PriceChange) -> str:
    """Return an arrow showing whether the price rose, fell, or held."""
    new = change.new_quote.last
    old = change.old_quote.last if change.old_quote else None
    if new is None or old is None:
        return "→"
    if new > old:
        return "↑"
    if new < old:
        return "↓"
    return "→"


def _pct_change(change: PriceChange) -> Optional[Decimal]:
    """Return percentage change between old and new last price, or None."""
    new = change.new_quote.last
    old = change.old_quote.last if change.old_quote else None
    if new is None or old is None or old == 0:
        return None
    return (new - old) / old * 100


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    load_dotenv()

    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    config = AsyncPublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
    )

    msft_tracker = QuoteTracker("MSFT")
    nvda_tracker = QuoteTracker("NVDA")

    # ------------------------------------------------------------------
    # async with ensures subscriptions are cancelled and the HTTP client
    # is closed even if an exception is raised.
    # ------------------------------------------------------------------
    async with AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key=api_secret_key),
        config=config,
    ) as client:

        # --- Fetch account info and portfolio concurrently ----------------
        print("Fetching accounts and portfolio simultaneously...")
        accounts_resp, portfolio = await asyncio.gather(
            client.get_accounts(),
            client.get_portfolio(),
        )

        print(f"Accounts: {len(accounts_resp.accounts)}")
        for acct in accounts_resp.accounts:
            print(f"  {acct.account_id}  ({acct.account_type.value})")

        print(f"\nPortfolio  ({portfolio.account_id})")
        print(f"  Buying power (cash): ${portfolio.buying_power.cash_only_buying_power:.2f}")
        print(f"  Buying power (margin): ${portfolio.buying_power.buying_power:.2f}")
        print(f"  Open positions: {len(portfolio.positions)}")
        for pos in portfolio.positions:
            val = pos.current_value
            pct = pos.percent_of_portfolio
            val_str = f"${val:.2f}" if val is not None else "N/A"
            pct_str = f"{pct:.1f}%" if pct is not None else "N/A"
            print(f"    {pos.instrument.symbol:<8} qty={pos.quantity}  value={val_str}  ({pct_str})")

        # --- One-off quote snapshot before subscribing --------------------
        print("\nFetching initial quotes for MSFT and NVDA...")
        quotes = await client.get_quotes([MSFT, NVDA])
        for q in quotes:
            spread = (q.ask or Decimal(0)) - (q.bid or Decimal(0))
            print(
                f"  {q.instrument.symbol:<5}  last=${q.last:.2f}  "
                f"bid=${q.bid:.2f}  ask=${q.ask:.2f}  spread=${spread:.4f}"
            )

        # --- Cancel and replace an existing order -------------------------
        #
        # NOTE: cancel-and-replace currently supports crypto (quantity-based)
        # orders and options orders only. Equity support is coming soon.
        #
        # Uncomment and fill in a real open order ID to try this live.
        #
        # original_order_id = "YOUR_OPEN_ORDER_ID"
        # print(f"\nCancelling and replacing order {original_order_id}...")
        # replacement = await client.cancel_and_replace_order(
        #     CancelAndReplaceRequest(
        #         order_id=original_order_id,
        #         request_id=str(uuid.uuid4()),
        #         order_type=OrderType.LIMIT,
        #         expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        #         quantity=Decimal("1"),
        #         limit_price=Decimal("228.00"),
        #     )
        # )
        # print(f"  Replacement order ID: {replacement.order_id}")
        # replacement_details = await replacement.wait_for_fill(timeout=30)
        # print(f"  Filled at: ${replacement_details.average_price}")

        # --- Define async callbacks (one per symbol) ----------------------

        async def on_msft_change(change: PriceChange) -> None:
            msft_tracker.record(change)
            direction = _price_direction(change)
            price = change.new_quote.last or Decimal(0)
            spread = (change.new_quote.ask or Decimal(0)) - (change.new_quote.bid or Decimal(0))
            pct = _pct_change(change)
            pct_str = f"  ({pct:+.3f}%)" if pct is not None else ""
            print(
                f"[MSFT] {direction} ${price:>9.2f}  "
                f"bid=${change.new_quote.bid:.2f}  ask=${change.new_quote.ask:.2f}  "
                f"spread=${spread:.4f}{pct_str}"
            )
            if pct is not None and abs(pct) >= Decimal("0.5"):
                print(f"         ** ALERT: MSFT moved {pct:+.2f}% **")

        async def on_nvda_change(change: PriceChange) -> None:
            nvda_tracker.record(change)
            direction = _price_direction(change)
            price = change.new_quote.last or Decimal(0)
            spread = (change.new_quote.ask or Decimal(0)) - (change.new_quote.bid or Decimal(0))
            pct = _pct_change(change)
            pct_str = f"  ({pct:+.3f}%)" if pct is not None else ""
            print(
                f"[NVDA] {direction} ${price:>9.2f}  "
                f"bid=${change.new_quote.bid:.2f}  ask=${change.new_quote.ask:.2f}  "
                f"spread=${spread:.4f}{pct_str}"
            )
            if pct is not None and abs(pct) >= Decimal("0.5"):
                print(f"         ** ALERT: NVDA moved {pct:+.2f}% **")

        # --- Create one subscription per symbol ---------------------------
        #
        # Separate subscriptions let us pause, resume, and tune each symbol
        # independently. Both poll every 1 second.
        #
        print("\nStarting price subscriptions (1 s polling)...\n")
        msft_sub = await client.price_stream.subscribe(
            instruments=[MSFT],
            callback=on_msft_change,
            config=SubscriptionConfig(polling_frequency_seconds=1.0),
        )
        nvda_sub = await client.price_stream.subscribe(
            instruments=[NVDA],
            callback=on_nvda_change,
            config=SubscriptionConfig(polling_frequency_seconds=1.0),
        )
        print(f"MSFT subscription ID: {msft_sub}")
        print(f"NVDA subscription ID: {nvda_sub}\n")

        # --- Phase 1: both subscriptions active (0-10 s) ------------------
        await asyncio.sleep(10)

        # --- Pause NVDA (10-15 s) -----------------------------------------
        print("\n-- Pausing NVDA subscription for 5 seconds --")
        client.price_stream.pause(nvda_sub)
        await asyncio.sleep(5)

        # --- Resume NVDA (15-25 s) ----------------------------------------
        print("-- Resuming NVDA subscription --\n")
        client.price_stream.resume(nvda_sub)
        await asyncio.sleep(10)

        # --- Slow down MSFT polling (25-30 s) ------------------------------
        print("\n-- Slowing MSFT polling to 3 seconds --")
        client.price_stream.set_polling_frequency(msft_sub, 3.0)
        await asyncio.sleep(5)

        # --- Inspect active subscriptions ---------------------------------
        active = client.price_stream.get_active_subscriptions()
        print(f"\nActive subscriptions: {len(active)}")

        msft_info = client.price_stream.get_subscription_info(msft_sub)
        nvda_info = client.price_stream.get_subscription_info(nvda_sub)
        if msft_info:
            print(f"  MSFT: polling every {msft_info.polling_frequency}s")
        if nvda_info:
            print(f"  NVDA: polling every {nvda_info.polling_frequency}s")

        # --- Final portfolio snapshot (shows any live P&L changes) --------
        print("\n-- Final portfolio snapshot --")
        portfolio = await client.get_portfolio()
        print(f"  Buying power (cash): ${portfolio.buying_power.cash_only_buying_power:.2f}")
        for pos in portfolio.positions:
            val = pos.current_value
            gain = pos.position_daily_gain
            val_str = f"${val:.2f}" if val is not None else "N/A"
            gain_str = ""
            if gain and gain.gain_value is not None and gain.gain_percentage is not None:
                gain_str = f"  daily P&L: ${gain.gain_value:.2f} ({gain.gain_percentage:.2f}%)"
            print(f"    {pos.instrument.symbol:<8} value={val_str}{gain_str}")

        # --- Summary stats ------------------------------------------------
        print("\n" + "=" * 60)
        print("Summary (30-second window)")
        print("=" * 60)
        print(msft_tracker.summary())
        print(nvda_tracker.summary())
        print("=" * 60)

        print("\nShutting down (subscriptions cancelled by context manager)...")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
