"""Event-contract (prediction market) discovery models.

Covers the three ``/userapigateway/eventcontract`` endpoints: browse
categories, page through event summaries, and fetch one event's full details
(outcomes, YES/NO contracts with pricing, trading timeline, CFTC terms).

For chart bars of an event's contracts see
:class:`~public_api_sdk.models.historic_data.EventContractChartsResponse`.
"""

import logging
import re
from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import List, Optional, Union

from pydantic import AliasChoices, BaseModel, Field, field_serializer, field_validator


def _warn_unknown(enum_name: str, value: object) -> None:
    logging.getLogger(__name__).warning(
        "Unrecognised %s %r — defaulting to UNKNOWN. "
        "Update the SDK to get the correct value.",
        enum_name,
        value,
    )


class EventSortingMode(str, Enum):
    """Sort order for :meth:`PublicApiClient.get_event_summary`."""

    VOLUME = "VOLUME"
    EXPIRATION = "EXPIRATION"
    RECENTLY_ADDED = "RECENTLY_ADDED"


class EventFrequency(str, Enum):
    """How often an event recurs.

    Used as a filter in :class:`EventSummaryFilters` and reported per category
    in :class:`EventCategoryFrequencies`.
    """

    ALL = "ALL"
    ONCE = "ONCE"
    FIFTEEN_MINUTES = "FIFTEEN_MINUTES"
    ONE_HOUR = "ONE_HOUR"
    ONE_DAY = "ONE_DAY"
    ONE_WEEK = "ONE_WEEK"
    ONE_MONTH = "ONE_MONTH"
    ONE_YEAR = "ONE_YEAR"
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API values

    @classmethod
    def _missing_(cls, value: object) -> "EventFrequency":
        _warn_unknown(cls.__name__, value)
        return cls.UNKNOWN


class EventExchange(str, Enum):
    """The exchange that lists an event."""

    EXCHANGE_UNSPECIFIED = "EXCHANGE_UNSPECIFIED"
    EMULATOR = "EMULATOR"
    KALSHI = "KALSHI"
    PMUS = "PMUS"
    CDNA = "CDNA"
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API values

    @classmethod
    def _missing_(cls, value: object) -> "EventExchange":
        _warn_unknown(cls.__name__, value)
        return cls.UNKNOWN


class EventOutcomeState(str, Enum):
    """State of an outcome and the event contracts within it."""

    STATE_UNSPECIFIED = "STATE_UNSPECIFIED"
    STATE_NEW = "STATE_NEW"
    STATE_OPEN = "STATE_OPEN"
    STATE_HALTED = "STATE_HALTED"
    STATE_CLOSED = "STATE_CLOSED"
    STATE_SETTLED = "STATE_SETTLED"
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API values

    @classmethod
    def _missing_(cls, value: object) -> "EventOutcomeState":
        _warn_unknown(cls.__name__, value)
        return cls.UNKNOWN


class EventSettledOutcome(str, Enum):
    """How an outcome settled."""

    SETTLED_OUTCOME_UNSPECIFIED = "SETTLED_OUTCOME_UNSPECIFIED"
    SETTLED_OUTCOME_YES = "SETTLED_OUTCOME_YES"
    SETTLED_OUTCOME_NO = "SETTLED_OUTCOME_NO"
    SETTLED_OUTCOME_OTHER = "SETTLED_OUTCOME_OTHER"
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API values

    @classmethod
    def _missing_(cls, value: object) -> "EventSettledOutcome":
        _warn_unknown(cls.__name__, value)
        return cls.UNKNOWN


class EventTradingMode(str, Enum):
    """Which trades an outcome currently accepts."""

    BUY_AND_SELL = "BUY_AND_SELL"
    LIQUIDATION_ONLY = "LIQUIDATION_ONLY"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API values

    @classmethod
    def _missing_(cls, value: object) -> "EventTradingMode":
        _warn_unknown(cls.__name__, value)
        return cls.UNKNOWN


class EventContractSide(str, Enum):
    """The outcome an event contract predicts."""

    YES = "YES"
    NO = "NO"
    UNKNOWN = "UNKNOWN"  # fallback for unrecognised API values

    @classmethod
    def _missing_(cls, value: object) -> "EventContractSide":
        _warn_unknown(cls.__name__, value)
        return cls.UNKNOWN


# Exchange prefix, ".", series ticker, "-", then a non-empty event suffix.
_EVENT_SYMBOL_PATTERN = re.compile(r"[^.\s-]+\.([^.\s-]+)-\S+")


def _series_of(event_symbol: str) -> Optional[str]:
    """Return the series ticker of an event symbol, or ``None``.

    ``"KALSHI.KXBTC15M-26OCT161345"`` → ``"KXBTC15M"``. The same series comes
    back for the event's ``-EVENT`` grouping id and its contract symbols
    (``.Y``/``.N`` and ``-EVENTCONTRACT``), since they all extend the event
    symbol. A symbol without an exchange prefix, without a ``-`` suffix, or
    that is empty gives ``None``: every event symbol the API returns has both,
    so anything else is not an event symbol and the series would be a guess.
    Outcome ids (e.g. ``"KXBTC15M-26OCT161345-45"``) carry no exchange prefix
    and also give ``None``.
    """
    match = _EVENT_SYMBOL_PATTERN.fullmatch(event_symbol)
    return match.group(1) if match else None


# --- Categories -------------------------------------------------------------


class EventCategoryFrequencies(BaseModel):
    """The frequency filters a category supports."""

    model_config = {"populate_by_name": True}

    show: Optional[bool] = Field(
        None, description="Whether to offer the frequency filter for this category."
    )
    frequencies: List[EventFrequency] = Field(default_factory=list)


class EventCategory(BaseModel):
    """An event category with its subcategories and supported frequencies."""

    model_config = {"populate_by_name": True}

    category: str = Field(..., description="Pass as `category` to `get_event_summary`.")
    subcategories: List[str] = Field(default_factory=list)
    event_frequency: Optional[EventCategoryFrequencies] = Field(
        None,
        validation_alias=AliasChoices("event_frequency", "eventFrequency"),
        serialization_alias="eventFrequency",
    )


class EventCategoriesResponse(BaseModel):
    """Response of :meth:`PublicApiClient.get_event_categories`."""

    model_config = {"populate_by_name": True}

    categories: List[EventCategory] = Field(default_factory=list)


# --- Summary ----------------------------------------------------------------


class EventSummaryFilters(BaseModel):
    """Optional filter block of :class:`EventSummaryRequest`.

    The API requires both ``event_symbols`` and ``frequencies`` when the block
    is sent. ``event_symbols`` defaults to an empty list, which matches every
    event, so ``EventSummaryFilters(frequencies=[...])`` filters by frequency
    alone.
    """

    model_config = {"populate_by_name": True}

    event_symbols: List[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("event_symbols", "eventSymbols"),
        serialization_alias="eventSymbols",
        description="Only return these events (eventSymbol values); empty = all.",
    )
    frequencies: List[EventFrequency] = Field(
        ..., description="Only return events recurring at these frequencies."
    )
    resolution_time_start: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("resolution_time_start", "resolutionTimeStart"),
        serialization_alias="resolutionTimeStart",
        description="Only return events resolving at or after this time.",
    )
    resolution_time_end: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("resolution_time_end", "resolutionTimeEnd"),
        serialization_alias="resolutionTimeEnd",
        description="Only return events resolving at or before this time.",
    )

    @field_validator("frequencies")
    @classmethod
    def validate_frequencies(cls, v: List[EventFrequency]) -> List[EventFrequency]:
        if EventFrequency.UNKNOWN in v:
            raise ValueError(
                "frequency UNKNOWN is a client-side fallback, not a filter"
            )
        return v

    @field_serializer("frequencies")
    def serialize_frequencies(self, value: List[EventFrequency]) -> List[str]:
        return [frequency.value for frequency in value]

    @field_serializer("resolution_time_start", "resolution_time_end")
    def serialize_timestamp(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat(timespec="seconds") if value else None


class EventSummaryRequest(BaseModel):
    """Request body for :meth:`PublicApiClient.get_event_summary`.

    Only ``sorting_mode`` is required by the API; it defaults to ``VOLUME``.
    To fetch the next page, send the same request with ``next_token`` set to
    the previous page's ``next_token``.
    """

    model_config = {"populate_by_name": True}

    sorting_mode: EventSortingMode = Field(
        EventSortingMode.VOLUME,
        validation_alias=AliasChoices("sorting_mode", "sortingMode"),
        serialization_alias="sortingMode",
        description="Sort order of the returned events.",
    )
    category: Optional[str] = Field(
        None, description="Only return events in this category."
    )
    subcategory: Optional[str] = Field(
        None, description="Only return events in this subcategory."
    )
    next_token: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("next_token", "nextToken"),
        serialization_alias="nextToken",
        description="Pagination token from the previous page.",
    )
    display_resolved_events: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices(
            "display_resolved_events", "displayResolvedEvents"
        ),
        serialization_alias="displayResolvedEvents",
        description="Whether to include resolved events.",
    )
    created_within_days: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("created_within_days", "createdWithinDays"),
        serialization_alias="createdWithinDays",
        description="Only return events created within the last N days.",
    )
    filters: Optional[EventSummaryFilters] = Field(
        None, description="Filter by event symbol, frequency or resolution time."
    )

    @field_serializer("sorting_mode")
    def serialize_sorting_mode(self, value: EventSortingMode) -> str:
        return value.value


class EventSummary(BaseModel):
    """A single event in an event summary page (no outcomes).

    ``series`` is the series ticker derived from ``event_symbol`` (see
    :attr:`series`); it is not an API field and is not serialized.
    """

    model_config = {"populate_by_name": True}

    event_symbol: str = Field(
        ...,
        validation_alias=AliasChoices("event_symbol", "eventSymbol"),
        serialization_alias="eventSymbol",
        description="Pass to `get_event_details`.",
    )
    title: Optional[str] = Field(None)
    volume: Optional[Decimal] = Field(
        None, description="Combined volume of all contracts in the event."
    )
    resolution_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("resolution_time", "resolutionTime"),
        serialization_alias="resolutionTime",
    )
    resolved: Optional[bool] = Field(None)
    halted: Optional[bool] = Field(None)
    category: Optional[str] = Field(None)
    subcategories: List[str] = Field(default_factory=list)
    symbols: List[str] = Field(
        default_factory=list,
        description=(
            "Related instrument symbols, e.g. BTC-CRYPTO, IBIT; often empty. "
            "Not the event's contracts: those come from `get_event_details`."
        ),
    )

    @property
    def series(self) -> Optional[str]:
        """Series ticker of the event, e.g. ``"KXBTC15M"``.

        Derived from ``event_symbol``; groups the events of a recurring
        market such as a 15-minute window. ``None`` if ``event_symbol`` is
        not of the form ``EXCHANGE.SERIES-SUFFIX``.
        """
        return _series_of(self.event_symbol)


class EventSummaryPage(BaseModel):
    """Response of :meth:`PublicApiClient.get_event_summary`.

    Up to 100 events per page. ``next_token`` is ``None`` on the last page.
    """

    model_config = {"populate_by_name": True}

    content: List[EventSummary] = Field(default_factory=list)
    next_token: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("next_token", "nextToken"),
        serialization_alias="nextToken",
    )


# --- Details ----------------------------------------------------------------


class ResolutionSource(BaseModel):
    """A source used to resolve an event."""

    model_config = {"populate_by_name": True}

    name: Optional[str] = Field(None)
    url: Optional[str] = Field(None)


class CftcContract(BaseModel):
    """CFTC contract terms of an event."""

    model_config = {"populate_by_name": True}

    contract_terms_url: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("contract_terms_url", "contractTermsUrl"),
        serialization_alias="contractTermsUrl",
    )
    prohibitions: List[str] = Field(
        default_factory=list, description="Who is not allowed to trade the event."
    )
    resolution_sources: List[ResolutionSource] = Field(
        default_factory=list,
        validation_alias=AliasChoices("resolution_sources", "resolutionSources"),
        serialization_alias="resolutionSources",
    )


class EventTimeline(BaseModel):
    """Trading timeline of an outcome."""

    model_config = {"populate_by_name": True}

    open_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("open_time", "openTime"),
        serialization_alias="openTime",
    )
    close_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("close_time", "closeTime"),
        serialization_alias="closeTime",
    )
    expected_expiration_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices(
            "expected_expiration_time", "expectedExpirationTime"
        ),
        serialization_alias="expectedExpirationTime",
    )
    latest_expiration_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("latest_expiration_time", "latestExpirationTime"),
        serialization_alias="latestExpirationTime",
    )
    settlement_time: Optional[datetime] = Field(
        None,
        validation_alias=AliasChoices("settlement_time", "settlementTime"),
        serialization_alias="settlementTime",
    )
    settlement_delay_seconds: Optional[int] = Field(
        None,
        validation_alias=AliasChoices(
            "settlement_delay_seconds", "settlementDelaySeconds"
        ),
        serialization_alias="settlementDelaySeconds",
        description="Seconds to wait after settlement before payout.",
    )


class EventContract(BaseModel):
    """A YES or NO contract of an outcome, with current pricing.

    Prices are in dollars (0.00 to 1.00). ``probability`` is the YES
    contract's last price (1 minus it for a NO contract).
    """

    model_config = {"populate_by_name": True}

    symbol: str = Field(..., description='e.g. "KALSHI.KXBALANCESHEET-EO26-6.6.Y".')
    predicted_outcome: Optional[EventContractSide] = Field(
        None,
        validation_alias=AliasChoices("predicted_outcome", "predictedOutcome"),
        serialization_alias="predictedOutcome",
    )
    bid: Optional[Decimal] = Field(None)
    ask: Optional[Decimal] = Field(None)
    last: Optional[Decimal] = Field(None)
    open_interest: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("open_interest", "openInterest"),
        serialization_alias="openInterest",
    )
    daily_gain_value: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("daily_gain_value", "dailyGainValue"),
        serialization_alias="dailyGainValue",
    )
    daily_gain_percentage: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("daily_gain_percentage", "dailyGainPercentage"),
        serialization_alias="dailyGainPercentage",
    )
    probability: Optional[Decimal] = Field(None)


class EventOutcome(BaseModel):
    """One outcome of an event, holding its YES and NO contracts.

    ``yes``, ``no``, ``close_time``, ``seconds_left``, ``is_tradable`` and
    ``winner`` are read-only shortcuts derived from the fields below; they are
    not API fields and are not serialized.
    """

    model_config = {"populate_by_name": True}

    outcome_id: str = Field(
        ...,
        validation_alias=AliasChoices("outcome_id", "outcomeId"),
        serialization_alias="outcomeId",
        description='e.g. "KXBALANCESHEET-EO26-6.6" (no exchange prefix).',
    )
    title: Optional[str] = Field(None, description='e.g. "ABOVE $6.6 TRILLION".')
    rules: Optional[str] = Field(
        None, description="Conditions for the outcome to resolve to YES."
    )
    volume: Optional[Decimal] = Field(None)
    state: Optional[EventOutcomeState] = Field(None)
    timeline: Optional[EventTimeline] = Field(None)
    settled_outcome: Optional[EventSettledOutcome] = Field(
        None,
        validation_alias=AliasChoices("settled_outcome", "settledOutcome"),
        serialization_alias="settledOutcome",
    )
    trading: Optional[EventTradingMode] = Field(None)
    contracts: List[EventContract] = Field(default_factory=list)
    floor_strike: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("floor_strike", "floorStrike"),
        serialization_alias="floorStrike",
        description="The outcome's floor strike, when it has one.",
    )

    def _contract(self, side: EventContractSide) -> Optional[EventContract]:
        return next((c for c in self.contracts if c.predicted_outcome == side), None)

    @property
    def yes(self) -> Optional[EventContract]:
        """The YES contract, or ``None`` if the outcome has none."""
        return self._contract(EventContractSide.YES)

    @property
    def no(self) -> Optional[EventContract]:
        """The NO contract, or ``None`` if the outcome has none."""
        return self._contract(EventContractSide.NO)

    @property
    def close_time(self) -> Optional[datetime]:
        """When trading closes (``timeline.close_time``)."""
        return self.timeline.close_time if self.timeline else None

    @property
    def seconds_left(self) -> Optional[float]:
        """Seconds until ``close_time`` (0 once it has passed), or ``None``.

        Computed from the current time on each access.
        """
        close_time = self.close_time
        if close_time is None:
            return None
        if close_time.tzinfo is None:
            close_time = close_time.replace(tzinfo=timezone.utc)
        return max(0.0, (close_time - datetime.now(timezone.utc)).total_seconds())

    @property
    def is_tradable(self) -> bool:
        """Whether the outcome accepts buys and sells right now.

        Requires ``state`` ``STATE_OPEN``, ``trading`` ``BUY_AND_SELL`` and
        ``close_time`` (when known) still in the future. ``state`` alone is not
        enough: an outcome can still report ``STATE_OPEN`` after it closes.
        """
        seconds_left = self.seconds_left
        return (
            self.state == EventOutcomeState.STATE_OPEN
            and self.trading == EventTradingMode.BUY_AND_SELL
            and (seconds_left is None or seconds_left > 0)
        )

    @property
    def winner(self) -> Optional[EventContract]:
        """The contract that paid out once the outcome settled YES or NO.

        ``None`` before settlement and for any other settlement
        (``SETTLED_OUTCOME_OTHER``, ``UNKNOWN``).
        """
        if self.settled_outcome == EventSettledOutcome.SETTLED_OUTCOME_YES:
            return self.yes
        if self.settled_outcome == EventSettledOutcome.SETTLED_OUTCOME_NO:
            return self.no
        return None

    def won(self, contract: Union[EventContract, str]) -> Optional[bool]:
        """Whether ``contract`` (or a contract symbol) paid out.

        ``None`` while :attr:`winner` is unknown (not settled yet, or settled
        some other way than YES/NO).
        """
        winner = self.winner
        if winner is None:
            return None
        symbol = contract if isinstance(contract, str) else contract.symbol
        return symbol.strip() == winner.symbol


class EventDetails(BaseModel):
    """Response of :meth:`PublicApiClient.get_event_details`.

    ``series`` (the series ticker derived from ``event_symbol``) and
    ``outcome`` (the only outcome of a single-outcome event) are read-only
    shortcuts; they are not API fields and are not serialized.
    """

    model_config = {"populate_by_name": True}

    event_symbol: str = Field(
        ...,
        validation_alias=AliasChoices("event_symbol", "eventSymbol"),
        serialization_alias="eventSymbol",
        description='e.g. "KALSHI.KXBALANCESHEET-EO26".',
    )
    exchange: Optional[EventExchange] = Field(None)
    resolved: Optional[bool] = Field(None)
    halted: Optional[bool] = Field(
        None, description="Whether trading is halted for every outcome."
    )
    title: Optional[str] = Field(None)
    category: Optional[str] = Field(None)
    volume: Optional[Decimal] = Field(None)
    subcategories: List[str] = Field(default_factory=list)
    cftc_contract: Optional[CftcContract] = Field(
        None,
        validation_alias=AliasChoices("cftc_contract", "cftcContract"),
        serialization_alias="cftcContract",
    )
    outcome_count: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("outcome_count", "outcomeCount"),
        serialization_alias="outcomeCount",
        description="Unfiltered number of outcomes, even when `outcomes` is cut short.",
    )
    outcomes: List[EventOutcome] = Field(default_factory=list)

    @property
    def series(self) -> Optional[str]:
        """Series ticker of the event, e.g. ``"KXBALANCESHEET"``.

        Derived from ``event_symbol``. ``None`` if ``event_symbol`` is not of
        the form ``EXCHANGE.SERIES-SUFFIX``.
        """
        return _series_of(self.event_symbol)

    @property
    def outcome(self) -> Optional[EventOutcome]:
        """The only outcome of a single-outcome event, e.g. a 15-minute
        "Up or Down" window. ``None`` when ``outcomes`` does not hold exactly
        one outcome; use ``outcomes`` for multi-outcome events.
        """
        return self.outcomes[0] if len(self.outcomes) == 1 else None
