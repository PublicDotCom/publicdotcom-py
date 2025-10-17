"""Tests for OrderRequest and PreflightRequest validation."""

from decimal import Decimal
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Type, Union
import pytest

from public_api_sdk.models.order import (
    OrderRequest,
    PreflightRequest,
    OrderInstrument,
    OrderSide,
    OrderType,
    TimeInForce,
    OrderExpirationRequest,
)
from public_api_sdk.models.instrument_type import InstrumentType


class TestOrderRequestValidation:
    """Tests specific to OrderRequest (UUID validation)."""

    def setup_method(self) -> None:
        self.valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        self.invalid_uuid = "not-a-valid-uuid"
        self.base_instrument = OrderInstrument(
            symbol="AAPL", type=InstrumentType.EQUITY
        )
        self.base_expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.DAY, expiration_time=None
        )

    def test_valid_uuid(self) -> None:
        """Test that a valid UUID is accepted."""
        order = OrderRequest(
            order_id=self.valid_uuid,
            instrument=self.base_instrument,
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=self.base_expiration,
            quantity=100,
        )
        assert order.order_id == self.valid_uuid

    def test_invalid_uuid(self) -> None:
        """Test that an invalid UUID is rejected."""
        with pytest.raises(ValueError, match="order_id must be a valid UUID"):
            OrderRequest(
                order_id=self.invalid_uuid,
                instrument=self.base_instrument,
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                expiration=self.base_expiration,
                quantity=100,
            )


class TestSharedValidation:
    """Tests for validations shared between OrderRequest and PreflightRequest."""

    def setup_method(self) -> None:
        self.valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        self.base_instrument = OrderInstrument(
            symbol="AAPL", type=InstrumentType.EQUITY
        )
        self.base_expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.DAY, expiration_time=None
        )

    def _create_request(
        self,
        request_class: Union[Type[OrderRequest], Type[PreflightRequest]],
        **kwargs: Any,
    ) -> Union[OrderRequest, PreflightRequest]:
        """Helper to create OrderRequest or PreflightRequest with common defaults."""
        base_args: Dict[str, Any] = {
            "instrument": self.base_instrument,
            "order_side": OrderSide.BUY,
            "order_type": OrderType.MARKET,
            "expiration": self.base_expiration,
        }
        # add order_id only for OrderRequest
        if request_class == OrderRequest:
            base_args["order_id"] = kwargs.pop("order_id", self.valid_uuid)
        base_args.update(kwargs)
        return request_class(**base_args)

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_quantity_or_amount_both(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that both quantity and amount cannot be specified."""
        with pytest.raises(
            ValueError, match="Only one of `quantity` or `amount` can be specified"
        ):
            self._create_request(
                request_class,
                quantity=100,
                amount=Decimal("1000.00"),
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_quantity_or_amount_neither(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that at least one of quantity or amount must be specified."""
        with pytest.raises(
            ValueError, match="Either `quantity` or `amount` must be specified"
        ):
            self._create_request(request_class)

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_quantity_only(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that quantity-only order is valid."""
        request = self._create_request(request_class, quantity=100)
        assert request.quantity == 100
        assert request.amount is None

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_amount_only(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that amount-only order is valid."""
        request = self._create_request(request_class, amount=Decimal("1000.00"))
        assert request.amount == Decimal("1000.00")
        assert request.quantity is None

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_limit_price_valid_for_limit_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that limit_price is accepted for LIMIT orders."""
        request = self._create_request(
            request_class,
            order_type=OrderType.LIMIT,
            quantity=100,
            limit_price=Decimal("150.00"),
        )
        assert request.limit_price == Decimal("150.00")

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_limit_price_valid_for_stop_limit_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that limit_price is accepted for STOP_LIMIT orders."""
        request = self._create_request(
            request_class,
            order_type=OrderType.STOP_LIMIT,
            quantity=100,
            limit_price=Decimal("150.00"),
        )
        assert request.limit_price == Decimal("150.00")

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_limit_price_invalid_for_market_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that limit_price is rejected for MARKET orders."""
        with pytest.raises(
            ValueError,
            match="`limit_price` can only be set for `LIMIT` or `STOP_LIMIT` orders",
        ):
            self._create_request(
                request_class,
                order_type=OrderType.MARKET,
                quantity=100,
                limit_price=Decimal("150.00"),
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_limit_price_invalid_for_stop_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that limit_price is rejected for STOP orders."""
        with pytest.raises(
            ValueError,
            match="`limit_price` can only be set for `LIMIT` or `STOP_LIMIT` orders",
        ):
            self._create_request(
                request_class,
                order_type=OrderType.STOP,
                quantity=100,
                limit_price=Decimal("150.00"),
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_stop_price_valid_for_stop_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that stop_price is accepted for STOP orders."""
        request = self._create_request(
            request_class,
            order_side=OrderSide.SELL,
            order_type=OrderType.STOP,
            quantity=100,
            stop_price=Decimal("140.00"),
        )
        assert request.stop_price == Decimal("140.00")

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_stop_price_valid_for_stop_limit_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that stop_price is accepted for STOP_LIMIT orders."""
        request = self._create_request(
            request_class,
            order_side=OrderSide.SELL,
            order_type=OrderType.STOP_LIMIT,
            quantity=100,
            limit_price=Decimal("139.00"),
            stop_price=Decimal("140.00"),
        )
        assert request.stop_price == Decimal("140.00")

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_stop_price_invalid_for_market_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that stop_price is rejected for MARKET orders."""
        with pytest.raises(
            ValueError,
            match="`stop_price` can only be set for `STOP` or `STOP_LIMIT` orders",
        ):
            self._create_request(
                request_class,
                order_type=OrderType.MARKET,
                quantity=100,
                stop_price=Decimal("140.00"),
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_stop_price_invalid_for_limit_order(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that stop_price is rejected for LIMIT orders."""
        with pytest.raises(
            ValueError,
            match="`stop_price` can only be set for `STOP` or `STOP_LIMIT` orders",
        ):
            self._create_request(
                request_class,
                order_type=OrderType.LIMIT,
                quantity=100,
                limit_price=Decimal("150.00"),
                stop_price=Decimal("140.00"),
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_stop_limit_order_both_prices(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that STOP_LIMIT orders accept both limit_price and stop_price."""
        request = self._create_request(
            request_class,
            order_type=OrderType.STOP_LIMIT,
            quantity=100,
            limit_price=Decimal("150.00"),
            stop_price=Decimal("145.00"),
        )
        assert request.limit_price == Decimal("150.00")
        assert request.stop_price == Decimal("145.00")

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_order_side_values(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that both BUY and SELL order sides are valid."""
        buy_request = self._create_request(
            request_class,
            order_side=OrderSide.BUY,
            quantity=100,
        )
        assert buy_request.order_side == OrderSide.BUY

        sell_request = self._create_request(
            request_class,
            order_id=(
                "550e8400-e29b-41d4-a716-446655440001"
                if request_class == OrderRequest
                else None
            ),
            order_side=OrderSide.SELL,
            quantity=100,
        )
        assert sell_request.order_side == OrderSide.SELL

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_time_in_force_day(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test DAY time in force."""
        request = self._create_request(
            request_class,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=100,
        )
        assert request.expiration.time_in_force == TimeInForce.DAY
        assert request.expiration.expiration_time is None

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_time_in_force_gtd(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test GTD time in force with expiration time."""
        expiration_time = datetime.now(timezone.utc) + timedelta(days=30)
        request = self._create_request(
            request_class,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(
                time_in_force=TimeInForce.GTD, expiration_time=expiration_time
            ),
            quantity=100,
            limit_price=Decimal("150.00"),
        )
        assert request.expiration.time_in_force == TimeInForce.GTD
        assert request.expiration.expiration_time == expiration_time

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_decimal_precision(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that decimal values with up to 2 decimal places are accepted."""
        request = self._create_request(
            request_class,
            order_type=OrderType.LIMIT,
            amount=Decimal("1234.56"),
            limit_price=Decimal("150.999"),
        )
        assert request.amount == Decimal("1234.56")
        assert request.limit_price == Decimal("150.999")

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_zero_quantity_invalid(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that zero quantity is rejected."""
        with pytest.raises(ValueError, match="`quantity` must be greater than 0"):
            self._create_request(request_class, quantity=0)

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_negative_quantity_invalid(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that negative quantity is rejected."""
        with pytest.raises(ValueError, match="`quantity` must be greater than 0"):
            self._create_request(request_class, quantity=-100)

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_zero_amount_invalid(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that zero amount is rejected."""
        with pytest.raises(ValueError, match="amount must be greater than 0"):
            self._create_request(request_class, amount=Decimal("0.00"))

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_negative_amount_invalid(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that negative amount is rejected."""
        with pytest.raises(ValueError, match="amount must be greater than 0"):
            self._create_request(request_class, amount=Decimal("-100.00"))

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_amount_too_many_decimal_places(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that amount with more than 2 decimal places is rejected."""
        with pytest.raises(
            ValueError, match="`amount` cannot have more than 2 decimal places"
        ):
            self._create_request(request_class, amount=Decimal("100.123"))

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_gtd_without_expiration_time(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that GTD orders require expiration_time."""
        with pytest.raises(
            ValueError,
            match="`expiration_time` is required when `time_in_force` is GTD",
        ):
            self._create_request(
                request_class,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(
                    time_in_force=TimeInForce.GTD, expiration_time=None
                ),
                quantity=100,
                limit_price=Decimal("150.00"),
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_day_with_expiration_time(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that DAY orders reject expiration_time."""
        expiration_time = datetime.now(timezone.utc) + timedelta(days=1)
        with pytest.raises(
            ValueError,
            match="`expiration_time` should not be provided when `time_in_force` is DAY",
        ):
            self._create_request(
                request_class,
                expiration=OrderExpirationRequest(
                    time_in_force=TimeInForce.DAY, expiration_time=expiration_time
                ),
                quantity=100,
            )

    @pytest.mark.parametrize("request_class", [OrderRequest, PreflightRequest])
    def test_expiration_time_too_far_in_future(
        self, request_class: Union[Type[OrderRequest], Type[PreflightRequest]]
    ) -> None:
        """Test that expiration_time more than 90 days in future is rejected."""
        expiration_time = datetime.now(timezone.utc) + timedelta(days=91)
        with pytest.raises(
            ValueError,
            match="`expiration_time` cannot be more than 90 days in the future",
        ):
            self._create_request(
                request_class,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(
                    time_in_force=TimeInForce.GTD, expiration_time=expiration_time
                ),
                quantity=100,
                limit_price=Decimal("150.00"),
            )
