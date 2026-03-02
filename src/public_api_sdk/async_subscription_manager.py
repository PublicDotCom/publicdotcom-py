"""Async-native price subscription manager using asyncio tasks."""

import asyncio
import logging
import uuid
from typing import Any, Awaitable, Callable, Dict, List, Optional, Set

from .models import (
    OrderInstrument,
    PriceChange,
    PriceChangeCallback,
    Quote,
    Subscription,
    SubscriptionConfig,
    SubscriptionInfo,
    SubscriptionStatus,
)

logger = logging.getLogger(__name__)

# Type alias for the async get-quotes function injected by the client
AsyncGetQuotesFunc = Callable[[List[OrderInstrument]], Awaitable[List[Quote]]]


class AsyncPriceSubscriptionManager:
    """Async-native price subscription manager.

    Each subscription runs as its own asyncio Task in the caller's event loop —
    no background threads or secondary event loops are needed.

    Usage::

        async with AsyncPublicApiClient(config) as client:
            sub_id = await client.price_stream.subscribe(
                instruments=[OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)],
                callback=my_async_callback,
            )
    """

    def __init__(self, get_quotes_func: AsyncGetQuotesFunc) -> None:
        self.get_quotes_func = get_quotes_func
        self.default_config = SubscriptionConfig()
        self._subscriptions: Dict[str, Subscription] = {}
        self._tasks: Dict[str, "asyncio.Task[Any]"] = {}
        self._last_quotes: Dict[str, Quote] = {}

    async def subscribe(
        self,
        instruments: List[OrderInstrument],
        callback: PriceChangeCallback,
        config: Optional[SubscriptionConfig] = None,
    ) -> str:
        """Subscribe to price changes for the given instruments.

        Args:
            instruments: Instruments to monitor
            callback: Called whenever a price change is detected (sync or async)
            config: Optional polling/retry configuration

        Returns:
            Subscription ID
        """
        if not instruments:
            raise ValueError("At least one instrument must be provided")

        subscription_id = str(uuid.uuid4())
        resolved_config = config or self.default_config

        subscription = Subscription(
            id=subscription_id,
            instruments=instruments,
            status=SubscriptionStatus.ACTIVE,
            config=resolved_config,
            callback=callback,
        )
        self._subscriptions[subscription_id] = subscription

        task = asyncio.create_task(self._poll_loop(subscription_id))
        self._tasks[subscription_id] = task

        return subscription_id

    async def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription and cancel its polling task.

        Args:
            subscription_id: ID returned from subscribe()

        Returns:
            True if removed, False if not found
        """
        if subscription_id not in self._subscriptions:
            return False

        sub = self._subscriptions.pop(subscription_id)

        task = self._tasks.pop(subscription_id, None)
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        # evict cached quotes for instruments no longer referenced by any subscription
        remaining_keys: Set[str] = set()
        for s in self._subscriptions.values():
            for inst in s.instruments:
                remaining_keys.add(f"{inst.symbol}_{inst.type.value}")

        for inst in sub.instruments:
            key = f"{inst.symbol}_{inst.type.value}"
            if key not in remaining_keys:
                self._last_quotes.pop(key, None)

        return True

    async def unsubscribe_all(self) -> None:
        """Remove all subscriptions and cancel all polling tasks."""
        for sub_id in list(self._subscriptions.keys()):
            await self.unsubscribe(sub_id)

    def pause_subscription(self, subscription_id: str) -> bool:
        """Pause polling for a subscription (task keeps running but skips fetches).

        Returns:
            True if the subscription was found and paused, False otherwise
        """
        if subscription_id in self._subscriptions:
            self._subscriptions[subscription_id].status = SubscriptionStatus.PAUSED
            return True
        return False

    def resume_subscription(self, subscription_id: str) -> bool:
        """Resume a paused subscription.

        Returns:
            True if the subscription was found and resumed, False otherwise
        """
        if subscription_id in self._subscriptions:
            self._subscriptions[subscription_id].status = SubscriptionStatus.ACTIVE
            return True
        return False

    def set_polling_frequency(
        self, subscription_id: str, frequency_seconds: float
    ) -> bool:
        """Update the polling frequency for a subscription.

        Args:
            subscription_id: Target subscription
            frequency_seconds: New frequency (0.1 – 60 seconds)

        Returns:
            True if updated, False if subscription not found
        """
        if frequency_seconds < 0.1 or frequency_seconds > 60:
            raise ValueError("Polling frequency must be between 0.1 and 60 seconds")

        if subscription_id in self._subscriptions:
            self._subscriptions[
                subscription_id
            ].config.polling_frequency_seconds = frequency_seconds
            return True
        return False

    def get_active_subscriptions(self) -> List[str]:
        """Return IDs of all currently active subscriptions."""
        return [
            sub_id
            for sub_id, sub in self._subscriptions.items()
            if sub.status == SubscriptionStatus.ACTIVE
        ]

    def get_subscription_info(self, subscription_id: str) -> Optional[SubscriptionInfo]:
        """Return metadata for a specific subscription, or None if not found."""
        if subscription_id in self._subscriptions:
            sub = self._subscriptions[subscription_id]
            return SubscriptionInfo(
                id=sub.id,
                instruments=sub.instruments,
                status=sub.status.value,
                polling_frequency=sub.config.polling_frequency_seconds,
                retry_on_error=sub.config.retry_on_error,
                max_retries=sub.config.max_retries,
            )
        return None

    async def stop(self) -> None:
        """Cancel all polling tasks and clear all subscriptions."""
        await self.unsubscribe_all()

    # ------------------------------------------------------------------ #
    # Internal polling logic                                               #
    # ------------------------------------------------------------------ #

    async def _poll_loop(self, subscription_id: str) -> None:
        """Per-subscription polling loop, runs as an asyncio Task."""
        while True:
            sub = self._subscriptions.get(subscription_id)
            if not sub:
                break

            if sub.status == SubscriptionStatus.ACTIVE:
                await self._poll_subscription(sub)

            # re-read config so frequency changes take effect immediately
            sub = self._subscriptions.get(subscription_id)
            if not sub:
                break

            await asyncio.sleep(sub.config.polling_frequency_seconds)

    async def _poll_subscription(self, subscription: Subscription) -> None:
        """Fetch quotes and fire callbacks for changed prices."""
        try:
            quotes = await self._fetch_quotes_with_retry(
                subscription.instruments, subscription.config
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Error polling subscription %s: %s", subscription.id, exc)
            return

        if not quotes:
            return

        quote_map = {
            f"{q.instrument.symbol}_{q.instrument.type.value}": q for q in quotes
        }

        for instrument in subscription.instruments:
            key = f"{instrument.symbol}_{instrument.type.value}"
            new_quote = quote_map.get(key)
            if new_quote is None:
                continue

            old_quote = self._last_quotes.get(key)
            if old_quote is not None:
                price_change = self._detect_price_change(instrument, old_quote, new_quote)
                if price_change and subscription.callback:
                    await self._execute_callback(subscription.callback, price_change)

            self._last_quotes[key] = new_quote

    async def _fetch_quotes_with_retry(
        self,
        instruments: List[OrderInstrument],
        config: SubscriptionConfig,
    ) -> List[Quote]:
        """Call get_quotes_func with exponential backoff retry."""
        retries = 0
        backoff = 1.0

        while retries <= config.max_retries:
            try:
                return await self.get_quotes_func(instruments)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error(
                    "Error fetching quotes (attempt %d): %s", retries + 1, exc
                )
                if not config.retry_on_error or retries >= config.max_retries:
                    return []

                retries += 1
                if config.exponential_backoff:
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    await asyncio.sleep(1)

        return []

    def _detect_price_change(
        self, instrument: OrderInstrument, old_quote: Quote, new_quote: Quote
    ) -> Optional[PriceChange]:
        changed_fields = []
        if old_quote.last != new_quote.last:
            changed_fields.append("last")
        if old_quote.bid != new_quote.bid:
            changed_fields.append("bid")
        if old_quote.ask != new_quote.ask:
            changed_fields.append("ask")

        if changed_fields:
            return PriceChange(
                instrument=instrument,
                old_quote=old_quote,
                new_quote=new_quote,
                changed_fields=changed_fields,
            )
        return None

    async def _execute_callback(
        self, callback: PriceChangeCallback, price_change: PriceChange
    ) -> None:
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(price_change)
            else:
                callback(price_change)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.error("Error executing price callback: %s", exc)
