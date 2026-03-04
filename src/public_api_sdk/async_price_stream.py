"""Async price stream — thin public facade over AsyncPriceSubscriptionManager."""

from typing import List, Optional

from .async_subscription_manager import AsyncPriceSubscriptionManager
from .models import (
    OrderInstrument,
    PriceChangeCallback,
    SubscriptionConfig,
    SubscriptionInfo,
)


class AsyncPriceStream:
    """Async facade for subscribing to real-time price updates.

    Accessed via ``AsyncPublicApiClient.price_stream``.  Methods that create
    or remove subscriptions are coroutines; read-only helpers remain synchronous.

    Example::

        async with AsyncPublicApiClient(config) as client:
            sub_id = await client.price_stream.subscribe(
                instruments=[OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)],
                callback=my_callback,
                config=SubscriptionConfig(polling_frequency_seconds=2.0),
            )
            ...
            await client.price_stream.unsubscribe(sub_id)
    """

    def __init__(self, subscription_manager: AsyncPriceSubscriptionManager) -> None:
        self._manager = subscription_manager

    async def subscribe(
        self,
        instruments: List[OrderInstrument],
        callback: PriceChangeCallback,
        config: Optional[SubscriptionConfig] = None,
    ) -> str:
        """Subscribe to price changes for the specified instruments.

        Args:
            instruments: Instruments to monitor
            callback: Called on every detected price change (sync or async)
            config: Optional polling/retry configuration

        Returns:
            Subscription ID for later management
        """
        return await self._manager.subscribe(instruments, callback, config)

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription and stop its polling task.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if removed, False if not found
        """
        return await self._manager.unsubscribe(subscription_id)

    async def unsubscribe_all(self) -> None:
        """Remove all active price subscriptions."""
        await self._manager.unsubscribe_all()

    def set_polling_frequency(
        self, subscription_id: str, frequency_seconds: float
    ) -> bool:
        """Update the polling interval for a subscription.

        Args:
            subscription_id: Target subscription
            frequency_seconds: New frequency in seconds (0.1 – 60)

        Returns:
            True if updated, False if subscription not found

        Raises:
            ValueError: If frequency_seconds is outside the valid range
        """
        return self._manager.set_polling_frequency(subscription_id, frequency_seconds)

    def get_active_subscriptions(self) -> List[str]:
        """Return IDs of all currently active subscriptions."""
        return self._manager.get_active_subscriptions()

    def get_subscription_info(self, subscription_id: str) -> Optional[SubscriptionInfo]:
        """Return detailed information about a subscription.

        Args:
            subscription_id: The subscription to query

        Returns:
            SubscriptionInfo, or None if not found
        """
        return self._manager.get_subscription_info(subscription_id)

    def pause(self, subscription_id: str) -> bool:
        """Pause polling for a subscription without removing it.

        Returns:
            True if paused, False if not found
        """
        return self._manager.pause_subscription(subscription_id)

    def resume(self, subscription_id: str) -> bool:
        """Resume a previously paused subscription.

        Returns:
            True if resumed, False if not found
        """
        return self._manager.resume_subscription(subscription_id)
