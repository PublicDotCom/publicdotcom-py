"""Tests for AsyncNewOrder."""

from decimal import Decimal
from unittest.mock import AsyncMock, Mock

import pytest

from public_api_sdk.models.async_new_order import AsyncNewOrder
from public_api_sdk.models.new_order import OrderSubscriptionConfig, WaitTimeoutError
from public_api_sdk.models.order import (
    Order,
    OrderInstrument,
    OrderSide,
    OrderStatus,
    OrderType,
)
from public_api_sdk.models.instrument_type import InstrumentType


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


def _make_async_new_order(
    order_id: str = "order-123",
    account_id: str = "account-456",
) -> tuple[AsyncNewOrder, Mock, Mock]:
    """Returns (new_order, mock_client, mock_subscription_manager)."""
    mock_client = Mock()
    mock_client.get_order = AsyncMock(return_value=_make_order())
    mock_client.cancel_order = AsyncMock(return_value=None)

    mock_sub_manager = Mock()
    mock_sub_manager.subscribe_order = AsyncMock(return_value="sub-123")
    mock_sub_manager.unsubscribe = AsyncMock(return_value=True)

    new_order = AsyncNewOrder(
        order_id=order_id,
        account_id=account_id,
        client=mock_client,
        subscription_manager=mock_sub_manager,
    )
    return new_order, mock_client, mock_sub_manager


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestAsyncNewOrderProperties:
    def test_order_id_property(self) -> None:
        new_order, _, _ = _make_async_new_order(order_id="order-abc")
        assert new_order.order_id == "order-abc"

    def test_account_id_property(self) -> None:
        new_order, _, _ = _make_async_new_order(account_id="acc-xyz")
        assert new_order.account_id == "acc-xyz"

    def test_repr(self) -> None:
        new_order, _, _ = _make_async_new_order()
        assert "order-123" in repr(new_order)
        assert "account-456" in repr(new_order)


# ---------------------------------------------------------------------------
# subscribe_updates / unsubscribe
# ---------------------------------------------------------------------------


class TestAsyncNewOrderSubscription:
    @pytest.mark.asyncio
    async def test_subscribe_updates_returns_subscription_id(self) -> None:
        new_order, _, mock_sub = _make_async_new_order()
        mock_sub.subscribe_order.return_value = "sub-id-1"
        sub_id = await new_order.subscribe_updates(AsyncMock())
        assert sub_id == "sub-id-1"

    @pytest.mark.asyncio
    async def test_subscribe_updates_calls_manager(self) -> None:
        new_order, _, mock_sub = _make_async_new_order()
        callback = Mock()
        config = OrderSubscriptionConfig(polling_frequency_seconds=2.0)
        await new_order.subscribe_updates(callback, config)
        mock_sub.subscribe_order.assert_called_once_with(
            order_id="order-123",
            account_id="account-456",
            callback=callback,
            config=config,
        )

    @pytest.mark.asyncio
    async def test_subscribe_replaces_existing_subscription(self) -> None:
        new_order, _, mock_sub = _make_async_new_order()
        mock_sub.subscribe_order.side_effect = ["sub-1", "sub-2"]

        await new_order.subscribe_updates(Mock())
        await new_order.subscribe_updates(Mock())

        # unsubscribe called once to cancel first subscription
        mock_sub.unsubscribe.assert_called_once_with("sub-1")
        # subscribe_order called twice
        assert mock_sub.subscribe_order.call_count == 2

    @pytest.mark.asyncio
    async def test_unsubscribe_returns_true_after_subscribing(self) -> None:
        new_order, _, mock_sub = _make_async_new_order()
        await new_order.subscribe_updates(Mock())
        result = await new_order.unsubscribe()
        assert result is True
        mock_sub.unsubscribe.assert_called_once_with("sub-123")

    @pytest.mark.asyncio
    async def test_unsubscribe_clears_subscription_id(self) -> None:
        new_order, _, mock_sub = _make_async_new_order()
        await new_order.subscribe_updates(Mock())
        await new_order.unsubscribe()
        # calling again should return False (no active subscription)
        result = await new_order.unsubscribe()
        assert result is False

    @pytest.mark.asyncio
    async def test_unsubscribe_without_subscription_returns_false(self) -> None:
        new_order, _, _ = _make_async_new_order()
        result = await new_order.unsubscribe()
        assert result is False


# ---------------------------------------------------------------------------
# get_status / get_details
# ---------------------------------------------------------------------------


class TestAsyncNewOrderFetch:
    @pytest.mark.asyncio
    async def test_get_status_returns_order_status(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.NEW)
        status = await new_order.get_status()
        assert status == OrderStatus.NEW

    @pytest.mark.asyncio
    async def test_get_status_calls_get_order_with_correct_args(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        await new_order.get_status()
        mock_client.get_order.assert_called_once_with(
            order_id="order-123", account_id="account-456"
        )

    @pytest.mark.asyncio
    async def test_get_details_returns_order(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        expected = _make_order(OrderStatus.FILLED)
        mock_client.get_order.return_value = expected
        result = await new_order.get_details()
        assert result == expected

    @pytest.mark.asyncio
    async def test_get_details_calls_get_order_with_correct_args(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        await new_order.get_details()
        mock_client.get_order.assert_called_once_with(
            order_id="order-123", account_id="account-456"
        )


# ---------------------------------------------------------------------------
# wait_for_status
# ---------------------------------------------------------------------------


class TestAsyncNewOrderWaitForStatus:
    @pytest.mark.asyncio
    async def test_wait_for_status_returns_immediately_when_already_at_target(
        self,
    ) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.FILLED)
        result = await new_order.wait_for_status(OrderStatus.FILLED, timeout=5)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_wait_for_status_polls_until_target(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        # first call returns NEW, second call returns FILLED
        mock_client.get_order.side_effect = [
            _make_order(OrderStatus.NEW),
            _make_order(OrderStatus.FILLED),
        ]
        result = await new_order.wait_for_status(
            OrderStatus.FILLED, timeout=5, polling_interval=0.01
        )
        assert result.status == OrderStatus.FILLED
        assert mock_client.get_order.call_count == 2

    @pytest.mark.asyncio
    async def test_wait_for_status_accepts_list_of_statuses(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.CANCELLED)
        result = await new_order.wait_for_status(
            [OrderStatus.FILLED, OrderStatus.CANCELLED], timeout=5
        )
        assert result.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_wait_for_status_raises_on_timeout(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.NEW)
        with pytest.raises(WaitTimeoutError) as exc_info:
            await new_order.wait_for_status(
                OrderStatus.FILLED, timeout=0.05, polling_interval=0.01
            )
        assert "order-123" in str(exc_info.value)
        assert "Timeout" in str(exc_info.value)


# ---------------------------------------------------------------------------
# wait_for_fill
# ---------------------------------------------------------------------------


class TestAsyncNewOrderWaitForFill:
    @pytest.mark.asyncio
    async def test_wait_for_fill_resolves_when_filled(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.FILLED)
        result = await new_order.wait_for_fill(timeout=5)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_wait_for_fill_raises_on_timeout(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.NEW)
        with pytest.raises(WaitTimeoutError):
            await new_order.wait_for_fill(timeout=0.05)


# ---------------------------------------------------------------------------
# wait_for_terminal_status
# ---------------------------------------------------------------------------


class TestAsyncNewOrderWaitForTerminalStatus:
    @pytest.mark.asyncio
    async def test_wait_for_terminal_resolves_on_filled(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.FILLED)
        result = await new_order.wait_for_terminal_status(timeout=5)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_wait_for_terminal_resolves_on_cancelled(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.CANCELLED)
        result = await new_order.wait_for_terminal_status(timeout=5)
        assert result.status == OrderStatus.CANCELLED

    @pytest.mark.asyncio
    async def test_wait_for_terminal_resolves_on_rejected(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        mock_client.get_order.return_value = _make_order(OrderStatus.REJECTED)
        result = await new_order.wait_for_terminal_status(timeout=5)
        assert result.status == OrderStatus.REJECTED

    @pytest.mark.asyncio
    async def test_wait_for_terminal_raises_on_timeout(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        # PARTIALLY_FILLED is not terminal
        mock_client.get_order.return_value = _make_order(OrderStatus.PARTIALLY_FILLED)
        with pytest.raises(WaitTimeoutError):
            await new_order.wait_for_terminal_status(timeout=0.05)


# ---------------------------------------------------------------------------
# cancel
# ---------------------------------------------------------------------------


class TestAsyncNewOrderCancel:
    @pytest.mark.asyncio
    async def test_cancel_calls_client_cancel_order(self) -> None:
        new_order, mock_client, _ = _make_async_new_order()
        await new_order.cancel()
        mock_client.cancel_order.assert_called_once_with(
            order_id="order-123", account_id="account-456"
        )
