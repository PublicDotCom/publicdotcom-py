import asyncio
import time
from decimal import Decimal
from unittest.mock import Mock, AsyncMock

import pytest

from public_api_sdk.order_subscription_manager import (
    OrderSubscriptionManager,
    OrderSubscription,
)
from public_api_sdk.models.order import (
    Order,
    OrderStatus,
    OrderInstrument,
    OrderSide,
    OrderType,
)
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.new_order import OrderUpdate, OrderSubscriptionConfig


class TestOrderSubscriptionManager:
    def setup_method(self) -> None:
        """Set up test fixtures."""
        self.mock_get_order = Mock()
        self.manager = OrderSubscriptionManager(self.mock_get_order)

        self.order_new = Order(
            order_id="order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
        )

        self.order_filled = Order(
            order_id="order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            average_price=Decimal("149.95"),
        )

    def teardown_method(self) -> None:
        if hasattr(self, "manager"):
            self.manager.stop()

    def test_subscribe_order(self) -> None:
        """Test subscribing to an order."""
        callback = Mock()
        config = OrderSubscriptionConfig(polling_frequency_seconds=2.0)

        subscription_id = self.manager.subscribe_order(
            order_id="order-123",
            account_id="account-456",
            callback=callback,
            config=config,
        )

        assert subscription_id is not None
        assert subscription_id in self.manager.subscriptions

        subscription = self.manager.subscriptions[subscription_id]
        assert subscription.order_id == "order-123"
        assert subscription.account_id == "account-456"
        assert subscription.callback == callback
        assert subscription.config == config
        assert subscription.is_active is True

    def test_subscribe_replaces_existing(self) -> None:
        """Test that subscribing to same order replaces existing subscription."""
        callback1 = Mock()
        callback2 = Mock()

        sub_id1 = self.manager.subscribe_order(
            order_id="order-123", account_id="account-456", callback=callback1
        )

        sub_id2 = self.manager.subscribe_order(
            order_id="order-123", account_id="account-456", callback=callback2
        )

        # first subscription should be removed
        assert sub_id1 not in self.manager.subscriptions
        # second subscription should exist
        assert sub_id2 in self.manager.subscriptions
        # order mapping should point to new subscription
        assert self.manager.order_to_subscription["order-123"] == sub_id2

    def test_unsubscribe(self) -> None:
        """Test unsubscribing from an order."""
        callback = Mock()
        sub_id = self.manager.subscribe_order(
            order_id="order-123", account_id="account-456", callback=callback
        )

        # unsubscribe
        result = self.manager.unsubscribe(sub_id)
        assert result is True

        # subscription should be removed
        assert sub_id not in self.manager.subscriptions
        assert "order-123" not in self.manager.order_to_subscription

        # unsubscribing again should return False
        result = self.manager.unsubscribe(sub_id)
        assert result is False

    def test_unsubscribe_all(self) -> None:
        """Test unsubscribing all subscriptions."""
        # add multiple subscriptions
        for i in range(3):
            self.manager.subscribe_order(
                order_id=f"order-{i}", account_id="account-456", callback=Mock()
            )

        assert len(self.manager.subscriptions) == 3
        assert len(self.manager.order_to_subscription) == 3

        # unsubscribe all
        self.manager.unsubscribe_all()

        assert len(self.manager.subscriptions) == 0
        assert len(self.manager.order_to_subscription) == 0

    def test_get_active_subscriptions(self) -> None:
        """Test getting list of active subscriptions."""
        # add active subscription
        active_id = self.manager.subscribe_order(
            order_id="order-1", account_id="account-456", callback=Mock()
        )

        # add inactive subscription (simulate terminal status)
        inactive_id = self.manager.subscribe_order(
            order_id="order-2", account_id="account-456", callback=Mock()
        )
        self.manager.subscriptions[inactive_id].is_active = False

        active_subs = self.manager.get_active_subscriptions()

        assert active_id in active_subs
        assert inactive_id not in active_subs

    def test_get_subscription_info(self) -> None:
        """Test getting subscription information."""
        config = OrderSubscriptionConfig(
            polling_frequency_seconds=2.5, retry_on_error=False, max_retries=5
        )

        sub_id = self.manager.subscribe_order(
            order_id="order-123",
            account_id="account-456",
            callback=Mock(),
            config=config,
        )

        info = self.manager.get_subscription_info(sub_id)

        assert info is not None
        assert info["id"] == sub_id
        assert info["order_id"] == "order-123"
        assert info["account_id"] == "account-456"
        assert info["is_active"] is True
        assert info["polling_frequency"] == 2.5
        assert info["retry_on_error"] is False
        assert info["max_retries"] == 5

        # test non-existent subscription
        info = self.manager.get_subscription_info("non-existent")
        assert info is None

    @pytest.mark.asyncio
    async def test_poll_subscription_status_change(self) -> None:
        """Test polling detects status changes."""
        callback = AsyncMock()

        # create subscription
        subscription = OrderSubscription(
            subscription_id="sub-123",
            order_id="order-123",
            account_id="account-456",
            callback=callback,
            config=OrderSubscriptionConfig(),
        )
        subscription.last_status = OrderStatus.NEW

        # mock get_order to return FILLED status
        self.mock_get_order.return_value = self.order_filled

        # set up the event loop
        self.manager.loop = asyncio.get_running_loop()

        # poll the subscription
        await self.manager._poll_subscription(subscription)

        # callback should have been called
        callback.assert_called_once()
        update = callback.call_args[0][0]

        assert isinstance(update, OrderUpdate)
        assert update.order_id == "order-123"
        assert update.old_status == OrderStatus.NEW
        assert update.new_status == OrderStatus.FILLED
        assert update.order == self.order_filled

        # subscription should be marked inactive (terminal status)
        assert subscription.is_active is False

    @pytest.mark.asyncio
    async def test_poll_subscription_no_change(self) -> None:
        """Test polling when status hasn't changed."""
        callback = AsyncMock()

        subscription = OrderSubscription(
            subscription_id="sub-123",
            order_id="order-123",
            account_id="account-456",
            callback=callback,
            config=OrderSubscriptionConfig(),
        )
        subscription.last_status = OrderStatus.NEW

        # mock get_order to return same status
        self.mock_get_order.return_value = self.order_new

        # set up the event loop
        self.manager.loop = asyncio.get_running_loop()

        # poll the subscription
        await self.manager._poll_subscription(subscription)

        # callback should not have been called
        callback.assert_not_called()

        # subscription should still be active
        assert subscription.is_active is True

    @pytest.mark.asyncio
    async def test_fetch_order_with_retry(self) -> None:
        """Test order fetching with retry logic."""
        config = OrderSubscriptionConfig(
            retry_on_error=True, max_retries=2, exponential_backoff=False
        )

        # mock get_order to fail twice then succeed
        self.mock_get_order.side_effect = [
            ConnectionError("Network error"),
            TimeoutError("Timeout"),
            self.order_new,
        ]

        # set up the event loop
        self.manager.loop = asyncio.get_running_loop()

        result = await self.manager._fetch_order_with_retry(
            "order-123", "account-456", config
        )

        assert result == self.order_new
        assert self.mock_get_order.call_count == 3

    @pytest.mark.asyncio
    async def test_fetch_order_max_retries_exceeded(self) -> None:
        """Test order fetching when max retries exceeded."""
        config = OrderSubscriptionConfig(
            retry_on_error=True, max_retries=1, exponential_backoff=False
        )

        # mock get_order to always fail
        self.mock_get_order.side_effect = ConnectionError("Network error")

        # set up the event loop
        self.manager.loop = asyncio.get_running_loop()

        result = await self.manager._fetch_order_with_retry(
            "order-123", "account-456", config
        )

        assert result is None
        assert self.mock_get_order.call_count == 2  # Initial + 1 retry

    @pytest.mark.asyncio
    async def test_execute_sync_callback(self) -> None:
        """Test executing synchronous callback."""
        callback = Mock()
        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            old_status=OrderStatus.NEW,
            new_status=OrderStatus.FILLED,
            order=self.order_filled,
        )

        # set up the event loop
        self.manager.loop = asyncio.get_running_loop()

        await self.manager._execute_callback(callback, update)

        # callback should have been called with the update
        callback.assert_called_once_with(update)

    @pytest.mark.asyncio
    async def test_execute_async_callback(self) -> None:
        """Test executing asynchronous callback."""
        callback = AsyncMock()
        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            old_status=OrderStatus.NEW,
            new_status=OrderStatus.FILLED,
            order=self.order_filled,
        )

        # set up the event loop
        self.manager.loop = asyncio.get_running_loop()

        await self.manager._execute_callback(callback, update)

        # async callback should have been awaited
        callback.assert_awaited_once_with(update)

    def test_start_stop(self) -> None:
        """Test starting and stopping the manager."""
        # start should create thread
        self.manager.start()
        assert self.manager.thread is not None
        assert self.manager.thread.is_alive()

        # starting again should not create new thread
        thread1 = self.manager.thread
        self.manager.start()
        assert self.manager.thread == thread1

        # stop should clean up
        self.manager.stop()
        time.sleep(0.5)  # give thread time to stop
        assert not self.manager.thread.is_alive()

    def test_terminal_statuses(self) -> None:
        """Test that terminal statuses mark subscription as inactive."""
        terminal_statuses = [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.REPLACED,
        ]

        for status in terminal_statuses:
            subscription = OrderSubscription(
                subscription_id=f"sub-{status}",
                order_id="order-123",
                account_id="account-456",
                callback=Mock(),
                config=OrderSubscriptionConfig(),
            )
            subscription.last_status = OrderStatus.NEW

            # create order with terminal status
            order = Order(
                order_id="order-123",
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                type=OrderType.LIMIT,
                side=OrderSide.BUY,
                status=status,
                quantity=Decimal("10"),
            )

            self.mock_get_order.return_value = order

            # run async test
            async def test_terminal() -> None:
                self.manager.loop = asyncio.get_running_loop()
                await self.manager._poll_subscription(subscription)
                assert subscription.is_active is False

            asyncio.run(test_terminal())


class TestOrderSubscription:
    def test_subscription_creation(self) -> None:
        """Test creating an OrderSubscription instance."""
        callback = Mock()
        config = OrderSubscriptionConfig(polling_frequency_seconds=3.0)

        subscription = OrderSubscription(
            subscription_id="sub-123",
            order_id="order-456",
            account_id="account-789",
            callback=callback,
            config=config,
        )

        assert subscription.id == "sub-123"
        assert subscription.order_id == "order-456"
        assert subscription.account_id == "account-789"
        assert subscription.callback == callback
        assert subscription.config == config
        assert subscription.last_status is None
        assert subscription.is_active is True
        assert subscription.last_poll_time == 0
        assert subscription.last_order is None
