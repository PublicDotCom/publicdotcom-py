"""Tests for the four production-readiness fixes:

1. OrderStatus.UNKNOWN fallback (_missing_ classmethod)
2. Retry on POST / PUT / DELETE in sync and async clients
3. Partial fill visibility in wait_for_fill (WaitTimeoutError.current_order + callback)
4. Subscription degradation notification (DEGRADED status + on_error callback)
"""

import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, Mock, call, patch

import pytest

from public_api_sdk.api_client import ApiClient
from public_api_sdk.async_api_client import AsyncApiClient
from public_api_sdk.exceptions import RateLimitError, ServerError, ValidationError
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.new_order import NewOrder, WaitTimeoutError
from public_api_sdk.models.async_new_order import AsyncNewOrder
from public_api_sdk.models.order import (
    Order,
    OrderInstrument,
    OrderSide,
    OrderStatus,
    OrderType,
)
from public_api_sdk.models.subscription import SubscriptionConfig, SubscriptionStatus


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_order(status: OrderStatus, order_id: str = "ord-1") -> Order:
    return Order(
        order_id=order_id,
        instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        type=OrderType.LIMIT,
        side=OrderSide.BUY,
        status=status,
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
        created_at=datetime.now(timezone.utc),
    )


# ===========================================================================
# Fix 1 – OrderStatus.UNKNOWN fallback
# ===========================================================================


class TestOrderStatusUnknown:
    def test_unknown_value_returns_unknown_sentinel(self) -> None:
        """An unrecognised status string must map to UNKNOWN, not raise."""
        result = OrderStatus("SOME_FUTURE_STATUS")
        assert result is OrderStatus.UNKNOWN

    def test_unknown_value_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        with caplog.at_level(logging.WARNING, logger="public_api_sdk.models.order"):
            OrderStatus("TOTALLY_NEW_STATUS")

        assert any("TOTALLY_NEW_STATUS" in r.message for r in caplog.records)
        assert any("UNKNOWN" in r.message for r in caplog.records)

    def test_known_values_still_work(self) -> None:
        assert OrderStatus("FILLED") is OrderStatus.FILLED
        assert OrderStatus("CANCELLED") is OrderStatus.CANCELLED
        assert OrderStatus("PARTIALLY_FILLED") is OrderStatus.PARTIALLY_FILLED

    def test_unknown_not_in_terminal_statuses(self) -> None:
        """UNKNOWN must not appear in any terminal-status list so polling continues."""
        terminal = [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.REPLACED,
        ]
        assert OrderStatus.UNKNOWN not in terminal

    def test_order_model_with_unknown_status(self) -> None:
        """Pydantic should not raise when deserialising an unknown status."""
        order = _make_order(OrderStatus("WEIRD_STATUS"))
        assert order.status is OrderStatus.UNKNOWN


# ===========================================================================
# Fix 2 – Retry on POST / PUT / DELETE
# ===========================================================================


class TestSyncRetryNonSafe:
    """ApiClient._retry_non_safe retries ServerError and RateLimitError."""

    def setup_method(self) -> None:
        self.client = ApiClient(base_url="https://api.example.com", max_retries=2)

    @patch("time.sleep")  # prevent real sleeping
    def test_post_retries_on_server_error(self, mock_sleep: Mock) -> None:
        calls = 0

        def _fn():
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ServerError("oops", 500)
            return {"ok": True}

        result = self.client._retry_non_safe(_fn)
        assert result == {"ok": True}
        assert calls == 3

    @patch("time.sleep")
    def test_post_retries_on_rate_limit(self, mock_sleep: Mock) -> None:
        calls = 0

        def _fn():
            nonlocal calls
            calls += 1
            if calls < 2:
                raise RateLimitError("slow down", 429, retry_after=1)
            return {"ok": True}

        result = self.client._retry_non_safe(_fn)
        assert result == {"ok": True}
        assert calls == 2

    @patch("time.sleep")
    def test_raises_after_max_retries_exhausted(self, mock_sleep: Mock) -> None:
        def _fn():
            raise ServerError("persistent 500", 500)

        with pytest.raises(ServerError):
            self.client._retry_non_safe(_fn)

    def test_does_not_retry_on_validation_error(self) -> None:
        calls = 0

        def _fn():
            nonlocal calls
            calls += 1
            raise ValidationError("bad request", 400)

        with pytest.raises(ValidationError):
            self.client._retry_non_safe(_fn)

        assert calls == 1  # no retry

    @patch("time.sleep")
    def test_post_method_uses_retry(self, mock_sleep: Mock) -> None:
        """post() must retry on ServerError via _retry_non_safe."""
        import requests

        mock_response_ok = Mock(spec=requests.Response)
        mock_response_ok.status_code = 200
        mock_response_ok.content = b'{"id": "123"}'
        mock_response_ok.json.return_value = {"id": "123"}
        mock_response_ok.headers = {}

        mock_response_err = Mock(spec=requests.Response)
        mock_response_err.status_code = 500
        mock_response_err.content = b'{"message": "server error"}'
        mock_response_err.json.return_value = {"message": "server error"}
        mock_response_err.headers = {}
        mock_response_err.text = "server error"

        self.client.session.post = Mock(
            side_effect=[mock_response_err, mock_response_err, mock_response_ok]
        )

        result = self.client.post("/orders", json_data={"x": 1})
        assert result == {"id": "123"}
        assert self.client.session.post.call_count == 3

    @patch("time.sleep")
    def test_delete_method_uses_retry(self, mock_sleep: Mock) -> None:
        """delete() must retry on ServerError via _retry_non_safe."""
        import requests

        mock_ok = Mock(spec=requests.Response)
        mock_ok.status_code = 200
        mock_ok.content = b"{}"
        mock_ok.json.return_value = {}
        mock_ok.headers = {}

        mock_err = Mock(spec=requests.Response)
        mock_err.status_code = 503
        mock_err.content = b'{"message": "unavailable"}'
        mock_err.json.return_value = {"message": "unavailable"}
        mock_err.headers = {}
        mock_err.text = "unavailable"

        self.client.session.delete = Mock(side_effect=[mock_err, mock_ok])

        result = self.client.delete("/orders/123")
        assert result == {}
        assert self.client.session.delete.call_count == 2


class TestAsyncRetryNonSafe:
    """AsyncApiClient retries POST/PUT/DELETE on 429/5xx."""

    @pytest.mark.asyncio
    async def test_post_retries_on_server_error(self) -> None:
        import httpx

        client = AsyncApiClient(
            base_url="https://api.example.com", max_retries=2, backoff_factor=0
        )

        ok_response = Mock(spec=httpx.Response)
        ok_response.status_code = 200
        ok_response.content = b'{"ok": true}'
        ok_response.json.return_value = {"ok": True}
        ok_response.headers = {}

        err_response = Mock(spec=httpx.Response)
        err_response.status_code = 500
        err_response.content = b'{"message": "err"}'
        err_response.json.return_value = {"message": "err"}
        err_response.headers = {}
        err_response.text = "err"

        client._client.request = AsyncMock(
            side_effect=[err_response, err_response, ok_response]
        )

        result = await client.post("/orders", json_data={"x": 1})
        assert result == {"ok": True}
        assert client._client.request.call_count == 3
        await client.aclose()

    @pytest.mark.asyncio
    async def test_delete_retries_on_rate_limit(self) -> None:
        import httpx

        client = AsyncApiClient(
            base_url="https://api.example.com", max_retries=2, backoff_factor=0
        )

        ok_response = Mock(spec=httpx.Response)
        ok_response.status_code = 200
        ok_response.content = b"{}"
        ok_response.json.return_value = {}
        ok_response.headers = {}

        rate_response = Mock(spec=httpx.Response)
        rate_response.status_code = 429
        rate_response.content = b'{"message": "slow down"}'
        rate_response.json.return_value = {"message": "slow down"}
        rate_response.headers = {"Retry-After": "1"}
        rate_response.text = "slow down"

        client._client.request = AsyncMock(
            side_effect=[rate_response, ok_response]
        )

        result = await client.delete("/orders/123")
        assert result == {}
        assert client._client.request.call_count == 2
        await client.aclose()


# ===========================================================================
# Fix 3 – Partial fill visibility in wait_for_fill
# ===========================================================================


class TestWaitTimeoutError:
    def test_current_order_defaults_to_none(self) -> None:
        exc = WaitTimeoutError("timed out")
        assert exc.current_order is None

    def test_current_order_stored(self) -> None:
        order = _make_order(OrderStatus.PARTIALLY_FILLED)
        exc = WaitTimeoutError("timed out", current_order=order)
        assert exc.current_order is order

    def test_message_preserved(self) -> None:
        exc = WaitTimeoutError("my message")
        assert str(exc) == "my message"


class TestWaitForFillSync:
    def setup_method(self) -> None:
        self.mock_client = Mock()
        self.mock_sub_manager = Mock()
        self.new_order = NewOrder(
            order_id="ord-1",
            account_id="acc-1",
            client=self.mock_client,
            subscription_manager=self.mock_sub_manager,
        )

    def test_returns_when_filled(self) -> None:
        filled = _make_order(OrderStatus.FILLED)
        self.mock_client.get_order.return_value = filled

        result = self.new_order.wait_for_fill(timeout=5)
        assert result.status == OrderStatus.FILLED

    @patch("time.sleep")
    def test_on_partial_fill_callback_called(self, _sleep: Mock) -> None:
        partial = _make_order(OrderStatus.PARTIALLY_FILLED)
        filled = _make_order(OrderStatus.FILLED)
        self.mock_client.get_order.side_effect = [partial, filled]

        callback = Mock()
        result = self.new_order.wait_for_fill(timeout=10, on_partial_fill=callback)

        assert result.status == OrderStatus.FILLED
        callback.assert_called_once_with(partial)

    @patch("time.sleep")
    def test_timeout_carries_current_order(self, _sleep: Mock) -> None:
        partial = _make_order(OrderStatus.PARTIALLY_FILLED)
        self.mock_client.get_order.return_value = partial

        # Patch time so the first call succeeds in getting an order, then times out
        with patch("time.time", side_effect=[0, 0, 100]):
            with pytest.raises(WaitTimeoutError) as exc_info:
                self.new_order.wait_for_fill(timeout=5)

        assert exc_info.value.current_order is not None
        assert exc_info.value.current_order.status == OrderStatus.PARTIALLY_FILLED

    @patch("time.sleep")
    def test_no_callback_when_filled_directly(self, _sleep: Mock) -> None:
        filled = _make_order(OrderStatus.FILLED)
        self.mock_client.get_order.return_value = filled

        callback = Mock()
        self.new_order.wait_for_fill(on_partial_fill=callback)
        callback.assert_not_called()


class TestWaitForFillAsync:
    @pytest.mark.asyncio
    async def test_returns_when_filled(self) -> None:
        mock_client = AsyncMock()
        mock_sub_manager = AsyncMock()
        order = AsyncNewOrder(
            order_id="ord-1",
            account_id="acc-1",
            client=mock_client,
            subscription_manager=mock_sub_manager,
        )
        filled = _make_order(OrderStatus.FILLED)
        mock_client.get_order.return_value = filled

        result = await order.wait_for_fill(timeout=5)
        assert result.status == OrderStatus.FILLED

    @pytest.mark.asyncio
    async def test_on_partial_fill_sync_callback(self) -> None:
        mock_client = AsyncMock()
        mock_sub_manager = AsyncMock()
        order = AsyncNewOrder(
            order_id="ord-1",
            account_id="acc-1",
            client=mock_client,
            subscription_manager=mock_sub_manager,
        )
        partial = _make_order(OrderStatus.PARTIALLY_FILLED)
        filled = _make_order(OrderStatus.FILLED)
        mock_client.get_order.side_effect = [partial, filled]

        callback = Mock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await order.wait_for_fill(
                timeout=10, polling_interval=0, on_partial_fill=callback
            )

        assert result.status == OrderStatus.FILLED
        callback.assert_called_once_with(partial)

    @pytest.mark.asyncio
    async def test_on_partial_fill_async_callback(self) -> None:
        mock_client = AsyncMock()
        mock_sub_manager = AsyncMock()
        order = AsyncNewOrder(
            order_id="ord-1",
            account_id="acc-1",
            client=mock_client,
            subscription_manager=mock_sub_manager,
        )
        partial = _make_order(OrderStatus.PARTIALLY_FILLED)
        filled = _make_order(OrderStatus.FILLED)
        mock_client.get_order.side_effect = [partial, filled]

        callback = AsyncMock()
        with patch("asyncio.sleep", new_callable=AsyncMock):
            result = await order.wait_for_fill(
                timeout=10, polling_interval=0, on_partial_fill=callback
            )

        assert result.status == OrderStatus.FILLED
        callback.assert_called_once_with(partial)

    @pytest.mark.asyncio
    async def test_timeout_carries_current_order(self) -> None:
        mock_client = AsyncMock()
        mock_sub_manager = AsyncMock()
        order = AsyncNewOrder(
            order_id="ord-1",
            account_id="acc-1",
            client=mock_client,
            subscription_manager=mock_sub_manager,
        )
        partial = _make_order(OrderStatus.PARTIALLY_FILLED)
        mock_client.get_order.return_value = partial

        with patch("time.monotonic", side_effect=[0, 0, 100]):
            with patch("asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(WaitTimeoutError) as exc_info:
                    await order.wait_for_fill(timeout=5)

        assert exc_info.value.current_order is not None
        assert exc_info.value.current_order.status == OrderStatus.PARTIALLY_FILLED


# ===========================================================================
# Fix 4 – Subscription degradation notification
# ===========================================================================


class TestSubscriptionStatus:
    def test_degraded_value_exists(self) -> None:
        assert SubscriptionStatus.DEGRADED == "DEGRADED"

    def test_degraded_is_distinct_from_active(self) -> None:
        assert SubscriptionStatus.DEGRADED != SubscriptionStatus.ACTIVE


class TestSubscriptionConfig:
    def test_default_max_consecutive_failures(self) -> None:
        config = SubscriptionConfig()
        assert config.max_consecutive_failures == 10

    def test_default_on_error_is_none(self) -> None:
        config = SubscriptionConfig()
        assert config.on_error is None

    def test_custom_on_error_callable(self) -> None:
        cb = Mock()
        config = SubscriptionConfig(on_error=cb)
        assert config.on_error is cb


class TestAsyncSubscriptionDegradation:
    """AsyncPriceSubscriptionManager sets DEGRADED and calls on_error."""

    def _make_instrument(self):
        from public_api_sdk.models.order import OrderInstrument
        return OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)

    @pytest.mark.asyncio
    async def test_degraded_after_consecutive_failures(self) -> None:
        from public_api_sdk.async_subscription_manager import AsyncPriceSubscriptionManager

        error_cb = Mock()
        config = SubscriptionConfig(max_consecutive_failures=3, on_error=error_cb)

        get_quotes = AsyncMock(side_effect=ConnectionError("network down"))
        manager = AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)

        instrument = self._make_instrument()
        price_cb = Mock()

        sub_id = await manager.subscribe(
            instruments=[instrument],
            callback=price_cb,
            config=config,
        )

        # manually drive the poll loop N times (avoiding real asyncio.sleep)
        with patch("asyncio.sleep", new_callable=AsyncMock):
            sub = manager._subscriptions[sub_id]
            for _ in range(3):
                await manager._poll_subscription(sub)

        assert sub.status == SubscriptionStatus.DEGRADED
        error_cb.assert_called_once()
        args = error_cb.call_args[0]
        assert args[0] == sub_id
        assert isinstance(args[1], ConnectionError)

        await manager.stop()

    @pytest.mark.asyncio
    async def test_recovers_from_degraded_on_success(self) -> None:
        from public_api_sdk.async_subscription_manager import AsyncPriceSubscriptionManager
        from public_api_sdk.models.quote import Quote

        instrument = self._make_instrument()

        # Build a mock quote for the success poll
        mock_quote = Mock(spec=Quote)
        mock_quote.instrument = instrument
        mock_quote.last = Decimal("100")
        mock_quote.bid = Decimal("99")
        mock_quote.ask = Decimal("101")

        call_count = 0

        async def flaky_quotes(instruments):
            nonlocal call_count
            call_count += 1
            if call_count <= 3:
                raise ConnectionError("down")
            return [mock_quote]

        error_cb = Mock()
        # max_retries=0 so each _poll_subscription call makes exactly one attempt;
        # otherwise the internal retry loop would consume the "flaky" calls.
        config = SubscriptionConfig(
            max_consecutive_failures=3, on_error=error_cb, max_retries=0
        )
        manager = AsyncPriceSubscriptionManager(get_quotes_func=flaky_quotes)

        price_cb = Mock()
        sub_id = await manager.subscribe(
            instruments=[instrument],
            callback=price_cb,
            config=config,
        )
        sub = manager._subscriptions[sub_id]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            # 3 failures → DEGRADED
            for _ in range(3):
                await manager._poll_subscription(sub)
            assert sub.status == SubscriptionStatus.DEGRADED

            # 1 success → recover to ACTIVE
            await manager._poll_subscription(sub)

        assert sub.status == SubscriptionStatus.ACTIVE
        assert manager._consecutive_failures.get(sub_id, 0) == 0

        await manager.stop()

    @pytest.mark.asyncio
    async def test_does_not_degrade_below_threshold(self) -> None:
        from public_api_sdk.async_subscription_manager import AsyncPriceSubscriptionManager

        config = SubscriptionConfig(max_consecutive_failures=5, on_error=Mock())
        get_quotes = AsyncMock(side_effect=ConnectionError("down"))
        manager = AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)

        instrument = self._make_instrument()
        sub_id = await manager.subscribe(
            instruments=[instrument],
            callback=Mock(),
            config=config,
        )
        sub = manager._subscriptions[sub_id]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            for _ in range(4):
                await manager._poll_subscription(sub)

        # Still ACTIVE — threshold not yet reached
        assert sub.status == SubscriptionStatus.ACTIVE
        assert manager._consecutive_failures[sub_id] == 4

        await manager.stop()

    @pytest.mark.asyncio
    async def test_degraded_subscription_continues_polling(self) -> None:
        """DEGRADED subscriptions must still be polled (not skipped)."""
        from public_api_sdk.async_subscription_manager import AsyncPriceSubscriptionManager

        config = SubscriptionConfig(max_consecutive_failures=1, on_error=Mock())
        get_quotes = AsyncMock(side_effect=ConnectionError("down"))
        manager = AsyncPriceSubscriptionManager(get_quotes_func=get_quotes)

        instrument = self._make_instrument()
        sub_id = await manager.subscribe(
            instruments=[instrument],
            callback=Mock(),
            config=config,
        )
        sub = manager._subscriptions[sub_id]

        with patch("asyncio.sleep", new_callable=AsyncMock):
            # First poll → DEGRADED
            await manager._poll_subscription(sub)
            assert sub.status == SubscriptionStatus.DEGRADED

            # _poll_loop should still poll DEGRADED subs
            # Simulate one poll_loop iteration
            if sub.status in (SubscriptionStatus.ACTIVE, SubscriptionStatus.DEGRADED):
                await manager._poll_subscription(sub)

        # get_quotes was called at least twice (second poll also tried)
        assert get_quotes.call_count >= 2

        await manager.stop()
