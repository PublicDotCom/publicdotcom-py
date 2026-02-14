"""Extended tests for NewOrder lifecycle and edge cases."""
import time
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import Mock

import pytest

from public_api_sdk.models import (
    OrderInstrument,
    OrderSide,
    OrderStatus,
    OrderType,
    InstrumentType,
    WaitTimeoutError,
)
from public_api_sdk.models.new_order import NewOrder, OrderUpdate, OrderSubscriptionConfig
from public_api_sdk.models.order import Order


class TestNewOrderLifecycle:
    """Tests for complete NewOrder lifecycle."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def mock_subscription_manager(self):
        return Mock()

    @pytest.fixture
    def sample_new_order(self, mock_client, mock_subscription_manager):
        return NewOrder(
            order_id="test-order-123",
            account_id="test-account-456",
            client=mock_client,
            subscription_manager=mock_subscription_manager,
        )

    @pytest.fixture
    def sample_order_new(self):
        return Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
            created_at=datetime.now(timezone.utc),
        )

    @pytest.fixture
    def sample_order_filled(self):
        return Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
            average_price=Decimal("149.95"),
            created_at=datetime.now(timezone.utc),
        )

    def test_wait_for_status_timeout(self, sample_new_order, mock_client, sample_order_new):
        """wait_for_status should raise WaitTimeoutError when timeout exceeded."""
        mock_client.get_order.return_value = sample_order_new  # Never changes
        
        with pytest.raises(WaitTimeoutError) as exc:
            sample_new_order.wait_for_status(
                OrderStatus.FILLED,
                timeout=0.1,
                polling_interval=0.05
            )
        
        assert "test-order-123" in str(exc.value)
        assert "FILLED" in str(exc.value)
        assert "NEW" in str(exc.value)  # Current status

    def test_wait_for_status_single_target(self, sample_new_order, mock_client, sample_order_filled):
        """wait_for_status should return when single target status reached."""
        mock_client.get_order.return_value = sample_order_filled
        
        result = sample_new_order.wait_for_status(OrderStatus.FILLED, timeout=5)
        
        assert result.status == OrderStatus.FILLED

    def test_wait_for_status_multiple_targets(self, sample_new_order, mock_client):
        """wait_for_status should return when any target status reached."""
        cancelled_order = Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.CANCELLED,
            quantity=Decimal("10"),
        )
        mock_client.get_order.return_value = cancelled_order
        
        result = sample_new_order.wait_for_status(
            [OrderStatus.FILLED, OrderStatus.CANCELLED],
            timeout=5
        )
        
        assert result.status == OrderStatus.CANCELLED

    def test_wait_for_fill_success(self, sample_new_order, mock_client, sample_order_filled):
        """wait_for_fill should return when order is filled."""
        mock_client.get_order.return_value = sample_order_filled
        
        result = sample_new_order.wait_for_fill(timeout=5)
        
        assert result.status == OrderStatus.FILLED
        assert result.filled_quantity == Decimal("10")

    def test_wait_for_fill_timeout(self, sample_new_order, mock_client, sample_order_new):
        """wait_for_fill should raise timeout when not filled."""
        mock_client.get_order.return_value = sample_order_new
        
        with pytest.raises(WaitTimeoutError):
            sample_new_order.wait_for_fill(timeout=0.1, polling_interval=0.05)

    def test_wait_for_terminal_status_filled(self, sample_new_order, mock_client, sample_order_filled):
        """wait_for_terminal_status should return when filled."""
        mock_client.get_order.return_value = sample_order_filled
        
        result = sample_new_order.wait_for_terminal_status(timeout=5)
        
        assert result.status == OrderStatus.FILLED

    def test_wait_for_terminal_status_cancelled(self, sample_new_order, mock_client):
        """wait_for_terminal_status should return when cancelled."""
        cancelled_order = Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.CANCELLED,
            quantity=Decimal("10"),
        )
        mock_client.get_order.return_value = cancelled_order
        
        result = sample_new_order.wait_for_terminal_status(timeout=5)
        
        assert result.status == OrderStatus.CANCELLED

    def test_wait_for_terminal_status_rejected(self, sample_new_order, mock_client):
        """wait_for_terminal_status should return when rejected."""
        rejected_order = Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.REJECTED,
            quantity=Decimal("10"),
        )
        mock_client.get_order.return_value = rejected_order
        
        result = sample_new_order.wait_for_terminal_status(timeout=5)
        
        assert result.status == OrderStatus.REJECTED

    def test_wait_for_terminal_status_expired(self, sample_new_order, mock_client):
        """wait_for_terminal_status should return when expired."""
        expired_order = Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.EXPIRED,
            quantity=Decimal("10"),
        )
        mock_client.get_order.return_value = expired_order
        
        result = sample_new_order.wait_for_terminal_status(timeout=5)
        
        assert result.status == OrderStatus.EXPIRED

    def test_cancel_calls_client(self, sample_new_order, mock_client):
        """cancel should call client.cancel_order."""
        sample_new_order.cancel()
        
        mock_client.cancel_order.assert_called_once_with(
            order_id="test-order-123",
            account_id="test-account-456",
        )

    def test_cancel_then_wait_for_cancelled(self, sample_new_order, mock_client):
        """Full cancel workflow: cancel then wait for CANCELLED status."""
        cancelled_order = Order(
            order_id="test-order-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.CANCELLED,
            quantity=Decimal("10"),
        )
        mock_client.get_order.return_value = cancelled_order
        
        sample_new_order.cancel()
        result = sample_new_order.wait_for_status(OrderStatus.CANCELLED, timeout=5)
        
        assert result.status == OrderStatus.CANCELLED

    def test_get_status_updates_last_known(self, sample_new_order, mock_client, sample_order_filled):
        """get_status should update last_known_status."""
        mock_client.get_order.return_value = sample_order_filled
        
        status = sample_new_order.get_status()
        
        assert status == OrderStatus.FILLED
        assert sample_new_order._last_known_status == OrderStatus.FILLED

    def test_get_details_updates_last_known(self, sample_new_order, mock_client, sample_order_filled):
        """get_details should update last_known_status."""
        mock_client.get_order.return_value = sample_order_filled
        
        order = sample_new_order.get_details()
        
        assert order.status == OrderStatus.FILLED
        assert sample_new_order._last_known_status == OrderStatus.FILLED


class TestNewOrderSubscription:
    """Tests for NewOrder subscription functionality."""

    @pytest.fixture
    def mock_client(self):
        return Mock()

    @pytest.fixture
    def mock_subscription_manager(self):
        return Mock()

    @pytest.fixture
    def sample_new_order(self, mock_client, mock_subscription_manager):
        return NewOrder(
            order_id="test-order-123",
            account_id="test-account-456",
            client=mock_client,
            subscription_manager=mock_subscription_manager,
        )

    def test_subscribe_updates_creates_subscription(self, sample_new_order, mock_subscription_manager):
        """subscribe_updates should create subscription via manager."""
        callback = Mock()
        config = OrderSubscriptionConfig(polling_frequency_seconds=2.0)
        mock_subscription_manager.subscribe_order.return_value = "sub-123"
        
        sub_id = sample_new_order.subscribe_updates(callback, config)
        
        assert sub_id == "sub-123"
        mock_subscription_manager.subscribe_order.assert_called_once_with(
            order_id="test-order-123",
            account_id="test-account-456",
            callback=callback,
            config=config,
        )

    def test_subscribe_updates_without_config(self, sample_new_order, mock_subscription_manager):
        """subscribe_updates should work without explicit config."""
        callback = Mock()
        mock_subscription_manager.subscribe_order.return_value = "sub-123"
        
        sub_id = sample_new_order.subscribe_updates(callback)
        
        assert sub_id == "sub-123"
        call_args = mock_subscription_manager.subscribe_order.call_args
        assert call_args.kwargs.get('config') is None

    def test_subscribe_updates_replaces_existing(self, sample_new_order, mock_subscription_manager):
        """Subscribing again should replace existing subscription."""
        callback1 = Mock()
        callback2 = Mock()
        
        mock_subscription_manager.subscribe_order.side_effect = ["sub-1", "sub-2"]
        mock_subscription_manager.unsubscribe.return_value = True
        
        sample_new_order.subscribe_updates(callback1)
        sample_new_order.subscribe_updates(callback2)
        
        mock_subscription_manager.unsubscribe.assert_called_once_with("sub-1")
        assert mock_subscription_manager.subscribe_order.call_count == 2

    def test_unsubscribe_success(self, sample_new_order, mock_subscription_manager):
        """unsubscribe should return True on success."""
        mock_subscription_manager.subscribe_order.return_value = "sub-123"
        mock_subscription_manager.unsubscribe.return_value = True
        
        sample_new_order.subscribe_updates(Mock())
        result = sample_new_order.unsubscribe()
        
        assert result is True
        mock_subscription_manager.unsubscribe.assert_called_once_with("sub-123")

    def test_unsubscribe_not_subscribed(self, sample_new_order):
        """unsubscribe without subscribing should return False."""
        result = sample_new_order.unsubscribe()
        
        assert result is False

    def test_unsubscribe_idempotent(self, sample_new_order, mock_subscription_manager):
        """unsubscribe should be safe to call multiple times."""
        mock_subscription_manager.subscribe_order.return_value = "sub-123"
        mock_subscription_manager.unsubscribe.return_value = True
        
        sample_new_order.subscribe_updates(Mock())
        sample_new_order.unsubscribe()
        
        # Second unsubscribe should return False
        result = sample_new_order.unsubscribe()
        assert result is False


class TestNewOrderProperties:
    """Tests for NewOrder properties."""

    @pytest.fixture
    def sample_new_order(self):
        return NewOrder(
            order_id="order-abc-123",
            account_id="account-xyz-456",
            client=Mock(),
            subscription_manager=Mock(),
        )

    def test_order_id_property(self, sample_new_order):
        """order_id property should return correct value."""
        assert sample_new_order.order_id == "order-abc-123"

    def test_account_id_property(self, sample_new_order):
        """account_id property should return correct value."""
        assert sample_new_order.account_id == "account-xyz-456"

    def test_repr(self, sample_new_order):
        """__repr__ should include order_id and account_id."""
        repr_str = repr(sample_new_order)
        assert "NewOrder" in repr_str
        assert "order-abc-123" in repr_str
        assert "account-xyz-456" in repr_str


class TestOrderUpdateModel:
    """Tests for OrderUpdate model."""

    def test_order_update_creation(self):
        """OrderUpdate should be created with all fields."""
        old_order = Order(
            order_id="test-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            quantity=Decimal("10"),
        )
        new_order = Order(
            order_id="test-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.FILLED,
            quantity=Decimal("10"),
            filled_quantity=Decimal("10"),
        )
        
        update = OrderUpdate(
            order_id="test-123",
            account_id="acc-456",
            old_status=OrderStatus.NEW,
            new_status=OrderStatus.FILLED,
            order=new_order,
        )
        
        assert update.order_id == "test-123"
        assert update.account_id == "acc-456"
        assert update.old_status == OrderStatus.NEW
        assert update.new_status == OrderStatus.FILLED
        assert update.order.status == OrderStatus.FILLED
        assert update.timestamp is not None

    def test_order_update_optional_old_status(self):
        """OrderUpdate old_status should be optional."""
        order = Order(
            order_id="test-123",
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            type=OrderType.LIMIT,
            side=OrderSide.BUY,
            status=OrderStatus.NEW,
            quantity=Decimal("10"),
        )
        
        update = OrderUpdate(
            order_id="test-123",
            account_id="acc-456",
            new_status=OrderStatus.NEW,
            order=order,
        )
        
        assert update.old_status is None


class TestOrderSubscriptionConfig:
    """Tests for OrderSubscriptionConfig model."""

    def test_default_config_values(self):
        """Default config should have sensible values."""
        config = OrderSubscriptionConfig()
        
        assert config.polling_frequency_seconds == 1.0
        assert config.retry_on_error is True
        assert config.max_retries == 3
        assert config.exponential_backoff is True

    def test_custom_config_values(self):
        """Custom config values should be accepted."""
        config = OrderSubscriptionConfig(
            polling_frequency_seconds=0.5,
            retry_on_error=False,
            max_retries=5,
            exponential_backoff=False,
        )
        
        assert config.polling_frequency_seconds == 0.5
        assert config.retry_on_error is False
        assert config.max_retries == 5
        assert config.exponential_backoff is False

    def test_polling_frequency_bounds(self):
        """Polling frequency must be within bounds."""
        # Too low
        with pytest.raises(ValueError):
            OrderSubscriptionConfig(polling_frequency_seconds=0.05)
        
        # Too high
        with pytest.raises(ValueError):
            OrderSubscriptionConfig(polling_frequency_seconds=61)
        
        # At bounds
        config_min = OrderSubscriptionConfig(polling_frequency_seconds=0.1)
        assert config_min.polling_frequency_seconds == 0.1
        
        config_max = OrderSubscriptionConfig(polling_frequency_seconds=60)
        assert config_max.polling_frequency_seconds == 60

    def test_max_retries_bounds(self):
        """Max retries must be within bounds."""
        with pytest.raises(ValueError):
            OrderSubscriptionConfig(max_retries=-1)
        
        with pytest.raises(ValueError):
            OrderSubscriptionConfig(max_retries=11)
        
        config = OrderSubscriptionConfig(max_retries=10)
        assert config.max_retries == 10
