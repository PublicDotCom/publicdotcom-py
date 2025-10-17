import asyncio
import os
import time
from decimal import Decimal
from typing import Dict, List

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    PublicApiClient,
    PublicApiClientConfiguration,
    OrderInstrument,
    InstrumentType,
    PriceChange,
    SubscriptionConfig,
)


# Example 1: Basic price subscription with sync callback
def basic_subscription_example() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )
    config = PublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER")
    )
    client = PublicApiClient(auth_config=auth_config, config=config)

    def on_price_change(price_change: PriceChange) -> None:
        symbol = price_change.instrument.symbol
        old_price = price_change.old_quote.last if price_change.old_quote else "N/A"
        new_price = price_change.new_quote.last
        print(f"Price change for {symbol}: {old_price} -> {new_price}")

    instruments = [
        OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
        OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY),
    ]

    # subscribe with 1-second polling frequency
    subscription_id = client.price_stream.subscribe(
        instruments=instruments,
        callback=on_price_change,
        config=SubscriptionConfig(polling_frequency_seconds=1.0),
    )

    print(f"Started subscription: {subscription_id}")
    print("Monitoring prices... Press Ctrl+C to stop")

    try:
        # run for 30 seconds
        time.sleep(30)
    except KeyboardInterrupt:
        print("\nStopping subscription...")
    finally:
        client.price_stream.unsubscribe(subscription_id)
        client.close()
        print("Subscription stopped")


# Example 2: Advanced subscription with async callback and management
async def advanced_subscription_example() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )
    config = PublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER")
    )
    client = PublicApiClient(auth_config=auth_config, config=config)

    # track price changes
    price_history: Dict[str, List[Decimal]] = {}

    # async callback with more complex logic
    async def on_price_change_async(price_change: PriceChange) -> None:
        symbol = price_change.instrument.symbol
        new_price = price_change.new_quote.last

        # track price history
        if symbol not in price_history:
            price_history[symbol] = []
        if new_price:
            price_history[symbol].append(new_price)

            # calculate percentage change
            if price_change.old_quote and price_change.old_quote.last:
                old_price = price_change.old_quote.last
                pct_change = ((new_price - old_price) / old_price) * 100

                # alert on significant changes
                if abs(pct_change) > 1:
                    print(f"⚠️  ALERT: {symbol} moved {pct_change:.2f}%!")

        # show current state
        print(f"{symbol}: ${new_price:.2f}")
        print(
            f"  Bid: ${price_change.new_quote.bid:.2f} x {price_change.new_quote.bid_size}"
        )
        print(
            f"  Ask: ${price_change.new_quote.ask:.2f} x {price_change.new_quote.ask_size}"
        )

        # simulate async processing
        await asyncio.sleep(0.1)

    instruments = [
        OrderInstrument(symbol="SPY", type=InstrumentType.EQUITY),
        OrderInstrument(symbol="QQQ", type=InstrumentType.EQUITY),
    ]

    # create subscription with retry configuration
    subscription_id = client.price_stream.subscribe(
        instruments=instruments,
        callback=on_price_change_async,
        config=SubscriptionConfig(
            polling_frequency_seconds=1.0,
            retry_on_error=True,
            max_retries=5,
            exponential_backoff=True,
        ),
    )

    print(f"Started advanced subscription: {subscription_id}")

    await asyncio.sleep(10)
    print("\nPausing subscription...")
    client.price_stream.pause(subscription_id)

    await asyncio.sleep(5)
    print("Resuming subscription...")
    client.price_stream.resume(subscription_id)

    await asyncio.sleep(5)
    print("\nUpdating polling frequency to 3 seconds...")
    client.price_stream.set_polling_frequency(subscription_id, 3.0)

    await asyncio.sleep(10)

    client.price_stream.unsubscribe(subscription_id)
    client.close()


# Example 3: Multiple concurrent subscriptions with different frequencies
def multiple_subscriptions_example() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )
    config = PublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER")
    )
    client = PublicApiClient(auth_config=auth_config, config=config)

    subscriptions = []

    # fast-moving stocks with high frequency polling
    def on_fast_stocks_change(price_change: PriceChange) -> None:
        print(
            f"[FAST] {price_change.instrument.symbol}: ${price_change.new_quote.last:.2f}"
        )

    fast_instruments = [
        OrderInstrument(symbol="TSLA", type=InstrumentType.EQUITY),
        OrderInstrument(symbol="NVDA", type=InstrumentType.EQUITY),
    ]
    fast_sub = client.price_stream.subscribe(
        instruments=fast_instruments,
        callback=on_fast_stocks_change,
        config=SubscriptionConfig(polling_frequency_seconds=0.5),
    )
    subscriptions.append(fast_sub)
    print(f"Started fast subscription: {fast_sub}")

    # slower-moving ETFs with lower frequency
    def on_slow_change(price_change: PriceChange) -> None:
        print(
            f"[SLOW] {price_change.instrument.symbol}: ${price_change.new_quote.last:.2f}"
        )

    etf_instruments = [
        OrderInstrument(symbol="VTI", type=InstrumentType.EQUITY),
        OrderInstrument(symbol="BND", type=InstrumentType.EQUITY),
    ]
    slow_sub = client.price_stream.subscribe(
        instruments=etf_instruments,
        callback=on_slow_change,
        config=SubscriptionConfig(polling_frequency_seconds=5.0),
    )
    subscriptions.append(slow_sub)
    print(f"Started slow subscription: {slow_sub}")

    # medium frequency
    def on_medium_frequency_change(price_change: PriceChange) -> None:
        print(
            f"[MED] {price_change.instrument.symbol}: ${price_change.new_quote.last:.2f}"
        )

    medium_frequency_instruments = [
        OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY),
    ]
    medium_frequency_sub = client.price_stream.subscribe(
        instruments=medium_frequency_instruments,
        callback=on_medium_frequency_change,
        config=SubscriptionConfig(polling_frequency_seconds=2.0),
    )
    subscriptions.append(medium_frequency_sub)
    print(f"Started medium frequency subscription: {medium_frequency_sub}")

    print(f"\nRunning {len(subscriptions)} concurrent subscriptions...")
    print("Press Ctrl+C to stop\n")

    try:
        time.sleep(60)
        active = client.price_stream.get_active_subscriptions()
        print(f"\nActive subscriptions: {len(active)}")
        for sub_id in active:
            print(f"  {sub_id[:8]}...")
    except KeyboardInterrupt:
        print("\nStopping all subscriptions...")
    finally:
        client.price_stream.unsubscribe_all()
        client.close()
        print("All subscriptions stopped")


# Example 4: Custom price alert system
class PriceAlertSystem:
    """A custom price alert system built on top of subscriptions."""

    def __init__(self, client: PublicApiClient):
        self.client = client
        self.alerts: Dict[str, Dict] = {}
        self.subscription_id = ""

    def add_alert(
        self,
        symbol: str,
        instrument_type: InstrumentType,
        target_price: Decimal,
        alert_type: str = "above",
    ) -> None:
        key = f"{symbol}_{instrument_type.value}"
        self.alerts[key] = {
            "symbol": symbol,
            "type": instrument_type,
            "target": target_price,
            "alert_type": alert_type,
            "triggered": False,
        }

    def start_monitoring(self) -> None:
        if not self.alerts:
            print("No alerts configured")
            return

        instruments = [
            OrderInstrument(symbol=alert["symbol"], type=alert["type"])
            for alert in self.alerts.values()
        ]
        self.subscription_id = self.client.price_stream.subscribe(
            instruments=instruments,
            callback=self._check_alerts,
            config=SubscriptionConfig(polling_frequency_seconds=1.0),
        )

    def _check_alerts(self, price_change: PriceChange) -> None:
        """Check if any alerts should be triggered."""
        key = f"{price_change.instrument.symbol}_{price_change.instrument.type.value}"

        if key not in self.alerts:
            return

        alert = self.alerts[key]
        if alert["triggered"]:
            return

        current_price = price_change.new_quote.last
        if not current_price:
            return

        should_trigger = False
        if alert["alert_type"] == "above" and current_price > alert["target"]:
            should_trigger = True
        elif alert["alert_type"] == "below" and current_price < alert["target"]:
            should_trigger = True

        if should_trigger:
            alert["triggered"] = True
            print(
                f"🔔 ALERT: {alert['symbol']} is now ${current_price:.2f} "
                f"({alert['alert_type']} target ${alert['target']:.2f})"
            )

    def stop_monitoring(self) -> None:
        if self.subscription_id:
            self.client.price_stream.unsubscribe(self.subscription_id)
            print("Alert monitoring stopped")


def price_alert_example() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )
    config = PublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER")
    )
    client = PublicApiClient(auth_config=auth_config, config=config)

    # create alert system
    alert_system = PriceAlertSystem(client)

    # add some alerts
    alert_system.add_alert("AAPL", InstrumentType.EQUITY, Decimal("155.00"), "above")
    alert_system.add_alert("GOOGL", InstrumentType.EQUITY, Decimal("140.00"), "below")
    alert_system.add_alert("MSFT", InstrumentType.EQUITY, Decimal("380.00"), "above")

    # start monitoring
    alert_system.start_monitoring()

    try:
        print("\nMonitoring for price alerts... Press Ctrl+C to stop\n")
        time.sleep(60)
    except KeyboardInterrupt:
        print("\nStopping alert system...")
    finally:
        alert_system.stop_monitoring()
        client.close()


if __name__ == "__main__":
    import sys

    # load env variables from .env file
    load_dotenv()

    print("Public API SDK - Price Subscription Examples")
    print("=" * 50)
    print("1. Basic subscription example")
    print("2. Advanced async subscription example")
    print("3. Multiple concurrent subscriptions")
    print("4. Price alert system")
    print("=" * 50)

    choice = input("Select an example (1-4): ").strip()

    if choice == "1":
        basic_subscription_example()
    elif choice == "2":
        asyncio.run(advanced_subscription_example())
    elif choice == "3":
        multiple_subscriptions_example()
    elif choice == "4":
        price_alert_example()
    else:
        print("Invalid choice")
        sys.exit(1)
