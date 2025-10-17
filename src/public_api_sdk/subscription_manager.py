import asyncio
import logging
import threading
import time
import uuid
from typing import Dict, List, Optional, Set, Callable
from concurrent.futures import ThreadPoolExecutor

from .models import (
    OrderInstrument,
    Quote,
    PriceChange,
    SubscriptionConfig,
    Subscription,
    SubscriptionInfo,
    SubscriptionStatus,
    PriceChangeCallback,
)


logger = logging.getLogger(__name__)


class PriceSubscriptionManager:
    def __init__(self, get_quotes_func: Callable[[List[OrderInstrument]], List[Quote]]):
        self.get_quotes_func = get_quotes_func
        self.default_config = SubscriptionConfig()
        self.subscriptions: Dict[str, Subscription] = {}
        self.instrument_to_subscription: Dict[str, Set[str]] = {}
        self.last_quotes: Dict[str, Quote] = {}
        # track last poll time per subscription
        self.last_poll_times: Dict[str, float] = {}
        self.polling_task: Optional[asyncio.Task] = None
        self.loop: Optional[asyncio.AbstractEventLoop] = None
        self.thread: Optional[threading.Thread] = None
        self.executor = ThreadPoolExecutor(max_workers=10)
        self._stop_event = threading.Event()
        self._lock = threading.Lock()

    def start(self) -> None:
        if self.thread and self.thread.is_alive():
            return

        self._stop_event.clear()
        self.thread = threading.Thread(target=self._run_event_loop, daemon=True)
        self.thread.start()

    def _run_event_loop(self) -> None:
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
        while not self._stop_event.is_set():
            try:
                await self._poll_all_subscriptions()

                # Find minimum polling frequency across all active subscriptions
                min_frequency = self.default_config.polling_frequency_seconds
                with self._lock:
                    for sub in self.subscriptions.values():
                        if sub.status == SubscriptionStatus.ACTIVE:
                            min_frequency = min(
                                min_frequency, sub.config.polling_frequency_seconds
                            )

                await asyncio.sleep(min_frequency)
            except (RuntimeError, ValueError, TypeError) as e:
                logger.error("Error in polling loop: %s", e)
                await asyncio.sleep(1)

    async def _poll_all_subscriptions(self) -> None:
        with self._lock:
            active_subscriptions = [
                sub
                for sub in self.subscriptions.values()
                if sub.status == SubscriptionStatus.ACTIVE
            ]

        if not active_subscriptions:
            return

        # group instruments by subscription config for batch processing
        config_groups: Dict[float, List[Subscription]] = {}
        for sub in active_subscriptions:
            freq = sub.config.polling_frequency_seconds
            if freq not in config_groups:
                config_groups[freq] = []
            config_groups[freq].append(sub)

        # process each config group
        for frequency, subs in config_groups.items():
            # check if it's time to poll this group
            current_time = time.time()
            should_poll = any(
                sub.id not in self.last_poll_times
                or (current_time - self.last_poll_times.get(sub.id, 0)) >= frequency
                for sub in subs
            )

            if should_poll:
                await self._poll_subscription_group(subs)
                for sub in subs:
                    self.last_poll_times[sub.id] = current_time

    async def _poll_subscription_group(self, subscriptions: List[Subscription]) -> None:
        # collect all unique instruments
        all_instruments = []
        seen = set()
        for sub in subscriptions:
            for instrument in sub.instruments:
                key = f"{instrument.symbol}_{instrument.type.value}"
                if key not in seen:
                    seen.add(key)
                    all_instruments.append(instrument)

        if not all_instruments:
            return

        # fetch quotes with retry logic
        quotes = await self._fetch_quotes_with_retry(
            all_instruments, subscriptions[0].config
        )

        if not quotes:
            return

        # create a map for quick lookup
        quote_map = {}
        for quote in quotes:
            key = f"{quote.instrument.symbol}_{quote.instrument.type.value}"
            quote_map[key] = quote

        # check for price changes and trigger callbacks
        for sub in subscriptions:
            for instrument in sub.instruments:
                key = f"{instrument.symbol}_{instrument.type.value}"
                if key in quote_map:
                    new_quote = quote_map[key]
                    old_quote = self.last_quotes.get(key)

                    if old_quote:
                        price_change = self._detect_price_change(
                            instrument, old_quote, new_quote
                        )
                        if price_change and sub.callback:
                            await self._execute_callback(sub.callback, price_change)

                    self.last_quotes[key] = new_quote

    async def _fetch_quotes_with_retry(
        self, instruments: List[OrderInstrument], config: SubscriptionConfig
    ) -> List[Quote]:
        retries = 0
        backoff = 1

        while retries <= config.max_retries:
            try:
                if not self.loop:
                    return []
                # run the synchronous get_quotes in executor
                quotes = await self.loop.run_in_executor(
                    self.executor, self.get_quotes_func, instruments
                )
                return quotes
            except (ConnectionError, TimeoutError, ValueError, TypeError) as e:
                logger.error("Error fetching quotes (attempt %d): %s", retries + 1, e)

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

        # check last price
        if old_quote.last != new_quote.last:
            changed_fields.append("last")

        # check bid
        if old_quote.bid != new_quote.bid:
            changed_fields.append("bid")

        # check ask
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
            # check if callback is async
            if asyncio.iscoroutinefunction(callback):
                await callback(price_change)
            else:
                # run sync callback in executor
                if self.loop:
                    await self.loop.run_in_executor(
                        self.executor, callback, price_change
                    )
        except (RuntimeError, TypeError, ValueError) as e:
            logger.error("Error executing callback: %s", e)

    def subscribe(
        self,
        instruments: List[OrderInstrument],
        callback: PriceChangeCallback,
        config: Optional[SubscriptionConfig] = None,
    ) -> str:
        if not instruments:
            raise ValueError("At least one instrument must be provided")

        subscription_id = str(uuid.uuid4())

        config = config or self.default_config

        subscription = Subscription(
            id=subscription_id,
            instruments=instruments,
            status=SubscriptionStatus.ACTIVE,
            config=config,
            callback=callback,
        )

        with self._lock:
            self.subscriptions[subscription_id] = subscription

            # update instrument mapping
            for instrument in instruments:
                key = f"{instrument.symbol}_{instrument.type.value}"
                if key not in self.instrument_to_subscription:
                    self.instrument_to_subscription[key] = set()
                self.instrument_to_subscription[key].add(subscription_id)

        # start polling if not already started
        self.start()

        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id not in self.subscriptions:
                return False

            subscription = self.subscriptions[subscription_id]

            # remove from instrument mapping
            for instrument in subscription.instruments:
                key = f"{instrument.symbol}_{instrument.type.value}"
                if key in self.instrument_to_subscription:
                    self.instrument_to_subscription[key].discard(subscription_id)
                    if not self.instrument_to_subscription[key]:
                        del self.instrument_to_subscription[key]
                        # remove cached quote if no more subscriptions
                        if key in self.last_quotes:
                            del self.last_quotes[key]

            # remove subscription
            del self.subscriptions[subscription_id]

            # clean up poll time tracking
            if subscription_id in self.last_poll_times:
                del self.last_poll_times[subscription_id]

            return True

    def unsubscribe_all(self) -> None:
        with self._lock:
            self.subscriptions.clear()
            self.instrument_to_subscription.clear()
            self.last_quotes.clear()
            self.last_poll_times.clear()

    def pause_subscription(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id in self.subscriptions:
                self.subscriptions[subscription_id].status = SubscriptionStatus.PAUSED
                return True
            return False

    def resume_subscription(self, subscription_id: str) -> bool:
        with self._lock:
            if subscription_id in self.subscriptions:
                self.subscriptions[subscription_id].status = SubscriptionStatus.ACTIVE
                return True
            return False

    def set_polling_frequency(
        self, subscription_id: str, frequency_seconds: float
    ) -> bool:
        if frequency_seconds < 0.1 or frequency_seconds > 60:
            raise ValueError("Polling frequency must be between 0.1 and 60 seconds")

        with self._lock:
            if subscription_id in self.subscriptions:
                self.subscriptions[subscription_id].config.polling_frequency_seconds = (
                    frequency_seconds
                )
                return True
            return False

    def get_active_subscriptions(self) -> List[str]:
        with self._lock:
            return [
                sub_id
                for sub_id, sub in self.subscriptions.items()
                if sub.status == SubscriptionStatus.ACTIVE
            ]

    def get_subscription_info(self, subscription_id: str) -> Optional[SubscriptionInfo]:
        with self._lock:
            if subscription_id in self.subscriptions:
                sub = self.subscriptions[subscription_id]
                return SubscriptionInfo(
                    id=sub.id,
                    instruments=sub.instruments,
                    status=sub.status.value,
                    polling_frequency=sub.config.polling_frequency_seconds,
                    retry_on_error=sub.config.retry_on_error,
                    max_retries=sub.config.max_retries,
                )
            return None

    def stop(self) -> None:
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
