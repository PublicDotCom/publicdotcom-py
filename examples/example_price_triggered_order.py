import os
import time
import uuid
from decimal import Decimal
from typing import Optional

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    InstrumentType,
    PublicApiClient,
    PublicApiClientConfiguration,
    OrderExpirationRequest,
    OrderInstrument,
    OrderSide,
    OrderType,
    OrderRequest,
    TimeInForce,
    OrderStatus,
    NewOrder,
    OrderUpdate,
    PriceChange,
    SubscriptionConfig,
    OrderSubscriptionConfig,
    WaitTimeoutError,
)


class PriceTriggeredOrderBot:
    """A bot that monitors price and places an order when a threshold is reached."""

    def __init__(
        self,
        client: PublicApiClient,
        symbol: str,
        target_price: Decimal,
        order_quantity: Decimal,
    ):
        self.client = client
        self.symbol = symbol
        self.target_price = target_price
        self.order_quantity = order_quantity
        self.order_side = OrderSide.BUY
        self.order_placed = False
        self.current_order: Optional[NewOrder] = None
        self.price_subscription_id: Optional[str] = None
        self.order_subscription_id: Optional[str] = None

    def on_price_change(self, price_change: PriceChange) -> None:
        if not price_change.new_quote or not price_change.new_quote.last:
            return

        current_price = price_change.new_quote.last

        print(
            f"📊 {self.symbol} Price: ${current_price:.2f} "
            f"(Target: ${self.target_price:.2f})"
        )

        # check if we should place an order
        if not self.order_placed:
            should_place_order = False

            if self.order_side == OrderSide.BUY:
                # for buy orders, trigger when price is at or below target
                if current_price <= self.target_price:
                    should_place_order = True
                    print(
                        f"✅ Price ${current_price:.2f} is at or below target "
                        f"${self.target_price:.2f}"
                    )
            else:
                # for sell orders, trigger when price is at or above target
                if current_price >= self.target_price:
                    should_place_order = True
                    print(
                        f"✅ Price ${current_price:.2f} is at or above target "
                        f"${self.target_price:.2f}"
                    )

            if should_place_order:
                self.place_market_order()

    def place_market_order(self) -> None:
        if self.order_placed:
            return
        self.order_placed = True

        print(
            f"\n🚀 Placing {self.order_side.value} market order for "
            "{self.order_quantity} shares of {self.symbol}..."
        )

        try:
            order_request = OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(
                    symbol=self.symbol,
                    type=InstrumentType.EQUITY,
                ),
                order_side=self.order_side,
                order_type=OrderType.MARKET,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=self.order_quantity,
            )

            self.current_order = self.client.place_order(order_request)
            print(
                f"✓ Order placed successfully! Order ID: {self.current_order.order_id}"
            )

            # subscribe to order updates
            self.order_subscription_id = self.current_order.subscribe_updates(
                callback=self.on_order_update,
                config=OrderSubscriptionConfig(
                    polling_frequency_seconds=1.0,
                    retry_on_error=True,
                ),
            )
            print("📡 Subscribed to order status updates")
        except Exception as e:  # pylint: disable=broad-except
            print(f"❌ Failed to place order: {e}")
            self.order_placed = False

    def on_order_update(self, update: OrderUpdate) -> None:
        """Callback for order status updates."""
        print("\n📋 Order Update:")
        print(f"   Status: {update.old_status} → {update.new_status}")
        print(f"   Time: {update.timestamp}")

        if update.new_status == OrderStatus.FILLED:
            print("\n🎉 Order FILLED!")
            print(f"   Filled Quantity: {update.order.filled_quantity}")
            print(f"   Amount: ${update.order.notional_value:.2f}")
            print(f"   Average Price: ${update.order.average_price:.2f}")

            # stop price monitoring once order is filled
            if self.price_subscription_id:
                print("\n🛑 Stopping price monitoring...")
                self.client.price_stream.unsubscribe(self.price_subscription_id)
                self.price_subscription_id = None

        elif update.new_status == OrderStatus.CANCELLED:
            print("\n❌ Order CANCELLED")
            self.order_placed = False

        elif update.new_status == OrderStatus.REJECTED:
            print(f"\n⚠️ Order REJECTED: {update.order.reject_reason}")
            self.order_placed = False

    def start_monitoring(self) -> None:
        print(f"\n🔍 Starting price monitoring for {self.symbol}...")
        print(f"   Target: ${self.target_price:.2f}")
        print(
            f"   Action: Place {self.order_side.value} order when price is "
            f"{'<=' if self.order_side == OrderSide.BUY else '>='} target"
        )
        print(f"   Quantity: {self.order_quantity} shares\n")

        # subscribe to price updates
        instruments = [OrderInstrument(symbol=self.symbol, type=InstrumentType.EQUITY)]
        self.price_subscription_id = self.client.price_stream.subscribe(
            instruments=instruments,
            callback=self.on_price_change,
            config=SubscriptionConfig(
                polling_frequency_seconds=1.0,
                retry_on_error=True,
                max_retries=5,
            ),
        )

    def stop_monitoring(self) -> None:
        if self.price_subscription_id:
            self.client.price_stream.unsubscribe(self.price_subscription_id)
            print("✓ Price subscription stopped")

        if self.current_order and self.order_subscription_id:
            self.current_order.unsubscribe()
            print("✓ Order subscription stopped")


SYMBOL = "AAPL"
TARGET_PRICE = Decimal("150.00")
ORDER_QUANTITY = Decimal("1")


def main() -> None:
    """Main function to run the price-triggered order example."""
    print("=" * 60)
    print("Price-Triggered Order Example")
    print("=" * 60)
    print("\nThis example will:")
    print("1. Monitor the price of a stock")
    print("2. Place a market order when the price reaches a target")
    print("3. Track the order until it's filled")
    print("=" * 60)

    load_dotenv()

    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )
    config = PublicApiClientConfiguration(
        default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
    )
    client = PublicApiClient(auth_config=auth_config, config=config)

    bot = PriceTriggeredOrderBot(
        client=client,
        symbol=SYMBOL,
        target_price=TARGET_PRICE,
        order_quantity=ORDER_QUANTITY,
    )

    try:
        bot.start_monitoring()

        # run for a maximum time (2 minutes) or until order is filled
        max_runtime = 120
        start_time = time.time()

        print("\nMonitoring... (Press Ctrl+C to stop)\n")

        while time.time() - start_time < max_runtime:
            # check if order has been filled
            if bot.current_order:
                try:
                    # wait for the order to reach terminal status (with short timeout)
                    order = bot.current_order.wait_for_terminal_status(timeout=1)
                    if order.status == OrderStatus.FILLED:
                        print("\n✅ Order filled successfully! Exiting...")
                        break
                except WaitTimeoutError:
                    # order not yet in terminal status, continue monitoring
                    pass

            time.sleep(1)

        if time.time() - start_time >= max_runtime:
            print(f"\n⏱️ Maximum runtime of {max_runtime} seconds reached")
    except KeyboardInterrupt:
        print("\n\n Interrupted by user")
    except Exception as e:  # pylint: disable=broad-except
        print(f"\n❌ Error: {e}")
    finally:
        print("\nCleaning up...")
        bot.stop_monitoring()
        client.close()
        print("✓ Cleanup complete")


if __name__ == "__main__":
    main()
