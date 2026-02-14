"""Shared fixtures for test suite."""
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
    TimeInForce,
    OrderExpirationRequest,
    OrderRequest,
    PreflightRequest,
)


@pytest.fixture
def mock_api_client():
    """Mock API client for testing."""
    return Mock()


@pytest.fixture
def sample_order_instrument():
    """Sample AAPL equity instrument."""
    return OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)


@pytest.fixture
def sample_option_instrument():
    """Sample AAPL option instrument."""
    return OrderInstrument(symbol="AAPL251024C00110000", type=InstrumentType.OPTION)


@pytest.fixture
def sample_order_expiration_day():
    """Sample DAY time in force expiration."""
    return OrderExpirationRequest(time_in_force=TimeInForce.DAY)


@pytest.fixture
def sample_order_expiration_gtd():
    """Sample GTD expiration with valid date."""
    return OrderExpirationRequest(
        time_in_force=TimeInForce.GTD,
        expiration_time=datetime(2026, 3, 1, 12, 0, 0, tzinfo=timezone.utc)
    )


@pytest.fixture
def sample_order_request(sample_order_instrument, sample_order_expiration_day):
    """Sample valid market order request."""
    return OrderRequest(
        order_id=str(uuid.uuid4()),
        instrument=sample_order_instrument,
        order_side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        expiration=sample_order_expiration_day,
        quantity=Decimal("10"),
    )


@pytest.fixture
def sample_limit_order_request(sample_order_instrument, sample_order_expiration_day):
    """Sample valid limit order request."""
    return OrderRequest(
        order_id=str(uuid.uuid4()),
        instrument=sample_order_instrument,
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        expiration=sample_order_expiration_day,
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
    )


@pytest.fixture
def sample_preflight_request(sample_order_instrument, sample_order_expiration_day):
    """Sample valid preflight request."""
    return PreflightRequest(
        instrument=sample_order_instrument,
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        expiration=sample_order_expiration_day,
        quantity=Decimal("10"),
        limit_price=Decimal("150.00"),
    )


@pytest.fixture
def sample_order():
    """Sample Order model."""
    from public_api_sdk.models.order import Order
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
def mock_get_quotes():
    """Mock get_quotes function for subscription manager tests."""
    from public_api_sdk.models import Quote
    
    def _get_quotes(instruments):
        return [
            Quote(
                instrument=instr,
                last=Decimal("150.00"),
                bid=Decimal("149.95"),
                ask=Decimal("150.05"),
            )
            for instr in instruments
        ]
    return _get_quotes
