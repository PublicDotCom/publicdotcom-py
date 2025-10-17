from enum import Enum
from typing import Callable, List, Optional, Any, Union, Awaitable
from pydantic import BaseModel, Field, field_validator, ConfigDict

from .order import OrderInstrument
from .quote import Quote


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    STOPPED = "STOPPED"


class PriceChange(BaseModel):
    instrument: OrderInstrument
    old_quote: Optional[Quote]
    new_quote: Quote
    changed_fields: List[str] = Field(
        default_factory=list,
        description="List of fields that changed (e.g., 'last', 'bid', 'ask')",
    )

    def has_price_change(self) -> bool:
        return len(self.changed_fields) > 0


class SubscriptionConfig(BaseModel):
    polling_frequency_seconds: float = Field(
        default=1.0,
        description="How often to poll for price updates in seconds",
        ge=0.1,
        le=60.0,
    )
    retry_on_error: bool = Field(
        default=True, description="Whether to retry on API errors"
    )
    max_retries: int = Field(
        default=3, description="Maximum number of retries on error", ge=0, le=10
    )
    exponential_backoff: bool = Field(
        default=True, description="Use exponential backoff for retries"
    )

    @field_validator("polling_frequency_seconds")
    @classmethod
    def validate_polling_frequency(cls, v: float) -> float:
        if v < 0.1:
            raise ValueError("Polling frequency must be at least 0.1 seconds")
        if v > 60.0:
            raise ValueError("Polling frequency cannot exceed 60 seconds")
        return v


class Subscription(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    instruments: List[OrderInstrument]
    status: SubscriptionStatus = Field(default=SubscriptionStatus.ACTIVE)
    config: SubscriptionConfig = Field(default_factory=SubscriptionConfig)
    callback: Optional[Any] = Field(
        default=None, description="Callback function (not serializable)"
    )


class SubscriptionInfo(BaseModel):
    id: str
    instruments: List[OrderInstrument]
    status: str
    polling_frequency: float
    retry_on_error: bool
    max_retries: int


PriceChangeCallback = Union[
    Callable[[PriceChange], None],  # Sync callback
    Callable[[PriceChange], Awaitable[None]],  # Async callback
]
