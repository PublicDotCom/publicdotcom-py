from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from public_api_sdk.models.new_order import (
    NewOrder,
    OrderUpdate,
    OrderSubscriptionConfig,
    WaitTimeoutError,
)
from public_api_sdk.models.order import (
    Order,
    OrderStatus,
    OrderInstrument,
    OrderSide,
    OrderType,
)
from public_api_sdk.models.instrument_type import InstrumentType


class TestNewOrder:
    def setup_method(self) -> None:
        self.order_id = "test-order-123"
        self.account_id = "test-account-456"
        self.mock_client = Mock()
        self.mock_subscription_manager = Mock()

        self.new_order = NewOrder(
            order_id=self.order_id,
            account_id=self.account_id,
            client=self.mock_client,
            subscription_manager=self.mock_subscription_manager,
        )
        self.sample_order = Order(
            order_id=self.order_id,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
            created_at=datetime.now(timezone.utc),
        )

    def test_properties(self) -> None:
        assert self.new_order.order_id == self.order_id
        assert self.new_order.account_id == self.account_id

    def test_subscribe_updates(self) -> None:
        """Test subscribing to order updates."""
        callback = Mock()
        config = OrderSubscriptionConfig(polling_frequency_seconds=2.0)
        subscription_id = "sub-123"

        self.mock_subscription_manager.subscribe_order.return_value = subscription_id

        result = self.new_order.subscribe_updates(callback, config)

        assert result == subscription_id
        self.mock_subscription_manager.subscribe_order.assert_called_once_with(
            order_id=self.order_id,
            account_id=self.account_id,
            callback=callback,
            config=config,
        )

    def test_subscribe_updates_replaces_existing(self) -> None:
        """Test that subscribing again replaces existing subscription."""
        callback1 = Mock()
        callback2 = Mock()

        self.mock_subscription_manager.subscribe_order.return_value = "sub-1"
        self.new_order.subscribe_updates(callback1)

        self.mock_subscription_manager.subscribe_order.return_value = "sub-2"
        self.mock_subscription_manager.unsubscribe.return_value = True

        self.new_order.subscribe_updates(callback2)

        # should unsubscribe from first subscription
        self.mock_subscription_manager.unsubscribe.assert_called_once_with("sub-1")
        # should create second subscription
        assert self.mock_subscription_manager.subscribe_order.call_count == 2

    def test_unsubscribe(self) -> None:
        """Test unsubscribing from updates."""
        # first subscribe
        self.mock_subscription_manager.subscribe_order.return_value = "sub-123"
        self.new_order.subscribe_updates(Mock())

        # then unsubscribe
        self.mock_subscription_manager.unsubscribe.return_value = True
        result = self.new_order.unsubscribe()

        assert result is True
        self.mock_subscription_manager.unsubscribe.assert_called_once_with("sub-123")

        # Unsubscribing again should return False
        result = self.new_order.unsubscribe()
        assert result is False

    def test_get_status(self) -> None:
        """Test getting current order status."""
        self.mock_client.get_order.return_value = self.sample_order

        result = self.new_order.get_status()

        assert result == OrderStatus.NEW
        self.mock_client.get_order.assert_called_once_with(
            order_id=self.order_id, account_id=self.account_id
        )

    def test_get_details(self) -> None:
        """Test getting full order details."""
        self.mock_client.get_order.return_value = self.sample_order

        result = self.new_order.get_details()

        assert result == self.sample_order
        self.mock_client.get_order.assert_called_once_with(
            order_id=self.order_id, account_id=self.account_id
        )

    def test_wait_for_status_single_status(self) -> None:
        """Test waiting for a single status."""
        filled_order = Order(
            order_id=self.order_id,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            average_price=Decimal("149.95"),
        )

        # mock get_order to return FILLED status
        self.mock_client.get_order.return_value = filled_order

        result = self.new_order.wait_for_status(OrderStatus.FILLED, timeout=5)

        assert result == filled_order
        self.mock_client.get_order.assert_called()

    def test_wait_for_status_multiple_statuses(self) -> None:
        """Test waiting for multiple statuses."""
        cancelled_order = Order(
            order_id=self.order_id,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.CANCELLED,
            quantity=Decimal("10"),
        )

        self.mock_client.get_order.return_value = cancelled_order

        result = self.new_order.wait_for_status(
            [OrderStatus.FILLED, OrderStatus.CANCELLED], timeout=5
        )

        assert result == cancelled_order

    def test_wait_for_status_timeout(self) -> None:
        """Test that wait_for_status raises timeout error."""
        # mock get_order to always return NEW status
        self.mock_client.get_order.return_value = self.sample_order

        with pytest.raises(WaitTimeoutError) as exc_info:
            self.new_order.wait_for_status(
                OrderStatus.FILLED, timeout=0.1, polling_interval=0.05
            )

        assert "Timeout waiting for order" in str(exc_info.value)
        assert self.order_id in str(exc_info.value)

    def test_wait_for_fill(self) -> None:
        """Test wait_for_fill convenience method."""
        filled_order = Order(
            order_id=self.order_id,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            average_price=Decimal("149.95"),
        )

        self.mock_client.get_order.return_value = filled_order

        result = self.new_order.wait_for_fill(timeout=5)

        assert result == filled_order
        assert result.status == OrderStatus.FILLED

    def test_wait_for_terminal_status(self) -> None:
        """Test wait_for_terminal_status method."""
        rejected_order = Order(
            order_id=self.order_id,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.REJECTED,
            quantity=Decimal("10"),
            reject_reason="Insufficient funds",
        )

        self.mock_client.get_order.return_value = rejected_order

        result = self.new_order.wait_for_terminal_status(timeout=5)

        assert result == rejected_order
        assert result.status == OrderStatus.REJECTED

    def test_cancel(self) -> None:
        """Test cancelling an order."""
        self.new_order.cancel()

        self.mock_client.cancel_order.assert_called_once_with(
            order_id=self.order_id, account_id=self.account_id
        )

    def test_del_unsubscribes(self) -> None:
        """Test that __del__ unsubscribes if subscribed."""
        # subscribe first
        self.mock_subscription_manager.subscribe_order.return_value = "sub-123"
        self.new_order.subscribe_updates(Mock())

        # mock unsubscribe
        self.mock_subscription_manager.unsubscribe.return_value = True

        # call __del__
        self.new_order.__del__()

        # should have called unsubscribe
        self.mock_subscription_manager.unsubscribe.assert_called_with("sub-123")

    def test_del_handles_exceptions(self) -> None:
        """Test that __del__ handles exceptions gracefully."""
        # subscribe first
        self.mock_subscription_manager.subscribe_order.return_value = "sub-123"
        self.new_order.subscribe_updates(Mock())

        # make unsubscribe raise an exception
        self.mock_subscription_manager.unsubscribe.side_effect = Exception("Test error")

        # should not raise
        self.new_order.__del__()


class TestOrderUpdate:
    def test_order_update_creation(self) -> None:
        order = Order(
            order_id="order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=Decimal("10"),
        )

        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            old_status=OrderStatus.NEW,
            new_status=OrderStatus.FILLED,
            order=order,
        )

        assert update.order_id == "order-123"
        assert update.account_id == "account-456"
        assert update.old_status == OrderStatus.NEW
        assert update.new_status == OrderStatus.FILLED
        assert update.order == order
        assert isinstance(update.timestamp, datetime)

    def test_order_update_without_old_status(self) -> None:
        """Test OrderUpdate with no old_status."""
        order = Order(
            order_id="order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            quantity=Decimal("10"),
        )

        update = OrderUpdate(
            order_id="order-123",
            account_id="account-456",
            new_status=OrderStatus.NEW,
            order=order,
        )

        assert update.old_status is None
        assert update.new_status == OrderStatus.NEW


class TestOrderSubscriptionConfig:
    """Test cases for OrderSubscriptionConfig."""

    def test_default_config(self) -> None:
        """Test default configuration values."""
        config = OrderSubscriptionConfig()

        assert config.polling_frequency_seconds == 1.0
        assert config.retry_on_error is True
        assert config.max_retries == 3
        assert config.exponential_backoff is True

    def test_custom_config(self) -> None:
        """Test custom configuration values."""
        config = OrderSubscriptionConfig(
            polling_frequency_seconds=5.0,
            retry_on_error=False,
            max_retries=5,
            exponential_backoff=False,
        )

        assert config.polling_frequency_seconds == 5.0
        assert config.retry_on_error is False
        assert config.max_retries == 5
        assert config.exponential_backoff is False

    def test_config_validation(self) -> None:
        """Test configuration validation."""
        # test polling frequency bounds
        with pytest.raises(ValueError):
            OrderSubscriptionConfig(polling_frequency_seconds=0.05)  # Too low

        with pytest.raises(ValueError):
            OrderSubscriptionConfig(polling_frequency_seconds=61)  # Too high

        # test max retries bounds
        with pytest.raises(ValueError):
            OrderSubscriptionConfig(max_retries=-1)  # Negative

        with pytest.raises(ValueError):
            OrderSubscriptionConfig(max_retries=11)  # Too high
