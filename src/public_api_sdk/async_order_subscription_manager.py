"""Async-native order subscription manager using asyncio tasks."""

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .models.new_order import OrderSubscriptionConfig, OrderUpdate, OrderUpdateCallback
from .models.order import Order, OrderStatus

logger = logging.getLogger(__name__)

AsyncGetOrderFunc = Callable[[str, str], Awaitable[Order]]

_TERMINAL_STATUSES = {
    OrderStatus.FILLED,
    OrderStatus.CANCELLED,
    OrderStatus.REJECTED,
    OrderStatus.EXPIRED,
    OrderStatus.REPLACED,
}


class _AsyncOrderSubscription:
    """Internal subscription record."""

    def __init__(
        self,
        subscription_id: str,
        order_id: str,
        account_id: str,
        callback: OrderUpdateCallback,
        config: OrderSubscriptionConfig,
    ) -> None:
        self.id = subscription_id
        self.order_id = order_id
        self.account_id = account_id
        self.callback = callback
        self.config = config
        self.last_status: Optional[OrderStatus] = None
        self.last_order: Optional[Order] = None
        self.is_active = True


class AsyncOrderSubscriptionManager:
    """Async-native order subscription manager.

    Each watched order runs as its own asyncio Task, polling for status changes
    entirely within the caller's event loop — no background threads required.
    """

    def __init__(self, get_order_func: AsyncGetOrderFunc) -> None:
        self.get_order_func = get_order_func
        self.default_config = OrderSubscriptionConfig()
        self._subscriptions: Dict[str, _AsyncOrderSubscription] = {}
        self._order_to_subscription: Dict[str, str] = {}
        self._tasks: Dict[str, "asyncio.Task[Any]"] = {}

    async def subscribe_order(
        self,
        order_id: str,
        account_id: str,
        callback: OrderUpdateCallback,
        config: Optional[OrderSubscriptionConfig] = None,
    ) -> str:
        """Subscribe to status updates for a specific order.

        Args:
            order_id: The order ID to monitor
            account_id: The account that owns the order
            callback: Called on each status transition (sync or async)
            config: Optional polling/retry configuration

        Returns:
            Subscription ID
        """
        subscription_id = str(uuid.uuid4())
        resolved_config = config or self.default_config

        # replace any existing subscription for this order
        if order_id in self._order_to_subscription:
            old_sub_id = self._order_to_subscription[order_id]
            await self.unsubscribe(old_sub_id)

        sub = _AsyncOrderSubscription(
            subscription_id=subscription_id,
            order_id=order_id,
            account_id=account_id,
            callback=callback,
            config=resolved_config,
        )
        self._subscriptions[subscription_id] = sub
        self._order_to_subscription[order_id] = subscription_id

        task = asyncio.create_task(self._poll_loop(subscription_id))
        self._tasks[subscription_id] = task

        logger.info("Created subscription %s for order %s", subscription_id, order_id)
        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription and cancel its polling task.

        Returns:
            True if removed, False if not found
        """
        if subscription_id not in self._subscriptions:
            return False

        sub = self._subscriptions.pop(subscription_id)
        self._order_to_subscription.pop(sub.order_id, None)

        task = self._tasks.pop(subscription_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        logger.info(
            "Removed subscription %s for order %s", subscription_id, sub.order_id
        )
        return True

    async def unsubscribe_all(self) -> None:
        """Remove all order subscriptions."""
        for sub_id in list(self._subscriptions.keys()):
            await self.unsubscribe(sub_id)
        logger.info("Removed all order subscriptions")

    def get_active_subscriptions(self) -> List[str]:
        """Return IDs of subscriptions whose orders have not yet reached a terminal status."""
        return [
            sub_id
            for sub_id, sub in self._subscriptions.items()
            if sub.is_active
        ]

    def get_subscription_info(self, subscription_id: str) -> Optional[Dict[str, Any]]:
        """Return metadata for a specific subscription, or None if not found."""
        if subscription_id not in self._subscriptions:
            return None

        sub = self._subscriptions[subscription_id]
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

    async def stop(self) -> None:
        """Cancel all polling tasks and clear all subscriptions."""
        await self.unsubscribe_all()

    # ------------------------------------------------------------------ #
    # Internal polling logic                                               #
    # ------------------------------------------------------------------ #

    async def _poll_loop(self, subscription_id: str) -> None:
        """Per-order polling loop, runs as an asyncio Task."""
        while True:
            sub = self._subscriptions.get(subscription_id)
            if not sub or not sub.is_active:
                break

            await self._poll_subscription(sub)

            sub = self._subscriptions.get(subscription_id)
            if not sub or not sub.is_active:
                break

            await asyncio.sleep(sub.config.polling_frequency_seconds)

    async def _poll_subscription(self, subscription: _AsyncOrderSubscription) -> None:
        """Fetch the latest order state and fire the callback on status changes."""
        try:
            order = await self._fetch_order_with_retry(
                subscription.order_id,
                subscription.account_id,
                subscription.config,
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Error polling order %s: %s", subscription.order_id, exc)
            return

        if not order:
            return

        if subscription.last_status != order.status:
            update = OrderUpdate(
                order_id=subscription.order_id,
                account_id=subscription.account_id,
                old_status=subscription.last_status,
                new_status=order.status,
                order=order,
                timestamp=datetime.now(timezone.utc),
            )
            subscription.last_status = order.status
            subscription.last_order = order

            await self._execute_callback(subscription.callback, update)

            if order.status in _TERMINAL_STATUSES:
                subscription.is_active = False
                logger.info(
                    "Order %s reached terminal status %s, stopping polling",
                    subscription.order_id,
                    order.status,
                )

    async def _fetch_order_with_retry(
        self,
        order_id: str,
        account_id: str,
        config: OrderSubscriptionConfig,
    ) -> Optional[Order]:
        """Fetch order details with exponential backoff retry."""
        retries = 0
        backoff = 1.0

        while retries <= config.max_retries:
            try:
                return await self.get_order_func(order_id, account_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Error fetching order %s (attempt %d): %s",
                    order_id,
                    retries + 1,
                    exc,
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
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(update)
            else:
                callback(update)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Error executing order callback: %s", exc)
