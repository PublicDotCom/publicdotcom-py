"""AsyncNewOrder — async counterpart to NewOrder."""

import asyncio
import time
from typing import TYPE_CHECKING, Callable, List, Optional, Union

from .new_order import OrderSubscriptionConfig, OrderUpdateCallback, WaitTimeoutError
from .order import Order, OrderStatus

if TYPE_CHECKING:
    from ..async_order_subscription_manager import AsyncOrderSubscriptionManager
    from ..async_public_api_client import AsyncPublicApiClient


class AsyncNewOrder:
    """Represents a newly placed order with async methods for tracking and management.

    Returned by :meth:`AsyncPublicApiClient.place_order` and
    :meth:`AsyncPublicApiClient.place_multileg_order`.

    Example::

        order = await client.place_order(request)

        # Poll until filled (raises WaitTimeoutError after 60 s)
        details = await order.wait_for_fill(timeout=60)

        # Or subscribe to every status transition
        async def on_update(update):
            print(f"{update.old_status} -> {update.new_status}")

        await order.subscribe_updates(on_update)
    """

    def __init__(
        self,
        order_id: str,
        account_id: str,
        client: "AsyncPublicApiClient",
        subscription_manager: "AsyncOrderSubscriptionManager",
    ) -> None:
        self._order_id = order_id
        self._account_id = account_id
        self._client = client
        self._subscription_manager = subscription_manager
        self._subscription_id: Optional[str] = None
        self._last_known_status: Optional[OrderStatus] = None

    # ------------------------------------------------------------------ #
    # Properties                                                           #
    # ------------------------------------------------------------------ #

    @property
    def order_id(self) -> str:
        return self._order_id

    @property
    def account_id(self) -> str:
        return self._account_id

    # ------------------------------------------------------------------ #
    # Subscription management                                              #
    # ------------------------------------------------------------------ #

    async def subscribe_updates(
        self,
        callback: OrderUpdateCallback,
        config: Optional[OrderSubscriptionConfig] = None,
    ) -> str:
        """Subscribe to order status updates.

        Args:
            callback: Called on each status transition (sync or async)
            config: Optional polling/retry configuration

        Returns:
            Subscription ID
        """
        if self._subscription_id:
            await self.unsubscribe()

        self._subscription_id = await self._subscription_manager.subscribe_order(
            order_id=self._order_id,
            account_id=self._account_id,
            callback=callback,
            config=config,
        )
        return self._subscription_id

    async def unsubscribe(self) -> bool:
        """Stop receiving status updates for this order.

        Returns:
            True if unsubscribed, False if no active subscription
        """
        if not self._subscription_id:
            return False

        success = await self._subscription_manager.unsubscribe(self._subscription_id)
        if success:
            self._subscription_id = None
        return success

    # ------------------------------------------------------------------ #
    # Status / detail fetching                                             #
    # ------------------------------------------------------------------ #

    async def get_status(self) -> OrderStatus:
        """Fetch the current order status from the API.

        Returns:
            Current OrderStatus
        """
        order = await self._client.get_order(
            order_id=self._order_id, account_id=self._account_id
        )
        self._last_known_status = order.status
        return order.status

    async def get_details(self) -> Order:
        """Fetch full order details from the API.

        Returns:
            Order with current status, fills, etc.
        """
        order = await self._client.get_order(
            order_id=self._order_id, account_id=self._account_id
        )
        self._last_known_status = order.status
        return order

    # ------------------------------------------------------------------ #
    # Waiting helpers                                                      #
    # ------------------------------------------------------------------ #

    async def wait_for_status(
        self,
        target_status: Union[OrderStatus, List[OrderStatus]],
        timeout: Optional[float] = None,
        polling_interval: float = 1.0,
    ) -> Order:
        """Poll until the order reaches one of the target statuses.

        Args:
            target_status: Status (or list of statuses) to wait for
            timeout: Maximum seconds to wait; None means wait indefinitely
            polling_interval: Seconds between polls

        Returns:
            Order details once the target status is reached

        Raises:
            WaitTimeoutError: If timeout is exceeded before reaching target status

        Example::

            order = await new_order.wait_for_status(
                [OrderStatus.FILLED, OrderStatus.CANCELLED],
                timeout=30,
            )
        """
        target_statuses = (
            [target_status] if isinstance(target_status, OrderStatus) else target_status
        )

        start = time.monotonic()

        while True:
            order = await self.get_details()

            if order.status in target_statuses:
                return order

            if timeout is not None and time.monotonic() - start >= timeout:
                raise WaitTimeoutError(
                    f"Timeout waiting for order {self._order_id} to reach "
                    f"status {target_statuses}. Current status: {order.status}"
                )

            await asyncio.sleep(polling_interval)

    async def wait_for_fill(
        self,
        timeout: Optional[float] = None,
        on_partial_fill: Optional[Callable[..., None]] = None,
        polling_interval: float = 1.0,
    ) -> Order:
        """Poll until the order is filled.

        Args:
            timeout: Maximum seconds to wait; None means wait indefinitely
            on_partial_fill: Optional callback invoked each time the order
                status is ``PARTIALLY_FILLED``.  May be sync or async.
                Receives the current :class:`Order` as its only argument.
            polling_interval: How often to check status in seconds (default 1s)

        Returns:
            Order details once filled

        Raises:
            WaitTimeoutError: If timeout is exceeded.  The exception's
                ``current_order`` attribute holds the last-seen order state,
                which may have a partial fill quantity.

        Example::

            async def on_partial(order):
                print(f"Partial fill: {order.filled_quantity} shares")

            try:
                order = await new_order.wait_for_fill(timeout=60, on_partial_fill=on_partial)
                print(f"Filled")
            except WaitTimeoutError as e:
                filled = e.current_order.filled_quantity if e.current_order else 0
                print(f"Timed out — {filled} shares filled so far")
        """
        start = time.monotonic()
        last_seen_order: Optional[Order] = None

        while True:
            order = await self.get_details()
            last_seen_order = order

            if order.status == OrderStatus.FILLED:
                return order

            if order.status == OrderStatus.PARTIALLY_FILLED and on_partial_fill:
                if asyncio.iscoroutinefunction(on_partial_fill):
                    await on_partial_fill(order)
                else:
                    on_partial_fill(order)

            if timeout is not None and time.monotonic() - start >= timeout:
                raise WaitTimeoutError(
                    f"Order {self._order_id} did not fill within {timeout}s. "
                    f"Current status: {order.status}",
                    current_order=last_seen_order,
                )

            await asyncio.sleep(polling_interval)

    async def wait_for_terminal_status(self, timeout: Optional[float] = None) -> Order:
        """Poll until the order reaches any terminal status.

        Terminal statuses: FILLED, CANCELLED, REJECTED, EXPIRED, REPLACED.

        Args:
            timeout: Maximum seconds to wait; None means wait indefinitely

        Returns:
            Order details once a terminal status is reached

        Raises:
            WaitTimeoutError: If timeout is exceeded
        """
        return await self.wait_for_status(
            [
                OrderStatus.FILLED,
                OrderStatus.CANCELLED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
                OrderStatus.REPLACED,
            ],
            timeout=timeout,
        )

    # ------------------------------------------------------------------ #
    # Order management                                                     #
    # ------------------------------------------------------------------ #

    async def cancel(self) -> None:
        """Submit a cancellation request for this order.

        Note: Cancellation is asynchronous on the exchange side.
        Use :meth:`wait_for_status` or :meth:`subscribe_updates` to confirm.
        """
        await self._client.cancel_order(
            order_id=self._order_id, account_id=self._account_id
        )

    def __repr__(self) -> str:
        return (
            f"AsyncNewOrder(order_id={self._order_id!r}, "
            f"account_id={self._account_id!r})"
        )
