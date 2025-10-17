import threading
import time
from typing import TYPE_CHECKING, Optional, Callable, Union, List, Coroutine, Any
from datetime import datetime, timezone

from pydantic import BaseModel, Field

from .order import Order, OrderStatus

if TYPE_CHECKING:
    from ..public_api_client import PublicApiClient
    from ..order_subscription_manager import OrderSubscriptionManager


class OrderUpdate(BaseModel):
    order_id: str = Field(...)
    account_id: str = Field(...)
    old_status: Optional[OrderStatus] = Field(None)
    new_status: OrderStatus = Field(...)
    order: Order = Field(...)
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="Last updated timestamp",
    )


OrderUpdateCallback = Union[
    Callable[[OrderUpdate], None], Callable[[OrderUpdate], Coroutine[Any, Any, None]]
]


class OrderSubscriptionConfig(BaseModel):
    """Configuration for order subscription."""

    polling_frequency_seconds: float = Field(
        default=1.0,
        ge=0.1,
        le=60.0,
        description="How often to poll for order updates (0.1 to 60 seconds)",
    )
    retry_on_error: bool = Field(
        default=True, description="Whether to retry on API errors"
    )
    max_retries: int = Field(
        default=3, ge=0, le=10, description="Maximum number of retry attempts"
    )
    exponential_backoff: bool = Field(
        default=True, description="Use exponential backoff for retries"
    )


class WaitTimeoutError(Exception):
    """Raised when waiting for an order status times out."""


class NewOrder:
    """
    Represents a newly placed order with methods for tracking updates and managing the order.

    This object is returned by place_order() and place_multileg_order() methods.
    """

    def __init__(
        self,
        order_id: str,
        account_id: str,
        client: "PublicApiClient",
        subscription_manager: "OrderSubscriptionManager",
    ):
        """
        Initialize a NewOrder instance.

        Args:
            order_id: The order ID
            account_id: The account ID
            client: Reference to the PublicApiClient
            subscription_manager: Reference to the OrderSubscriptionManager
        """
        self._order_id = order_id
        self._account_id = account_id
        self._client = client
        self._subscription_manager = subscription_manager
        self._subscription_id: Optional[str] = None
        self._last_known_status: Optional[OrderStatus] = None
        self._lock = threading.Lock()

    @property
    def order_id(self) -> str:
        return self._order_id

    @property
    def account_id(self) -> str:
        return self._account_id

    def subscribe_updates(
        self,
        callback: OrderUpdateCallback,
        config: Optional[OrderSubscriptionConfig] = None,
    ) -> str:
        """
        Subscribe to order status updates.

        Args:
            callback: Function to call when order status changes
            config: Optional subscription configuration

        Returns:
            Subscription ID that can be used to unsubscribe

        Example:
            ```python
            def on_update(update: OrderUpdate):
                print(f"Order {update.order_id}: {update.old_status} -> {update.new_status}")

            subscription_id = new_order.subscribe_updates(on_update)
            ```
        """
        if self._subscription_id:
            self.unsubscribe()

        self._subscription_id = self._subscription_manager.subscribe_order(
            order_id=self._order_id,
            account_id=self._account_id,
            callback=callback,
            config=config,
        )
        return self._subscription_id

    def unsubscribe(self) -> bool:
        """
        Unsubscribe from order updates.

        Returns:
            True if unsubscribed successfully, False if not subscribed
        """
        if not self._subscription_id:
            return False

        success = self._subscription_manager.unsubscribe(self._subscription_id)
        if success:
            self._subscription_id = None
        return success

    def get_status(self) -> OrderStatus:
        """
        Get the current order status by fetching from the API.

        Returns:
            Current order status
        """
        order = self._client.get_order(
            order_id=self._order_id, account_id=self._account_id
        )
        with self._lock:
            self._last_known_status = order.status
        return order.status

    def get_details(self) -> Order:
        """
        Get the full order details by fetching from the API.

        Returns:
            Current order details including status, fills, etc.
        """
        order = self._client.get_order(
            order_id=self._order_id, account_id=self._account_id
        )
        with self._lock:
            self._last_known_status = order.status
        return order

    def wait_for_status(
        self,
        target_status: Union[OrderStatus, List[OrderStatus]],
        timeout: Optional[float] = None,
        polling_interval: float = 1.0,
    ) -> Order:
        """
        Wait synchronously for the order to reach a specific status.

        Args:
            target_status: Status to wait for, or list of statuses
            timeout: Maximum time to wait in seconds (None for no timeout)
            polling_interval: How often to check status (seconds)

        Returns:
            Order details when target status is reached

        Raises:
            WaitTimeoutError: If timeout is exceeded

        Example:
            ```python
            # Wait for order to be filled
            order = new_order.wait_for_status(OrderStatus.FILLED, timeout=60)

            # Wait for any terminal status
            order = new_order.wait_for_status(
                [OrderStatus.FILLED, OrderStatus.CANCELLED, OrderStatus.REJECTED],
                timeout=30
            )
            ```
        """
        if isinstance(target_status, OrderStatus):
            target_statuses = [target_status]
        else:
            target_statuses = target_status

        start_time = time.time()

        while True:
            order = self.get_details()

            if order.status in target_statuses:
                return order

            # check timeout
            if timeout is not None:
                elapsed = time.time() - start_time
                if elapsed >= timeout:
                    raise WaitTimeoutError(
                        f"Timeout waiting for order {self._order_id} to reach "
                        f"status {target_statuses}. Current status: {order.status}"
                    )

            # sleep before next check
            time.sleep(polling_interval)

    def wait_for_fill(self, timeout: Optional[float] = None) -> Order:
        """
        Wait for the order to be filled.

        Args:
            timeout: Maximum time to wait in seconds (None for no timeout)

        Returns:
            Order details when filled

        Raises:
            WaitTimeoutError: If timeout is exceeded

        Example:
            ```python
            try:
                order = new_order.wait_for_fill(timeout=60)
                print(f"Order filled at {order.average_price}")
            except WaitTimeoutError:
                print("Order not filled within timeout")
            ```
        """
        return self.wait_for_status(OrderStatus.FILLED, timeout=timeout)

    def wait_for_terminal_status(self, timeout: Optional[float] = None) -> Order:
        """
        Wait for the order to reach a terminal status (filled, cancelled, rejected, expired).

        Args:
            timeout: Maximum time to wait in seconds (None for no timeout)

        Returns:
            Order details when terminal status is reached

        Raises:
            WaitTimeoutError: If timeout is exceeded
        """
        terminal_statuses = [
            OrderStatus.FILLED,
            OrderStatus.CANCELLED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
            OrderStatus.REPLACED,
        ]
        return self.wait_for_status(terminal_statuses, timeout=timeout)

    def cancel(self) -> None:
        """
        Cancel the order.

        Note: Cancellation is asynchronous. Use wait_for_status() or subscribe_updates()
        to confirm the cancellation.

        Example:
            ```python
            new_order.cancel()
            # wait for cancellation to be confirmed
            order = new_order.wait_for_status(OrderStatus.CANCELLED, timeout=10)
            ```
        """
        self._client.cancel_order(order_id=self._order_id, account_id=self._account_id)

    def __repr__(self) -> str:
        return f"NewOrder(order_id={self._order_id}, account_id={self._account_id})"

    def __del__(self) -> None:
        try:
            if self._subscription_id:
                self.unsubscribe()
        except Exception:  # pylint: disable=broad-except
            # must catch all exceptions in __del__ to prevent interpreter errors
            pass
