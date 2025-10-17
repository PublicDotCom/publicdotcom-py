import asyncio
import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Dict, Optional, Callable, List

from .models.new_order import OrderUpdate, OrderUpdateCallback, OrderSubscriptionConfig
from .models.order import Order, OrderStatus


logger = logging.getLogger(__name__)


class OrderSubscription:
    def __init__(
        self,
        subscription_id: str,
        order_id: str,
        account_id: str,
        callback: OrderUpdateCallback,
        config: OrderSubscriptionConfig,
    ):
        self.id = subscription_id
        self.order_id = order_id
        self.account_id = account_id
        self.callback = callback
        self.config = config
        self.last_status: Optional[OrderStatus] = None
        self.is_active = True
        self.last_poll_time: float = 0
        self.last_order: Optional[Order] = None


class OrderSubscriptionManager:
    """
    Manages order status subscriptions and polling.

    Similar to PriceSubscriptionManager but focused on order updates.
    """

    def __init__(self, get_order_func: Callable[[str, str], Order]):
        """
        Initialize the OrderSubscriptionManager.

        Args:
            get_order_func: Function to fetch order details (order_id, account_id) -> Order
        """
        self.get_order_func = get_order_func
        self.default_config = OrderSubscriptionConfig()
        self.subscriptions: Dict[str, OrderSubscription] = {}
        self.order_to_subscription: Dict[str, str] = {}  # order_id -> subscription_id
        self.polling_task: Optional[asyncio.Task] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        """Start the polling loop if not already running."""
        if self.thread and self.thread.is_alive():
            return

        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

    def _run_event_loop(self) -> None:
        """Run the asyncio event loop in a separate thread."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.polling_task = self.loop.create_task(self._polling_loop())

        try:
            self.loop.run_until_complete(self.polling_task)
        except asyncio.CancelledError:
            pass
        finally:
            self.loop.close()

    async def _polling_loop(self) -> None:
        """Main polling loop that checks for order updates."""
        while not self._stop_event.is_set():
            try:
                await self._poll_all_subscriptions()

                # find minimum polling frequency across all active subscriptions
                min_frequency = self.default_config.polling_frequency_seconds
                with self._lock:
                    for sub in self.subscriptions.values():
                        if sub.is_active:
                            min_frequency = min(
                                min_frequency, sub.config.polling_frequency_seconds
                            )

                await asyncio.sleep(min_frequency)
            except (RuntimeError, ValueError, TypeError) as e:
                logger.error("Error in polling loop: %s", e)
                await asyncio.sleep(1)

    async def _poll_all_subscriptions(self) -> None:
        """Poll all active subscriptions for updates."""
        with self._lock:
            active_subscriptions = [
                sub for sub in self.subscriptions.values() if sub.is_active
            ]

        if not active_subscriptions:
            return

        current_time = time.time()

        for sub in active_subscriptions:
            # check if it's time to poll this subscription
            time_since_last_poll = current_time - sub.last_poll_time
            if time_since_last_poll >= sub.config.polling_frequency_seconds:
                await self._poll_subscription(sub)
                sub.last_poll_time = current_time

    async def _poll_subscription(self, subscription: OrderSubscription) -> None:
        """Poll a single subscription for order updates."""
        try:
            # fetch order with retry logic
            order = await self._fetch_order_with_retry(
                subscription.order_id, subscription.account_id, subscription.config
            )

            if not order:
                return

            # check for status change
            if subscription.last_status != order.status:
                update = OrderUpdate(
                    order_id=subscription.order_id,
                    account_id=subscription.account_id,
                    old_status=subscription.last_status,
                    new_status=order.status,
                    order=order,
                    timestamp=datetime.now(timezone.utc),
                )

                # update last known status
                subscription.last_status = order.status
                subscription.last_order = order

                # trigger callback
                await self._execute_callback(subscription.callback, update)

                # check if order reached terminal status
                terminal_statuses = [
                    OrderStatus.FILLED,
                    OrderStatus.CANCELLED,
                    OrderStatus.REJECTED,
                    OrderStatus.EXPIRED,
                    OrderStatus.REPLACED,
                ]
                if order.status in terminal_statuses:
                    # mark subscription as inactive (but don't remove it yet)
                    subscription.is_active = False
                    logger.info(
                        "Order %s reached terminal status %s, marking subscription as inactive",
                        subscription.order_id,
                        order.status,
                    )
        except Exception as e:  # pylint: disable=broad-except
            logger.error("Error polling order %s: %s", subscription.order_id, e)

    async def _fetch_order_with_retry(
        self, order_id: str, account_id: str, config: OrderSubscriptionConfig
    ) -> Optional[Order]:
        """Fetch order details with retry logic."""
        retries = 0
        backoff = 1

        while retries <= config.max_retries:
            try:
                if not self.loop:
                    return None
                # run the synchronous get_order in executor
                order = await self.loop.run_in_executor(
                    self.executor, self.get_order_func, order_id, account_id
                )
                return order
            except (ConnectionError, TimeoutError, ValueError, TypeError) as e:
                logger.error(
                    "Error fetching order %s (attempt %d): %s", order_id, retries + 1, e
                )

                if not config.retry_on_error or retries >= config.max_retries:
                    return None

                retries += 1
                if config.exponential_backoff:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    await asyncio.sleep(1)

        return None

    async def _execute_callback(
        self, callback: OrderUpdateCallback, update: OrderUpdate
    ) -> None:
        """Execute the callback function for an order update."""
        try:
            # check if callback is async
            if asyncio.iscoroutinefunction(callback):
                await callback(update)
            else:
                # run sync callback in executor
                if self.loop:
                    await self.loop.run_in_executor(self.executor, callback, update)
        except (RuntimeError, TypeError, ValueError) as e:
            logger.error("Error executing callback: %s", e)

    def subscribe_order(
        self,
        order_id: str,
        account_id: str,
        callback: OrderUpdateCallback,
        config: Optional[OrderSubscriptionConfig] = None,
    ) -> str:
        """
        Subscribe to updates for a specific order.

        Args:
            order_id: The order ID to monitor
            account_id: The account ID
            callback: Function to call when order status changes
            config: Optional subscription configuration

        Returns:
            Subscription ID
        """
        subscription_id = str(uuid.uuid4())
        config = config or self.default_config

        subscription = OrderSubscription(
            subscription_id=subscription_id,
            order_id=order_id,
            account_id=account_id,
            callback=callback,
            config=config,
        )

        with self._lock:
            # remove any existing subscription for this order
            if order_id in self.order_to_subscription:
                old_sub_id = self.order_to_subscription[order_id]
                if old_sub_id in self.subscriptions:
                    del self.subscriptions[old_sub_id]

            # add new subscription
            self.subscriptions[subscription_id] = subscription
            self.order_to_subscription[order_id] = subscription_id

        # start polling if not already started
        self.start()

        logger.info("Created subscription %s for order %s", subscription_id, order_id)

        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """
        Remove a subscription.

        Args:
            subscription_id: The subscription ID to remove

        Returns:
            True if removed, False if not found
        """
        with self._lock:
            if subscription_id not in self.subscriptions:
                return False

            subscription = self.subscriptions[subscription_id]

            # remove from order mapping
            if subscription.order_id in self.order_to_subscription:
                del self.order_to_subscription[subscription.order_id]

            # remove subscription
            del self.subscriptions[subscription_id]

            logger.info(
                "Removed subscription %s for order %s",
                subscription_id,
                subscription.order_id,
            )

            return True

    def unsubscribe_all(self) -> None:
        """Remove all subscriptions."""
        with self._lock:
            self.subscriptions.clear()
            self.order_to_subscription.clear()
        logger.info("Removed all order subscriptions")

    def get_active_subscriptions(self) -> List[str]:
        """
        Get list of active subscription IDs.

        Returns:
            List of subscription IDs that are currently active
        """
        with self._lock:
            return [
                sub_id for sub_id, sub in self.subscriptions.items() if sub.is_active
            ]

    def get_subscription_info(self, subscription_id: str) -> Optional[Dict]:
        """
        Get information about a specific subscription.

        Args:
            subscription_id: The subscription ID

        Returns:
            Dictionary with subscription info or None if not found
        """
        with self._lock:
            if subscription_id not in self.subscriptions:
                return None

            sub = self.subscriptions[subscription_id]
            return {
                "id": sub.id,
                "order_id": sub.order_id,
                "account_id": sub.account_id,
                "is_active": sub.is_active,
                "last_status": sub.last_status.value if sub.last_status else None,
                "polling_frequency": sub.config.polling_frequency_seconds,
                "retry_on_error": sub.config.retry_on_error,
                "max_retries": sub.config.max_retries,
            }

    def stop(self) -> None:
        """Stop the polling loop and cleanup resources."""
        self._stop_event.set()

        if self.polling_task and self.loop and not self.loop.is_closed():
            try:
                self.loop.call_soon_threadsafe(self.polling_task.cancel)
            except RuntimeError:
                pass  # loop already closed

        if self.thread:
            self.thread.join(timeout=5)

        self.executor.shutdown(wait=False)

    def __del__(self) -> None:
        try:
            self.stop()
        except Exception:  # pylint: disable=broad-except
            # must catch all exceptions in __del__ to prevent interpreter errors
            pass
