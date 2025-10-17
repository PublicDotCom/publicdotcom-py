import asyncio
import os
import time
import uuid
from decimal import Decimal

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
    OrderUpdate,
    OrderSubscriptionConfig,
    WaitTimeoutError,
)


def on_order_update(update: OrderUpdate) -> None:
    print(f"📊 Order Update: {update.order_id}")
    print(f"   Status: {update.old_status} -> {update.new_status}")
    print(f"   Time: {update.timestamp}")

    if update.new_status == OrderStatus.FILLED:
        print(f"   ✅ Order filled! Average price: ${update.order.average_price}")
    elif update.new_status == OrderStatus.CANCELLED:
        print("   ❌ Order cancelled")
    elif update.new_status == OrderStatus.REJECTED:
        print(f"   ⚠️ Order rejected: {update.order.reject_reason}")


async def async_order_callback(update: OrderUpdate) -> None:
    """Async callback function for order status updates."""
    await asyncio.sleep(0.1)  # Simulate async processing
    print(f"🔄 Async Update: Order {update.order_id} is now {update.new_status}")


def example_subscription_with_callback() -> None:
    print("\n=== Example 1: Order Subscription with Callback ===\n")

    load_dotenv()

    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )

    client = PublicApiClient(
        auth_config=auth_config,
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )

    try:
        print("Placing order...")
        new_order = client.place_order(
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(
                    symbol="AAPL",
                    type=InstrumentType.EQUITY,
                ),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=1,
                limit_price=Decimal("150.00"),  # Low price to avoid immediate fill
            ),
        )
        print(f"Order placed: {new_order.order_id}\n")

        # subscribe to updates with custom configuration
        config = OrderSubscriptionConfig(
            polling_frequency_seconds=2.0,  # check every 2 seconds
            retry_on_error=True,
            max_retries=3,
        )

        subscription_id = new_order.subscribe_updates(
            callback=on_order_update, config=config
        )
        print(f"Subscribed to order updates (ID: {subscription_id})\n")

        # let it run for a bit
        print("Monitoring order for 10 seconds...")
        time.sleep(10)

        # cancel the order
        print("\nCancelling order...")
        new_order.cancel()

        # wait a bit more to see the cancellation update
        time.sleep(3)

        # unsubscribe
        new_order.unsubscribe()
        print("Unsubscribed from order updates")
    finally:
        client.close()


def example_synchronous_wait() -> None:
    """Example using synchronous wait methods."""
    print("\n=== Example 2: Synchronous Wait for Order Status ===\n")

    load_dotenv()

    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )

    client = PublicApiClient(
        auth_config=auth_config,
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )

    try:
        # place an order with a price likely to fill
        print("Placing market order...")
        new_order = client.place_order(
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(
                    symbol="AAPL",
                    type=InstrumentType.EQUITY,
                ),
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=1,
            ),
        )
        print(f"Order placed: {new_order.order_id}\n")

        # wait for the order to reach terminal status
        print("Waiting for order to complete (max 30 seconds)...")
        try:
            order = new_order.wait_for_terminal_status(timeout=30)
            print(f"✅ Order completed with status: {order.status}")

            if order.status == OrderStatus.FILLED:
                print(f"   Filled quantity: {order.filled_quantity}")
                print(f"   Average price: ${order.average_price}")
            elif order.status == OrderStatus.REJECTED:
                print(f"   Reject reason: {order.reject_reason}")
        except WaitTimeoutError as e:
            print(f"⏱️ Timeout: {e}")
            # get current status
            status = new_order.get_status()
            print(f"Current status: {status}")
    finally:
        client.close()


def example_async_callback() -> None:
    print("\n=== Example 3: Async Callback ===\n")

    load_dotenv()

    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    auth_config = ApiKeyAuthConfig(
        api_secret_key=api_secret_key, validity_minutes=15
    )

    client = PublicApiClient(
        auth_config=auth_config,
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )

    try:
        print("Placing order...")
        new_order = client.place_order(
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(
                    symbol="AAPL",
                    type=InstrumentType.EQUITY,
                ),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=1,
                limit_price=Decimal("140.00"),
            ),
        )
        print(f"Order placed: {new_order.order_id}\n")

        # subscribe with async callback
        subscription_id = new_order.subscribe_updates(
            callback=async_order_callback,
            config=OrderSubscriptionConfig(polling_frequency_seconds=1.5),
        )
        print(f"Subscribed with async callback (ID: {subscription_id})\n")

        # monitor for a bit
        print("Monitoring order for 5 seconds...")
        time.sleep(5)

        # cancel and wait for confirmation
        print("\nCancelling order and waiting for confirmation...")
        new_order.cancel()

        try:
            new_order.wait_for_status(OrderStatus.CANCELLED, timeout=10)
            print("✅ Order successfully cancelled")
        except WaitTimeoutError:
            print("❌ Order cancellation timeout")
    finally:
        client.close()


def main() -> None:
    try:
        # Example 1: Callback-based subscription
        example_subscription_with_callback()

        # Example 2: Synchronous wait
        example_synchronous_wait()

        # Example 3: Async callback
        example_async_callback()
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")


if __name__ == "__main__":
    main()
