"""Tests for MultilegOrderRequest and PreflightMultiLegRequest validation."""

from decimal import Decimal
from typing import Any, Dict, List, Type, Union
import pytest

from public_api_sdk.models.option import (
    MultilegOrderRequest,
    PreflightMultiLegRequest,
    OrderLegRequest,
    LegInstrument,
    LegInstrumentType,
)
from public_api_sdk.models.order import (
    OrderSide,
    OrderType,
    TimeInForce,
    OrderExpirationRequest,
    OpenCloseIndicator,
)


class TestMultilegOrderRequestValidation:
    """Tests specific to MultilegOrderRequest (UUID validation)."""

    def setup_method(self) -> None:
        self.valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        self.invalid_uuid = "not-a-valid-uuid"
        self.base_expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.DAY, expiration_time=None
        )
        self.base_legs = self._create_valid_legs()

    def _create_valid_legs(self) -> List[OrderLegRequest]:
        """Helper to create a valid set of legs."""
        return [
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00160000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.SELL,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
        ]

    def test_valid_uuid(self) -> None:
        """Test that a valid UUID is accepted."""
        order = MultilegOrderRequest(
            order_id=self.valid_uuid,
            quantity=10,
            type=OrderType.LIMIT,
            limit_price=Decimal("1.50"),
            expiration=self.base_expiration,
            legs=self.base_legs,
        )
        assert order.order_id == self.valid_uuid

    def test_invalid_uuid(self) -> None:
        """Test that an invalid UUID is rejected."""
        with pytest.raises(ValueError, match="`order_id` must be a valid UUID"):
            MultilegOrderRequest(
                order_id=self.invalid_uuid,
                quantity=10,
                type=OrderType.LIMIT,
                limit_price=Decimal("1.50"),
                expiration=self.base_expiration,
                legs=self.base_legs,
            )

    def test_quantity_required(self) -> None:
        """Test that quantity is required for MultilegOrderRequest."""
        with pytest.raises(ValueError):
            MultilegOrderRequest(  # type: ignore[call-arg]
                order_id=self.valid_uuid,
                type=OrderType.LIMIT,
                limit_price=Decimal("1.50"),
                expiration=self.base_expiration,
                legs=self.base_legs,
            )

    def test_limit_price_optional(self) -> None:
        """Test that limit_price is optional for MultilegOrderRequest."""
        order = MultilegOrderRequest(
            order_id=self.valid_uuid,
            quantity=10,
            type=OrderType.LIMIT,
            limit_price=None,
            expiration=self.base_expiration,
            legs=self.base_legs,
        )
        assert order.limit_price is None


class TestSharedMultilegValidation:
    """Tests for validations shared between MultilegOrderRequest and PreflightMultiLegRequest."""

    def setup_method(self) -> None:
        self.valid_uuid = "550e8400-e29b-41d4-a716-446655440000"
        self.base_expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.DAY, expiration_time=None
        )

    def _create_request(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
        **kwargs: Any,
    ) -> Union[MultilegOrderRequest, PreflightMultiLegRequest]:
        base_args: Dict[str, Any] = {
            (
                "type" if request_class == MultilegOrderRequest else "order_type"
            ): OrderType.LIMIT,
            "expiration": self.base_expiration,
            "limit_price": Decimal("1.50"),
            "legs": self._create_valid_legs(),
        }
        # add `order_id` only for MultilegOrderRequest
        if request_class == MultilegOrderRequest:
            base_args["order_id"] = kwargs.pop("order_id", self.valid_uuid)
            base_args["quantity"] = kwargs.pop("quantity", 10)
        else:
            # PreflightMultiLegRequest has optional `quantity`
            if "quantity" in kwargs:
                base_args["quantity"] = kwargs.pop("quantity")
        base_args.update(kwargs)
        return request_class(**base_args)

    def _create_valid_legs(self, num_legs: int = 2) -> List[OrderLegRequest]:
        """Helper to create a valid set of legs."""
        legs = []
        for i in range(num_legs):
            legs.append(
                OrderLegRequest(
                    instrument=LegInstrument(
                        symbol=f"AAPL230120C0015{i}000", type=LegInstrumentType.OPTION
                    ),
                    side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                )
            )
        return legs

    def _create_legs_with_equity(
        self, num_option_legs: int = 1, num_equity_legs: int = 1
    ) -> List[OrderLegRequest]:
        """Helper to create legs with both option and equity legs."""
        legs = []
        for i in range(num_option_legs):
            legs.append(
                OrderLegRequest(
                    instrument=LegInstrument(
                        symbol=f"AAPL230120C0015{i}000", type=LegInstrumentType.OPTION
                    ),
                    side=OrderSide.BUY if i % 2 == 0 else OrderSide.SELL,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                )
            )
        for i in range(num_equity_legs):
            legs.append(
                OrderLegRequest(
                    instrument=LegInstrument(
                        symbol="AAPL", type=LegInstrumentType.EQUITY
                    ),
                    side=OrderSide.BUY,
                    ratio_quantity=100,
                )
            )
        return legs

    # quantity validation tests
    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_zero_quantity_invalid(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that zero quantity is rejected."""
        with pytest.raises(ValueError, match="`quantity` must be greater than 0"):
            self._create_request(request_class, quantity=0)

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_negative_quantity_invalid(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that negative quantity is rejected."""
        with pytest.raises(ValueError, match="`quantity` must be greater than 0"):
            self._create_request(request_class, quantity=-10)

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_positive_quantity_valid(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that positive quantity is valid."""
        request = self._create_request(request_class, quantity=100)
        assert request.quantity == 100

    # order type validation tests
    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_only_limit_orders_allowed(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that only LIMIT orders are allowed for multi-leg orders."""
        limit_request = self._create_request(request_class)
        order_type_attr = (
            "type" if request_class == MultilegOrderRequest else "order_type"
        )
        assert getattr(limit_request, order_type_attr) == OrderType.LIMIT

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    @pytest.mark.parametrize(
        "order_type", [OrderType.MARKET, OrderType.STOP, OrderType.STOP_LIMIT]
    )
    def test_non_limit_orders_rejected(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
        order_type: OrderType,
    ) -> None:
        """Test that non-LIMIT order types are rejected."""
        order_type_key = (
            "type" if request_class == MultilegOrderRequest else "order_type"
        )
        with pytest.raises(
            ValueError, match="Only LIMIT orders are allowed for multi-leg orders"
        ):
            self._create_request(request_class, **{order_type_key: order_type})

    # legs validation tests
    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_minimum_two_legs_required(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that at least 2 legs are required."""
        with pytest.raises(
            ValueError, match="Multi-leg orders must have between 2 and 6 legs, got 1"
        ):
            self._create_request(request_class, legs=self._create_valid_legs(1))

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_maximum_six_legs_allowed(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that maximum 6 legs are allowed."""
        with pytest.raises(
            ValueError, match="Multi-leg orders must have between 2 and 6 legs, got 7"
        ):
            self._create_request(request_class, legs=self._create_valid_legs(7))

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    @pytest.mark.parametrize("num_legs", [2, 3, 4, 5, 6])
    def test_valid_leg_counts(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
        num_legs: int,
    ) -> None:
        """Test that 2-6 legs are valid."""
        request = self._create_request(
            request_class, legs=self._create_valid_legs(num_legs)
        )
        assert len(request.legs) == num_legs

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_at_most_one_equity_leg(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that at most 1 equity leg is allowed."""
        # Valid: 1 equity leg with 1 option leg
        valid_request = self._create_request(
            request_class,
            legs=self._create_legs_with_equity(num_option_legs=1, num_equity_legs=1),
        )
        assert len(valid_request.legs) == 2

        # Invalid: 2 equity legs
        with pytest.raises(
            ValueError, match="Multi-leg orders can have at most 1 equity leg, got 2"
        ):
            self._create_request(
                request_class,
                legs=self._create_legs_with_equity(
                    num_option_legs=1, num_equity_legs=2
                ),
            )

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_empty_legs_invalid(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that empty legs list is rejected."""
        with pytest.raises(
            ValueError, match="Multi-leg orders must have between 2 and 6 legs, got 0"
        ):
            self._create_request(request_class, legs=[])

    # limit price validation tests
    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_limit_price_decimal_precision(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that decimal values are properly handled."""
        request = self._create_request(request_class, limit_price=Decimal("123.456"))
        assert request.limit_price == Decimal("123.456")

        request2 = self._create_request(request_class, limit_price=Decimal("0.01"))
        assert request2.limit_price == Decimal("0.01")

    @pytest.mark.parametrize(
        "request_class", [MultilegOrderRequest, PreflightMultiLegRequest]
    )
    def test_negative_limit_price_valid(
        self,
        request_class: Union[
            Type[MultilegOrderRequest], Type[PreflightMultiLegRequest]
        ],
    ) -> None:
        """Test that negative limit price is valid (for credit spreads)."""
        request = self._create_request(request_class, limit_price=Decimal("-1.50"))
        assert request.limit_price == Decimal("-1.50")


class TestOrderLegRequestValidation:
    """Tests for OrderLegRequest validation."""

    def test_ratio_quantity_positive(self) -> None:
        """Test that ratio_quantity must be positive."""
        leg = OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
            ),
            side=OrderSide.BUY,
            open_close_indicator=OpenCloseIndicator.OPEN,
            ratio_quantity=10,
        )
        assert leg.ratio_quantity == 10

    def test_ratio_quantity_zero_invalid(self) -> None:
        """Test that zero ratio_quantity is rejected."""
        with pytest.raises(ValueError, match="`ratio_quantity` must be greater than 0"):
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=0,
            )

    def test_ratio_quantity_negative_invalid(self) -> None:
        """Test that negative ratio_quantity is rejected."""
        with pytest.raises(ValueError, match="`ratio_quantity` must be greater than 0"):
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=-5,
            )

    def test_open_close_required_for_option(self) -> None:
        """Test that open_close_indicator is required for OPTION legs."""
        with pytest.raises(
            ValueError, match="`open_close_indicator` is required for OPTION legs"
        ):
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                ratio_quantity=1,
            )

    def test_open_close_not_allowed_for_equity(self) -> None:
        """Test that open_close_indicator is not allowed for EQUITY legs."""
        with pytest.raises(
            ValueError,
            match="`open_close_indicator` should not be provided for EQUITY legs",
        ):
            OrderLegRequest(
                instrument=LegInstrument(symbol="AAPL", type=LegInstrumentType.EQUITY),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=100,
            )

    def test_equity_leg_without_open_close(self) -> None:
        """Test that EQUITY legs without open_close_indicator are valid."""
        leg = OrderLegRequest(
            instrument=LegInstrument(symbol="AAPL", type=LegInstrumentType.EQUITY),
            side=OrderSide.SELL,
            ratio_quantity=100,
        )
        assert leg.open_close_indicator is None
        assert leg.ratio_quantity == 100

    def test_option_leg_with_open_close(self) -> None:
        """Test that OPTION legs with open_close_indicator are valid."""
        leg = OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL230120P00140000", type=LegInstrumentType.OPTION
            ),
            side=OrderSide.SELL,
            open_close_indicator=OpenCloseIndicator.CLOSE,
            ratio_quantity=2,
        )
        assert leg.open_close_indicator == OpenCloseIndicator.CLOSE
        assert leg.ratio_quantity == 2

    def test_both_order_sides_valid(self) -> None:
        """Test that both BUY and SELL sides are valid."""
        buy_leg = OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
            ),
            side=OrderSide.BUY,
            open_close_indicator=OpenCloseIndicator.OPEN,
            ratio_quantity=1,
        )
        assert buy_leg.side == OrderSide.BUY

        sell_leg = OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL230120C00160000", type=LegInstrumentType.OPTION
            ),
            side=OrderSide.SELL,
            open_close_indicator=OpenCloseIndicator.CLOSE,
            ratio_quantity=1,
        )
        assert sell_leg.side == OrderSide.SELL


class TestPreflightMultiLegRequestValidation:
    """Tests specific to PreflightMultiLegRequest."""

    def setup_method(self) -> None:
        self.base_expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.DAY, expiration_time=None
        )
        self.base_legs = [
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00150000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.BUY,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
            OrderLegRequest(
                instrument=LegInstrument(
                    symbol="AAPL230120C00160000", type=LegInstrumentType.OPTION
                ),
                side=OrderSide.SELL,
                open_close_indicator=OpenCloseIndicator.OPEN,
                ratio_quantity=1,
            ),
        ]

    def test_quantity_optional(self) -> None:
        """Test that quantity is optional for PreflightMultiLegRequest."""
        request = PreflightMultiLegRequest(
            order_type=OrderType.LIMIT,
            limit_price=Decimal("1.50"),
            expiration=self.base_expiration,
            legs=self.base_legs,
        )
        assert request.quantity is None

    def test_quantity_can_be_provided(self) -> None:
        """Test that quantity can be provided for PreflightMultiLegRequest."""
        request = PreflightMultiLegRequest(
            order_type=OrderType.LIMIT,
            quantity=10,
            limit_price=Decimal("1.50"),
            expiration=self.base_expiration,
            legs=self.base_legs,
        )
        assert request.quantity == 10

    def test_limit_price_required(self) -> None:
        """Test that limit_price is required for PreflightMultiLegRequest."""
        with pytest.raises(ValueError):
            PreflightMultiLegRequest(  # type: ignore[call-arg]
                order_type=OrderType.LIMIT,
                expiration=self.base_expiration,
                legs=self.base_legs,
            )
