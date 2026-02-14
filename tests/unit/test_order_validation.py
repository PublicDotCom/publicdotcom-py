"""Comprehensive tests for order model validation."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from public_api_sdk.models import (
    OrderInstrument,
    OrderSide,
    OrderType,
    InstrumentType,
    TimeInForce,
    OrderExpirationRequest,
    OrderRequest,
    PreflightRequest,
    LegInstrument,
    LegInstrumentType,
    OpenCloseIndicator,
    OrderLegRequest,
    PreflightMultiLegRequest,
)


class TestOrderExpirationValidation:
    """Tests for OrderExpirationRequest validation."""

    def test_day_time_in_force_no_expiration_time(self):
        """DAY orders should not have expiration_time."""
        # Valid: DAY without expiration_time
        expiration = OrderExpirationRequest(time_in_force=TimeInForce.DAY)
        assert expiration.time_in_force == TimeInForce.DAY
        assert expiration.expiration_time is None

    def test_day_time_in_force_with_expiration_time_fails(self):
        """DAY orders should fail if expiration_time is provided."""
        with pytest.raises(ValueError, match="should not be provided"):
            OrderExpirationRequest(
                time_in_force=TimeInForce.DAY,
                expiration_time=datetime.now(timezone.utc),
            )

    def test_gtd_requires_expiration_time(self):
        """GTD orders require expiration_time."""
        with pytest.raises(ValueError, match="required"):
            OrderExpirationRequest(time_in_force=TimeInForce.GTD)

    def test_gtd_expiration_within_90_days(self):
        """GTD expiration must be within 90 days."""
        valid_date = datetime.now(timezone.utc) + timedelta(days=30)
        expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.GTD,
            expiration_time=valid_date,
        )
        assert expiration.time_in_force == TimeInForce.GTD

    def test_gtd_expiration_exceeds_90_days_fails(self):
        """GTD expiration cannot exceed 90 days."""
        invalid_date = datetime.now(timezone.utc) + timedelta(days=100)
        with pytest.raises(ValueError, match="90 days"):
            OrderExpirationRequest(
                time_in_force=TimeInForce.GTD,
                expiration_time=invalid_date,
            )

    def test_gtd_naive_datetime_converted_to_utc(self):
        """Naive datetime should be treated as UTC."""
        naive_date = datetime.now() + timedelta(days=30)
        # Should not raise
        expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.GTD,
            expiration_time=naive_date,
        )
        assert expiration.expiration_time is not None

    def test_serialization_uses_utc_format(self):
        """GTD expiration should serialize to UTC ISO format."""
        expiration_time = datetime(2026, 6, 15, 14, 30, 0, tzinfo=timezone.utc)
        expiration = OrderExpirationRequest(
            time_in_force=TimeInForce.GTD,
            expiration_time=expiration_time,
        )
        serialized = expiration.model_dump(by_alias=True)
        assert serialized["timeInForce"] == "GTD"
        assert serialized["expirationTime"] == "2026-06-15T14:30:00Z"


class TestQuantityValidation:
    """Tests for quantity and amount validation."""

    def test_quantity_must_be_positive(self):
        """Quantity must be greater than 0."""
        with pytest.raises(ValueError, match="quantity.*greater than 0"):
            PreflightRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("0"),
                limit_price=Decimal("150.00"),
            )

    def test_quantity_negative_fails(self):
        """Negative quantity should fail."""
        with pytest.raises(ValueError, match="quantity.*greater than 0"):
            PreflightRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("-10"),
                limit_price=Decimal("150.00"),
            )

    def test_amount_must_be_positive(self):
        """Amount must be greater than 0."""
        with pytest.raises(ValueError, match="amount must be greater than 0"):
            PreflightRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                amount=Decimal("0"),
            )

    def test_amount_decimal_places_limited(self):
        """Amount cannot have more than 2 decimal places."""
        with pytest.raises(ValueError, match="2 decimal places"):
            PreflightRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                amount=Decimal("100.123"),
            )

    def test_amount_two_decimal_places_allowed(self):
        """Amount with exactly 2 decimal places should work."""
        request = PreflightRequest(
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            amount=Decimal("100.50"),
        )
        assert request.amount == Decimal("100.50")

    def test_quantity_xor_amount_both_specified_fails(self):
        """Cannot specify both quantity and amount."""
        with pytest.raises(ValueError, match="Only one of"):
            PreflightRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("10"),
                amount=Decimal("1000.00"),
                limit_price=Decimal("100.00"),
            )

    def test_quantity_xor_amount_none_specified_fails(self):
        """Must specify either quantity or amount."""
        with pytest.raises(ValueError, match="Either.*must be specified"):
            PreflightRequest(
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                limit_price=Decimal("100.00"),
            )


class TestLimitPriceValidation:
    """Tests for limit price validation."""

    def test_limit_price_only_for_limit_orders(self):
        """limit_price should fail for MARKET orders."""
        with pytest.raises(ValueError, match="limit_price.*can only be set for"):
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("10"),
                limit_price=Decimal("150.00"),
            )

    def test_limit_price_allowed_for_limit(self):
        """limit_price should work for LIMIT orders."""
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
        )
        assert order.limit_price == Decimal("150.00")

    def test_limit_price_allowed_for_stop_limit(self):
        """limit_price should work for STOP_LIMIT orders."""
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.STOP_LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            limit_price=Decimal("150.00"),
            stop_price=Decimal("145.00"),
        )
        assert order.limit_price == Decimal("150.00")

    def test_limit_price_not_required_for_limit(self):
        """limit_price is optional even for LIMIT orders."""
        # This might be intentional for certain order types
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            # limit_price omitted
        )
        assert order.limit_price is None


class TestStopPriceValidation:
    """Tests for stop price validation."""

    def test_stop_price_only_for_stop_orders(self):
        """stop_price should fail for MARKET orders."""
        with pytest.raises(ValueError, match="stop_price.*can only be set for"):
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.MARKET,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("10"),
                stop_price=Decimal("145.00"),
            )

    def test_stop_price_only_for_limit_orders_fails(self):
        """stop_price should fail for LIMIT orders."""
        with pytest.raises(ValueError, match="stop_price.*can only be set for"):
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("10"),
                limit_price=Decimal("150.00"),
                stop_price=Decimal("145.00"),
            )

    def test_stop_price_allowed_for_stop(self):
        """stop_price should work for STOP orders."""
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.SELL,
            order_type=OrderType.STOP,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            stop_price=Decimal("145.00"),
        )
        assert order.stop_price == Decimal("145.00")

    def test_stop_price_allowed_for_stop_limit(self):
        """stop_price should work for STOP_LIMIT orders."""
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.SELL,
            order_type=OrderType.STOP_LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
            limit_price=Decimal("140.00"),
            stop_price=Decimal("145.00"),
        )
        assert order.stop_price == Decimal("145.00")


class TestMultiLegOrderValidation:
    """Tests for multi-leg order validation."""

    def test_multileg_requires_at_least_one_leg(self):
        """Multi-leg order must have at least one leg."""
        # Empty legs should fail - checking if validation exists
        with pytest.raises((ValueError, TypeError)):
            PreflightMultiLegRequest(
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal("1"),
                limit_price=Decimal("3.45"),
                legs=[],  # Empty legs
            )

    def test_valid_multileg_with_two_legs(self):
        """Valid two-leg option spread."""
        request = PreflightMultiLegRequest(
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("1"),
            limit_price=Decimal("3.45"),
            legs=[
                OrderLegRequest(
                    instrument=LegInstrument(symbol="AAPL251024C00110000", type=LegInstrumentType.OPTION),
                    side=OrderSide.SELL,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                ),
                OrderLegRequest(
                    instrument=LegInstrument(symbol="AAPL251024C00120000", type=LegInstrumentType.OPTION),
                    side=OrderSide.BUY,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                ),
            ],
        )
        assert len(request.legs) == 2
        assert request.legs[0].side == OrderSide.SELL
        assert request.legs[1].side == OrderSide.BUY


class TestOrderRequestEdgeCases:
    """Edge case tests for OrderRequest."""

    def test_order_id_uuid_validation(self):
        """order_id should accept valid UUID string."""
        valid_uuid = str(uuid.uuid4())
        order = OrderRequest(
            order_id=valid_uuid,
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
        )
        assert order.order_id == valid_uuid

    def test_symbol_case_sensitivity(self):
        """Test that symbol case is preserved."""
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="aapl", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.MARKET,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10"),
        )
        assert order.instrument.symbol == "aapl"

    def test_decimal_precision_preserved(self):
        """Test that Decimal precision is maintained."""
        order = OrderRequest(
            order_id=str(uuid.uuid4()),
            instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=Decimal("10.5"),
            limit_price=Decimal("150.1234"),
        )
        assert order.quantity == Decimal("10.5")
        assert order.limit_price == Decimal("150.1234")
