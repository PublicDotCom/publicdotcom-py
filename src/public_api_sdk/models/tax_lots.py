"""Response models for the unrealized tax-lot endpoints.

These models map to the spec's `com.hellopublic.hstier2.service.taxlots.api.*`
schemas (plus `com.hellopublic.core.dto.Base64File`) and back the three
`/taxlots/...` GET endpoints on the client.

Monetary and quantity fields are exposed as `Decimal` (matching the SDK's
convention for numeric string fields elsewhere, e.g. `Quote`/`Portfolio`).
`date`-format fields (`asOf`, `openDate`, `expirationDate`) are kept as plain
`str` (YYYY-MM-DD) to avoid the implicit-midnight-UTC conversion a `datetime`
field would introduce — the same approach used by `OptionDetails` in order.py.
"""

from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from .order import OptionType


class Base64File(BaseModel):
    """A base64-encoded file export (used by the tax-lots CSV endpoint)."""

    file_name: Optional[str] = Field(None, alias="fileName")
    base64_data: Optional[str] = Field(
        None,
        alias="base64Data",
        description="The file contents, base64-encoded.",
    )


class OrderReference(BaseModel):
    """Reference to an order."""

    id: str = Field(
        ...,
        description="Order id, which can be used to link to the order.",
    )
    description: str = Field(
        ...,
        description="Textual description of the order.",
    )


class OutOfDateStatusDescription(BaseModel):
    """Human-readable description of a tax-lot out-of-date status."""

    header: str = Field(
        ...,
        description="Header that describes the tax lot status.",
    )
    body: str = Field(
        ...,
        description="Message that describes the tax lot status in more detail.",
    )


class OutOfDateStatusType(str, Enum):
    """Describes how a tax lot is not up to date."""

    PRE_EXISTING_OPEN_ORDER_ON_SYMBOL = "PRE_EXISTING_OPEN_ORDER_ON_SYMBOL"
    CORPORATE_ACTION_UNDERWAY = "CORPORATE_ACTION_UNDERWAY"
    ORDER_OR_TRADE_ON_SYMBOL_TODAY = "ORDER_OR_TRADE_ON_SYMBOL_TODAY"
    LOT_ASSIGNED = "LOT_ASSIGNED"
    NOT_REPORTED_YET = "NOT_REPORTED_YET"


class OutOfDateStatus(BaseModel):
    """Describes how an unrealized lot is out of date."""

    type: OutOfDateStatusType = Field(
        ...,
        description="The tax lot status type describes how the tax lot is not up-to-date.",
    )
    order: Optional[OrderReference] = Field(None)
    description: Optional[OutOfDateStatusDescription] = Field(None)


class InstrumentSpecificTaxLotDetails(BaseModel):
    """Base for instrument-specific tax-lot details, keyed by `payloadType`."""

    payload_type: str = Field(..., alias="payloadType")


class OptionSpecificTaxLotDetails(InstrumentSpecificTaxLotDetails):
    """Option-specific tax-lot details (e.g. strike price, expiration)."""

    root_symbol: str = Field(..., alias="rootSymbol")
    strike_price: Decimal = Field(..., alias="strikePrice")
    expiration_date: str = Field(..., alias="expirationDate")
    option_type: OptionType = Field(..., alias="optionType")


class UnrealizedLot(BaseModel):
    """A single unrealized tax lot, sorted by open date."""

    quantity: Decimal = Field(..., description="The total quantity owned.")
    cost_basis: Decimal = Field(
        ..., alias="costBasis", description="The cost basis for the lot."
    )
    unit_cost: Decimal = Field(..., alias="unitCost")
    current_price: Decimal = Field(
        ...,
        alias="currentPrice",
        description=(
            "The current price. This is calculated once (by Apex) and does not"
            " change intraday, unless an explicit price was supplied."
        ),
    )
    current_value: Decimal = Field(..., alias="currentValue")
    gain_loss: Decimal = Field(
        ...,
        alias="gainLoss",
        description="The accumulated gain/loss for the lot, does not change intraday.",
    )
    open_date: str = Field(
        ..., alias="openDate", description="The date the lot was opened (YYYY-MM-DD)."
    )
    term: str = Field(
        ...,
        description="LONG, SHORT or SIXTY_FORTY. Will be null if used for a summary.",
    )
    short_term_gain_loss: Decimal = Field(
        ...,
        alias="shortTermGainLoss",
        description="The short term gain/loss including 40% of sixty-forty lots.",
    )
    long_term_gain_loss: Decimal = Field(
        ...,
        alias="longTermGainLoss",
        description="The long term gain/loss including 60% of sixty-forty lots.",
    )
    wash_sale: Optional[bool] = Field(
        None, alias="washSale", description="If this lot is marked as a wash-sale."
    )
    open_buy_price: Optional[Decimal] = Field(
        None,
        alias="openBuyPrice",
        description="The price the position was opened with.",
    )
    lot_selection_id: Optional[str] = Field(
        None,
        alias="lotSelectionId",
        description=(
            "Identifies the tax lot for selection for tax lot selling; null if it"
            " cannot be selected."
        ),
    )
    out_of_date_status: Optional[OutOfDateStatus] = Field(None, alias="outOfDateStatus")


class UnrealizedLotSummary(BaseModel):
    """Summary of the unrealized tax lots for a single symbol."""

    account_number: str = Field(..., alias="accountNumber")
    symbol: str = Field(..., description="The ticker.")
    cusip: str = Field(...)
    company_name: str = Field(..., alias="companyName")
    quantity: Decimal = Field(..., description="The total quantity owned.")
    cost_basis: Decimal = Field(..., alias="costBasis")
    unit_cost: Decimal = Field(..., alias="unitCost")
    current_price: Decimal = Field(..., alias="currentPrice")
    current_value: Decimal = Field(..., alias="currentValue")
    gain_loss: Decimal = Field(..., alias="gainLoss")
    short_term_gain_loss: Decimal = Field(..., alias="shortTermGainLoss")
    long_term_gain_loss: Decimal = Field(..., alias="longTermGainLoss")
    details: Optional[OptionSpecificTaxLotDetails] = Field(
        None,
        description="Instrument-specific details, e.g. strike price for options.",
    )
    lot_selection_id: Optional[str] = Field(
        None,
        alias="lotSelectionId",
        description=(
            "Identifies the tax lot for selection for tax lot selling; null if it"
            " cannot be selected."
        ),
    )
    out_of_date_status: Optional[OutOfDateStatus] = Field(None, alias="outOfDateStatus")


class UnrealizedLotsSummaryResponse(BaseModel):
    """An overview of the unrealized tax lots for an account."""

    as_of: str = Field(
        ...,
        alias="asOf",
        description="The trading session after which this summary was calculated.",
    )
    lots: List[UnrealizedLotSummary] = Field(
        ..., description="The lots sorted by openDate."
    )
    short_term: Decimal = Field(
        ..., alias="shortTerm", description="The short term profit or loss."
    )
    long_term: Decimal = Field(
        ..., alias="longTerm", description="The long term profit or loss."
    )
    sixty_forty_term: Decimal = Field(
        ..., alias="sixtyFortyTerm", description="The 60/40 profit/loss."
    )
    total_profit_loss: Decimal = Field(
        ..., alias="totalProfitLoss", description="The total profit or loss."
    )


class UnrealizedLotsDetailResponse(BaseModel):
    """Unrealized lots and information about a single instrument."""

    as_of: str = Field(
        ...,
        alias="asOf",
        description="The trading session after which this summary was calculated.",
    )
    symbol: str = Field(..., description="The ticker.")
    company_name: str = Field(..., alias="companyName")
    lots: Optional[List[UnrealizedLot]] = Field(
        None, description="The lots sorted by openDate."
    )
    details: Optional[OptionSpecificTaxLotDetails] = Field(None)
