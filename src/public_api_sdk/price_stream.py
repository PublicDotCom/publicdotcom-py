from typing import List, Optional

from .models import (
    OrderInstrument,
    PriceChangeCallback,
    SubscriptionConfig,
    SubscriptionInfo,
)
from .subscription_manager import PriceSubscriptionManager


class PriceStream:
    def __init__(self, subscription_manager: PriceSubscriptionManager):
        """Initialize the PriceStream.

        Args:
            subscription_manager: The underlying subscription manager
        """
        self._manager = subscription_manager

    def subscribe(
        self,
        instruments: List[OrderInstrument],
        callback: PriceChangeCallback,
        config: Optional[SubscriptionConfig] = None,
    ) -> str:
        """Subscribe to price changes for specified instruments.

        This method sets up a subscription that polls for quote updates at the
        specified frequency and triggers the callback only when price changes
        are detected.

        Args:
            instruments: List of instruments to monitor for price changes
            callback: Function to call when a price change is detected.
                    Can be sync or async function.
            config: Optional subscription configuration (polling frequency, retry settings)

        Returns:
            Subscription ID that can be used to manage the subscription

        Example:
            ```python
            def on_price_change(price_change: PriceChange):
                print(f"{price_change.instrument.symbol}: "
                    f"{price_change.old_quote.last} -> {price_change.new_quote.last}")

            client.price_stream.subscribe(
                instruments=[OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)],
                callback=on_price_change,
                config=SubscriptionConfig(polling_frequency_seconds=2.0)
            )
            ```
        """
        return self._manager.subscribe(instruments, callback, config)

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a specific price subscription.

        Args:
            subscription_id: The ID returned from subscribe

        Returns:
            True if the subscription was found and removed, False otherwise
        """
        return self._manager.unsubscribe(subscription_id)

    def unsubscribe_all(self) -> None:
        """Remove all active price subscriptions."""
        self._manager.unsubscribe_all()

    def set_polling_frequency(
        self, subscription_id: str, frequency_seconds: float
    ) -> bool:
        """Update the polling frequency for a specific subscription.

        Args:
            subscription_id: The ID of the subscription to update
            frequency_seconds: New polling frequency in seconds (0.1 to 60)

        Returns:
            True if the subscription was found and updated, False otherwise

        Raises:
            ValueError: If frequency_seconds is outside the valid range
        """
        return self._manager.set_polling_frequency(subscription_id, frequency_seconds)

    def get_active_subscriptions(self) -> List[str]:
        """Get a list of all active subscription IDs.

        Returns:
            List of subscription IDs that are currently active
        """
        return self._manager.get_active_subscriptions()

    def get_subscription_info(self, subscription_id: str) -> Optional[SubscriptionInfo]:
        """Get detailed information about a specific subscription.

        Args:
            subscription_id: The ID of the subscription

        Returns:
            SubscriptionInfo with subscription details or None if not found
        """
        return self._manager.get_subscription_info(subscription_id)

    def pause(self, subscription_id: str) -> bool:
        """Pause a specific subscription.

        Args:
            subscription_id: The ID of the subscription to pause

        Returns:
            True if the subscription was found and paused, False otherwise
        """
        return self._manager.pause_subscription(subscription_id)

    def resume(self, subscription_id: str) -> bool:
        """Resume a paused subscription.

        Args:
            subscription_id: The ID of the subscription to resume

        Returns:
            True if the subscription was found and resumed, False otherwise
        """
        return self._manager.resume_subscription(subscription_id)
