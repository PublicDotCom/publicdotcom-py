"""Tests for AsyncOrderSubscriptionManager."""

import asyncio
from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from public_api_sdk.async_order_subscription_manager import (
    AsyncOrderSubscriptionManager,
    _AsyncOrderSubscription,
)
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.new_order import OrderSubscriptionConfig, OrderUpdate
from public_api_sdk.models.order import (
    Order,
    OrderInstrument,
    OrderSide,
    OrderStatus,
    OrderType,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_order(status: OrderStatus = OrderStatus.NEW) -> Order:
    return Order(
        order_id="order-123",
        instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        type=OrderType.LIMIT,
        side=OrderSide.BUY,
        status=status,
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
    )


def _make_manager() -> AsyncOrderSubscriptionManager:
    return AsyncOrderSubscriptionManager(get_order_func=AsyncMock(return_value=_make_order()))


# ---------------------------------------------------------------------------
# subscribe_order
# ---------------------------------------------------------------------------


class TestAsyncOrderSubscriptionManagerSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_creates_subscription(self) -> None:
        manager = _make_manager()
        callback = Mock()

        sub_id = await manager.subscribe_order(
            order_id="order-123",
            account_id="account-456",
            callback=callback,
        )

        assert sub_id is not None
        assert sub_id in manager._subscriptions
        sub = manager._subscriptions[sub_id]
        assert sub.order_id == "order-123"
        assert sub.account_id == "account-456"
        assert sub.is_active is True

        await manager.stop()

    @pytest.mark.asyncio
    async def test_subscribe_creates_polling_task(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe_order(
            "order-123", "account-456", callback=Mock()
        )
        assert sub_id in manager._tasks
        assert not manager._tasks[sub_id].done()

        await manager.stop()

    @pytest.mark.asyncio
    async def test_subscribe_with_custom_config(self) -> None:
        manager = _make_manager()
        config = OrderSubscriptionConfig(polling_frequency_seconds=5.0)
        sub_id = await manager.subscribe_order(
            "order-123", "account-456", callback=Mock(), config=config
        )
        assert manager._subscriptions[sub_id].config.polling_frequency_seconds == 5.0

        await manager.stop()

    @pytest.mark.asyncio
    async def test_subscribe_replaces_existing_subscription_for_same_order(
        self,
    ) -> None:
        manager = _make_manager()
        callback1 = Mock()
        callback2 = Mock()

        sub1 = await manager.subscribe_order("order-123", "acc", callback=callback1)
        sub2 = await manager.subscribe_order("order-123", "acc", callback=callback2)

        assert sub1 != sub2
        assert sub1 not in manager._subscriptions
        assert sub2 in manager._subscriptions

        await manager.stop()

    @pytest.mark.asyncio
    async def test_order_to_subscription_mapping_updated(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe_order(
            "order-123", "account-456", callback=Mock()
        )
        assert manager._order_to_subscription.get("order-123") == sub_id

        await manager.stop()


# ---------------------------------------------------------------------------
# unsubscribe
# ---------------------------------------------------------------------------


class TestAsyncOrderSubscriptionManagerUnsubscribe:
    @pytest.mark.asyncio
    async def test_unsubscribe_removes_subscription(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe_order(
            "order-123", "acc", callback=Mock()
        )
        result = await manager.unsubscribe(sub_id)
        assert result is True
        assert sub_id not in manager._subscriptions

    @pytest.mark.asyncio
    async def test_unsubscribe_cancels_task(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe_order(
            "order-123", "acc", callback=Mock()
        )
        task = manager._tasks[sub_id]
        await manager.unsubscribe(sub_id)
        assert task.cancelled() or task.done()

    @pytest.mark.asyncio
    async def test_unsubscribe_nonexistent_returns_false(self) -> None:
        manager = _make_manager()
        result = await manager.unsubscribe("does-not-exist")
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_clears_order_mapping(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe_order(
            "order-123", "acc", callback=Mock()
        )
        await manager.unsubscribe(sub_id)
        assert "order-123" not in manager._order_to_subscription

    @pytest.mark.asyncio
    async def test_unsubscribe_all_clears_everything(self) -> None:
        manager = _make_manager()
        await manager.subscribe_order("order-1", "acc", callback=Mock())
        await manager.subscribe_order("order-2", "acc", callback=Mock())
        await manager.unsubscribe_all()
        assert len(manager._subscriptions) == 0
        assert len(manager._tasks) == 0
        assert len(manager._order_to_subscription) == 0


# ---------------------------------------------------------------------------
# get_active_subscriptions / get_subscription_info
# ---------------------------------------------------------------------------


class TestAsyncOrderSubscriptionManagerInfo:
    @pytest.mark.asyncio
    async def test_get_active_subscriptions_returns_active_only(self) -> None:
        manager = _make_manager()
        sub1 = await manager.subscribe_order("order-1", "acc", callback=Mock())
        sub2 = await manager.subscribe_order("order-2", "acc", callback=Mock())
        # manually mark sub1's underlying subscription as inactive
        manager._subscriptions[sub1].is_active = False
        active = manager.get_active_subscriptions()
        assert sub1 not in active
        assert sub2 in active

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_subscription_info_returns_details(self) -> None:
        manager = _make_manager()
        sub_id = await manager.subscribe_order(
            "order-123", "account-456", callback=Mock()
        )
        info = manager.get_subscription_info(sub_id)
        assert info is not None
        assert info["id"] == sub_id
        assert info["order_id"] == "order-123"
        assert info["account_id"] == "account-456"
        assert info["is_active"] is True

        await manager.stop()

    @pytest.mark.asyncio
    async def test_get_subscription_info_returns_none_for_missing_id(self) -> None:
        manager = _make_manager()
        assert manager.get_subscription_info("nonexistent") is None


# ---------------------------------------------------------------------------
# Callback execution
# ---------------------------------------------------------------------------


class TestAsyncOrderSubscriptionCallback:
    @pytest.mark.asyncio
    async def test_sync_callback_is_called(self) -> None:
        callback = Mock()
        manager = _make_manager()
        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            old_status=None,
            new_status=OrderStatus.FILLED,
            order=_make_order(OrderStatus.FILLED),
        )
        await manager._execute_callback(callback, update)
        callback.assert_called_once_with(update)

    @pytest.mark.asyncio
    async def test_async_callback_is_awaited(self) -> None:
        callback = AsyncMock()
        manager = _make_manager()
        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            old_status=None,
            new_status=OrderStatus.FILLED,
            order=_make_order(OrderStatus.FILLED),
        )
        await manager._execute_callback(callback, update)
        callback.assert_called_once_with(update)

    @pytest.mark.asyncio
    async def test_callback_exception_does_not_propagate(self) -> None:
        def bad_callback(_: OrderUpdate) -> None:
            raise RuntimeError("boom")

        manager = _make_manager()
        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            old_status=None,
            new_status=OrderStatus.FILLED,
            order=_make_order(OrderStatus.FILLED),
        )
        # should not raise
        await manager._execute_callback(bad_callback, update)


# ---------------------------------------------------------------------------
# _poll_subscription (internal method — tests status change detection)
# ---------------------------------------------------------------------------


class TestPollSubscription:
    def _make_sub(
        self,
        order_id: str = "order-123",
        account_id: str = "account-456",
        callback: object = None,
        last_status: OrderStatus = OrderStatus.NEW,
    ) -> _AsyncOrderSubscription:
        return _AsyncOrderSubscription(
            subscription_id="sub-id",
            order_id=order_id,
            account_id=account_id,
            callback=callback or Mock(),
            config=OrderSubscriptionConfig(),
        )

    @pytest.mark.asyncio
    async def test_callback_triggered_on_status_change(self) -> None:
        callback = AsyncMock()
        new_order = _make_order(OrderStatus.NEW)
        filled_order = _make_order(OrderStatus.FILLED)

        get_order = AsyncMock(return_value=filled_order)
        manager = AsyncOrderSubscriptionManager(get_order_func=get_order)

        sub = self._make_sub(callback=callback, last_status=OrderStatus.NEW)
        sub.last_status = OrderStatus.NEW
        manager._subscriptions["sub-id"] = sub

        await manager._poll_subscription(sub)

        callback.assert_called_once()
        update: OrderUpdate = callback.call_args[0][0]
        assert update.old_status == OrderStatus.NEW
        assert update.new_status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_callback_not_triggered_when_status_unchanged(self) -> None:
        callback = AsyncMock()
        order = _make_order(OrderStatus.NEW)

        get_order = AsyncMock(return_value=order)
        manager = AsyncOrderSubscriptionManager(get_order_func=get_order)

        sub = self._make_sub(callback=callback)
        sub.last_status = OrderStatus.NEW
        manager._subscriptions["sub-id"] = sub

        await manager._poll_subscription(sub)

        callback.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscription_marked_inactive_on_terminal_status(self) -> None:
        callback = AsyncMock()
        filled_order = _make_order(OrderStatus.FILLED)

        get_order = AsyncMock(return_value=filled_order)
        manager = AsyncOrderSubscriptionManager(get_order_func=get_order)

        sub = self._make_sub(callback=callback)
        sub.last_status = OrderStatus.NEW
        manager._subscriptions["sub-id"] = sub

        await manager._poll_subscription(sub)

        assert sub.is_active is False

    @pytest.mark.asyncio
    async def test_subscription_stays_active_on_non_terminal_status(self) -> None:
        callback = AsyncMock()
        partial_order = _make_order(OrderStatus.PARTIALLY_FILLED)

        get_order = AsyncMock(return_value=partial_order)
        manager = AsyncOrderSubscriptionManager(get_order_func=get_order)

        sub = self._make_sub(callback=callback)
        sub.last_status = OrderStatus.NEW
        manager._subscriptions["sub-id"] = sub

        await manager._poll_subscription(sub)

        assert sub.is_active is True

    @pytest.mark.asyncio
    async def test_all_terminal_statuses_deactivate_subscription(self) -> None:
        from public_api_sdk.async_order_subscription_manager import _TERMINAL_STATUSES

        for terminal_status in _TERMINAL_STATUSES:
            get_order = AsyncMock(return_value=_make_order(terminal_status))
            manager = AsyncOrderSubscriptionManager(get_order_func=get_order)

            sub = self._make_sub(callback=AsyncMock())
            sub.last_status = OrderStatus.NEW
            manager._subscriptions["sub-id"] = sub

            await manager._poll_subscription(sub)
            assert sub.is_active is False, f"Expected inactive for {terminal_status}"
