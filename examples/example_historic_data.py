"""Historic bar data example.

Demonstrates fetching OHLCV bar data using get_bars() on both the sync and
async clients, covering:

  - Default aggregation for a standard time period (YEAR)
  - Aggregation override for intraday data (DAY + FIVE_MINUTES)
  - SINCE_PURCHASE period with a purchase_date
  - Iterating pre-market, regular-market, and after-hours sessions

Run:
    API_SECRET_KEY=<key> python examples/example_historic_data.py
"""

import asyncio
import os

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    BarAggregation,
    BarPeriod,
    InstrumentType,
    PublicApiClient,
    PublicApiClientConfiguration,
)

load_dotenv()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _print_bars_summary(bars) -> None:
    """Print a concise summary of a BarsResponse."""
    print(f"  Symbol : {bars.symbol}")
    print(f"  Period : {bars.period}")
    print(f"  Total expected bars : {bars.total_expected_bars}")

    for label, session in (
        ("Pre-market", bars.pre_market),
        ("Regular   ", bars.regular_market),
        ("After-hrs ", bars.after_market),
    ):
        count = len(session.bars)
        if count:
            first = session.bars[0]
            last = session.bars[-1]
            print(
                f"  {label}: {count}/{session.expected_bars} bars  "
                f"[{first.timestamp} open=${first.open}  …  "
                f"{last.timestamp} close=${last.close}]"
            )
        else:
            print(f"  {label}: 0/{session.expected_bars} bars (none returned)")

    if bars.total_gain_loss is not None:
        print(f"  Gain/loss : ${bars.total_gain_loss} ({bars.total_gain_loss_percentage}%)")


# ---------------------------------------------------------------------------
# Sync example
# ---------------------------------------------------------------------------


def sync_example() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key=api_secret_key),
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )

    try:
        # --- 1. Full year of daily bars (server picks aggregation) ----------
        print("\n[1] AAPL — 1 year, default aggregation")
        bars = client.get_bars("AAPL", BarPeriod.YEAR)
        _print_bars_summary(bars)

        # --- 2. Today's intraday bars at 5-minute resolution ----------------
        print("\n[2] AAPL — 1 day, 5-minute bars")
        bars = client.get_bars(
            "AAPL",
            BarPeriod.DAY,
            aggregation=BarAggregation.FIVE_MINUTES,
        )
        _print_bars_summary(bars)

        # --- 3. Performance since a specific purchase date ------------------
        print("\n[3] AAPL — since purchase on 2024-01-02")
        bars = client.get_bars(
            "AAPL",
            BarPeriod.SINCE_PURCHASE,
            purchase_date="2024-01-02",
        )
        _print_bars_summary(bars)

        # --- 4. YTD hourly bars for a crypto symbol -------------------------
        print("\n[4] BTC — YTD, 1-hour bars")
        bars = client.get_bars(
            "BTC",
            BarPeriod.YTD,
            instrument_type=InstrumentType.CRYPTO,
            aggregation=BarAggregation.ONE_HOUR,
        )
        _print_bars_summary(bars)

    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Async example
# ---------------------------------------------------------------------------


async def async_example() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    config = AsyncPublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
    )

    async with AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key=api_secret_key),
        config=config,
    ) as client:

        # --- Fetch multiple symbols concurrently ---------------------------
        print("\n[async] AAPL and MSFT — 1 year, concurrent fetch")
        aapl_bars, msft_bars = await asyncio.gather(
            client.get_bars("AAPL", BarPeriod.YEAR),
            client.get_bars("MSFT", BarPeriod.YEAR),
        )
        print("AAPL:")
        _print_bars_summary(aapl_bars)
        print("MSFT:")
        _print_bars_summary(msft_bars)

        # --- Intraday with aggregation override ----------------------------
        print("\n[async] NVDA — 1 week, 30-minute bars")
        bars = await client.get_bars(
            "NVDA",
            BarPeriod.WEEK,
            aggregation=BarAggregation.THIRTY_MINUTES,
        )
        _print_bars_summary(bars)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    print("=== Sync client ===")
    sync_example()

    print("\n=== Async client ===")
    asyncio.run(async_example())
