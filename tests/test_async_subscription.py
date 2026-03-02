"""Tests for AsyncPriceSubscriptionManager."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from public_api_sdk.async_subscription_manager import AsyncPriceSubscriptionManager
from public_api_sdk.models import (
    InstrumentType,
    OrderInstrument,
    PriceChange,
    Quote,
    QuoteOutcome,
    SubscriptionConfig,
    SubscriptionStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_instrument(symbol: str = "AAPL") -> OrderInstrument:
    return OrderInstrument(symbol=symbol, type=InstrumentType.EQUITY)


def _make_quote(
    symbol: str = "AAPL",
    last: str = "150.00",
    bid: str = "149.99",
    ask: str = "150.01",
) -> Quote:
    return Quote(
        instrument=OrderInstrument(symbol=symbol, type=InstrumentType.EQUITY),
        last=Decimal(last),
        bid=Decimal(bid),
        ask=Decimal(ask),
        outcome=QuoteOutcome.SUCCESS,
    )


def _make_manager() -> AsyncPriceSubscriptionManager:
    get_quotes = AsyncMock(return_value=[])
    return AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)


# ---------------------------------------------------------------------------
# subscribe
# ---------------------------------------------------------------------------


class TestAsyncPriceSubscriptionManagerSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_creates_subscription(self) -> None:
        manager = _make_manager()
        callback = Mock()
        instruments = [_make_instrument()]

        sub_id = await manager.subscribe(instruments=instruments, callback=callback)

        assert sub_id is not None
        assert sub_id in manager._subscriptions
        assert manager._subscriptions[sub_id].status == SubscriptionStatus.ACTIVE

        await manager.stop()

    @pytest.mark.asyncio
    async def test_subscribe_stores_instruments_and_callback(self) -> None:
        manager = _make_manager()
        callback = Mock()
        instruments = [_make_instrument("AAPL"), _make_instrument("GOOGL")]

        sub_id = await manager.subscribe(instruments=instruments, callback=callback)

        sub = manager._subscriptions[sub_id]
        assert len(sub.instruments) == 2
        assert sub.callback is callback

        await manager.stop()

    @pytest.mark.asyncio
    async def test_subscribe_with_custom_config(self) -> None:
        manager = _make_manager()
        config = SubscriptionConfig(polling_frequency_seconds=5.0, max_retries=0)
        sub_id = await manager.subscribe(
            instruments=[_make_instrument()], callback=Mock(), config=config
        )
        assert manager._subscriptions[sub_id].config.polling_frequency_seconds == 5.0

        await manager.stop()

    @pytest.mark.asyncio
    async def test_subscribe_empty_instruments_raises(self) -> None:
        manager = _make_manager()
        with pytest.raises(ValueError, match="At least one instrument"):
            await manager.subscribe(instruments=[], callback=Mock())

    @pytest.mark.asyncio
    async def test_subscribe_creates_asyncio_task(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe(
            instruments=[_make_instrument()], callback=Mock()
        )
        assert sub_id in manager._tasks
        assert not manager._tasks[sub_id].done()

        await manager.stop()

    @pytest.mark.asyncio
    async def test_multiple_subscriptions_get_independent_ids(self) -> None:
        manager = _make_manager()
        id1 = await manager.subscribe([_make_instrument("AAPL")], callback=Mock())
        id2 = await manager.subscribe([_make_instrument("GOOGL")], callback=Mock())
        assert id1 != id2
        assert len(manager._subscriptions) == 2

        await manager.stop()


# ---------------------------------------------------------------------------
# unsubscribe
# ---------------------------------------------------------------------------


class TestAsyncPriceSubscriptionManagerUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscription(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe([_make_instrument()], callback=Mock())
        result = await manager.unsubscribe(sub_id)
        assert result is True
        assert sub_id not in manager._subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_cancels_task(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe([_make_instrument()], callback=Mock())
        task = manager._tasks[sub_id]
        await manager.unsubscribe(sub_id)
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_returns_false(self) -> None:
        manager = _make_manager()
        result = await manager.unsubscribe("does-not-exist")
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_evicts_cached_quotes(self) -> None:
        manager = _make_manager()
        instruments = [_make_instrument("AAPL")]
        sub_id = await manager.subscribe(instruments, callback=Mock())
        manager._last_quotes["AAPL_EQUITY"] = _make_quote()
        await manager.unsubscribe(sub_id)
        assert "AAPL_EQUITY" not in manager._last_quotes

    @pytest.mark.asyncio
    async def test_unsubscribe_preserves_quote_if_other_subscription_uses_it(
        self,
    ) -> None:
        manager = _make_manager()
        instruments = [_make_instrument("AAPL")]
        sub1 = await manager.subscribe(instruments, callback=Mock())
        await manager.subscribe(instruments, callback=Mock())
        manager._last_quotes["AAPL_EQUITY"] = _make_quote()
        await manager.unsubscribe(sub1)
        assert "AAPL_EQUITY" in manager._last_quotes

        await manager.stop()

    @pytest.mark.asyncio
    async def test_unsubscribe_all_clears_everything(self) -> None:
        manager = _make_manager()
        await manager.subscribe([_make_instrument("AAPL")], callback=Mock())
        await manager.subscribe([_make_instrument("GOOGL")], callback=Mock())
        await manager.unsubscribe_all()
        assert len(manager._subscriptions) == 0
        assert len(manager._tasks) == 0


# ---------------------------------------------------------------------------
# pause / resume / set_polling_frequency / get_active_subscriptions
# ---------------------------------------------------------------------------


class TestAsyncPriceSubscriptionManagerControls:
    @pytest.mark.asyncio
    async def test_pause_sets_status_to_paused(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe([_make_instrument()], callback=Mock())
        result = manager.pause_subscription(sub_id)
        assert result is True
        assert manager._subscriptions[sub_id].status == SubscriptionStatus.PAUSED

        await manager.stop()

    @pytest.mark.asyncio
    async def test_resume_sets_status_to_active(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe([_make_instrument()], callback=Mock())
        manager.pause_subscription(sub_id)
        result = manager.resume_subscription(sub_id)
        assert result is True
        assert manager._subscriptions[sub_id].status == SubscriptionStatus.ACTIVE

        await manager.stop()

    @pytest.mark.asyncio
    async def test_pause_nonexistent_returns_false(self) -> None:
        manager = _make_manager()
        assert manager.pause_subscription("no-such-id") is False

    @pytest.mark.asyncio
    async def test_resume_nonexistent_returns_false(self) -> None:
        manager = _make_manager()
        assert manager.resume_subscription("no-such-id") is False

    @pytest.mark.asyncio
    async def test_set_polling_frequency_updates_config(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe([_make_instrument()], callback=Mock())
        result = manager.set_polling_frequency(sub_id, 5.0)
        assert result is True
        assert (
            manager._subscriptions[sub_id].config.polling_frequency_seconds == 5.0
        )

        await manager.stop()

    def test_set_polling_frequency_raises_on_out_of_range(self) -> None:
        manager = _make_manager()
        with pytest.raises(ValueError, match="between 0.1 and 60"):
            manager.set_polling_frequency("any", 0.0)
        with pytest.raises(ValueError, match="between 0.1 and 60"):
            manager.set_polling_frequency("any", 61.0)

    @pytest.mark.asyncio
    async def test_get_active_subscriptions_returns_active_ids(self) -> None:
        manager = _make_manager()
        sub1 = await manager.subscribe([_make_instrument("AAPL")], callback=Mock())
        sub2 = await manager.subscribe([_make_instrument("GOOGL")], callback=Mock())
        manager.pause_subscription(sub1)
        active = manager.get_active_subscriptions()
        assert sub1 not in active
        assert sub2 in active

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_subscription_info_returns_details(self) -> None:
        manager = _make_manager()
        instruments = [_make_instrument("AAPL")]
        config = SubscriptionConfig(polling_frequency_seconds=3.0)
        sub_id = await manager.subscribe(instruments, callback=Mock(), config=config)
        info = manager.get_subscription_info(sub_id)
        assert info is not None
        assert info.id == sub_id
        assert info.polling_frequency == 3.0

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_subscription_info_returns_none_for_missing_id(self) -> None:
        manager = _make_manager()
        assert manager.get_subscription_info("nonexistent") is None


# ---------------------------------------------------------------------------
# Price change detection
# ---------------------------------------------------------------------------


class TestDetectPriceChange:
    def setup_method(self) -> None:
        self.manager = _make_manager()
        self.instrument = _make_instrument("AAPL")

    def test_no_change_returns_none(self) -> None:
        old = _make_quote(last="150.00", bid="149.99", ask="150.01")
        new = _make_quote(last="150.00", bid="149.99", ask="150.01")
        result = self.manager._detect_price_change(self.instrument, old, new)
        assert result is None

    def test_last_price_change_detected(self) -> None:
        old = _make_quote(last="150.00")
        new = _make_quote(last="151.00")
        result = self.manager._detect_price_change(self.instrument, old, new)
        assert result is not None
        assert "last" in result.changed_fields

    def test_bid_change_detected(self) -> None:
        old = _make_quote(bid="149.99")
        new = _make_quote(bid="150.00")
        result = self.manager._detect_price_change(self.instrument, old, new)
        assert result is not None
        assert "bid" in result.changed_fields

    def test_ask_change_detected(self) -> None:
        old = _make_quote(ask="150.01")
        new = _make_quote(ask="150.50")
        result = self.manager._detect_price_change(self.instrument, old, new)
        assert result is not None
        assert "ask" in result.changed_fields

    def test_multiple_fields_changed(self) -> None:
        old = _make_quote(last="150.00", bid="149.99", ask="150.01")
        new = _make_quote(last="151.00", bid="150.50", ask="151.50")
        result = self.manager._detect_price_change(self.instrument, old, new)
        assert result is not None
        assert set(result.changed_fields) == {"last", "bid", "ask"}

    def test_price_change_contains_old_and_new_quote(self) -> None:
        old = _make_quote(last="150.00")
        new = _make_quote(last="151.00")
        result = self.manager._detect_price_change(self.instrument, old, new)
        assert result is not None
        assert result.old_quote == old
        assert result.new_quote == new


# ---------------------------------------------------------------------------
# Callback execution
# ---------------------------------------------------------------------------


class TestExecuteCallback:
    def setup_method(self) -> None:
        self.manager = _make_manager()
        self.instrument = _make_instrument("AAPL")

    @pytest.mark.asyncio
    async def test_sync_callback_is_called(self) -> None:
        callback = Mock()
        price_change = PriceChange(
            instrument=self.instrument,
            old_quote=_make_quote(last="150.00"),
            new_quote=_make_quote(last="151.00"),
            changed_fields=["last"],
        )
        await self.manager._execute_callback(callback, price_change)
        callback.assert_called_once_with(price_change)

    @pytest.mark.asyncio
    async def test_async_callback_is_awaited(self) -> None:
        callback = AsyncMock()
        price_change = PriceChange(
            instrument=self.instrument,
            old_quote=_make_quote(last="150.00"),
            new_quote=_make_quote(last="151.00"),
            changed_fields=["last"],
        )
        await self.manager._execute_callback(callback, price_change)
        callback.assert_called_once_with(price_change)

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_propagate(self) -> None:
        def bad_callback(_: PriceChange) -> None:
            raise RuntimeError("callback error")

        price_change = PriceChange(
            instrument=self.instrument,
            old_quote=_make_quote(last="150.00"),
            new_quote=_make_quote(last="151.00"),
            changed_fields=["last"],
        )
        # should not raise
        await self.manager._execute_callback(bad_callback, price_change)


# ---------------------------------------------------------------------------
# Poll subscription integration (internal method)
# ---------------------------------------------------------------------------


class TestPollSubscription:
    @pytest.mark.asyncio
    async def test_callback_triggered_on_price_change(self) -> None:
        callback = AsyncMock()
        instrument = _make_instrument("AAPL")
        old_quote = _make_quote("AAPL", last="150.00")
        new_quote = _make_quote("AAPL", last="151.00")

        get_quotes = AsyncMock(return_value=[new_quote])
        manager = AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)

        # seed the last-known quote so a change is detected
        manager._last_quotes["AAPL_EQUITY"] = old_quote

        sub_id = await manager.subscribe([instrument], callback=callback)
        sub = manager._subscriptions[sub_id]
        await manager._poll_subscription(sub)

        callback.assert_called_once()
        change: PriceChange = callback.call_args[0][0]
        assert "last" in change.changed_fields

        await manager.stop()

    @pytest.mark.asyncio
    async def test_callback_not_triggered_when_no_change(self) -> None:
        callback = AsyncMock()
        instrument = _make_instrument("AAPL")
        quote = _make_quote("AAPL", last="150.00")

        get_quotes = AsyncMock(return_value=[quote])
        manager = AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)
        manager._last_quotes["AAPL_EQUITY"] = quote  # same quote

        sub_id = await manager.subscribe([instrument], callback=callback)
        sub = manager._subscriptions[sub_id]
        await manager._poll_subscription(sub)

        callback.assert_not_called()
        await manager.stop()

    @pytest.mark.asyncio
    async def test_first_poll_seeds_cache_without_callback(self) -> None:
        callback = AsyncMock()
        instrument = _make_instrument("AAPL")
        quote = _make_quote("AAPL")

        get_quotes = AsyncMock(return_value=[quote])
        manager = AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)

        # no cached quote — first poll should not trigger callback
        sub_id = await manager.subscribe([instrument], callback=callback)
        sub = manager._subscriptions[sub_id]
        await manager._poll_subscription(sub)

        callback.assert_not_called()
        assert "AAPL_EQUITY" in manager._last_quotes

        await manager.stop()
