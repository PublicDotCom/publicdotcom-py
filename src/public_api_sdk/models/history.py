from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field, field_serializer


class HistoryRequest(BaseModel):
    model_config = {"populate_by_name": True}
    start: Optional[datetime] = Field(
        None,
        description="Start timestamp in ISO 8601 format with timezone. Example: 2025-01-15T09:00:00-05:00 (9 AM EST, New York time).",
    )
    end: Optional[datetime] = Field(
        None,
        description="End timestamp in ISO 8601 format with timezone. Example: 2025-04-10T09:00:00-04:00 (9 AM EDT, New York time).",
    )
    page_size: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("page_size", "pageSize"),
        serialization_alias="pageSize",
        description="Maximum number of records to return.",
    )
    next_token: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("next_token", "nextToken"),
        serialization_alias="nextToken",
        description="Pagination token for fetching the next result set.",
    )

    @field_serializer("start", "end")
    def serialize_timestamp(self, value: Optional[datetime]) -> Optional[str]:
        return value.isoformat(timespec="seconds") if value else None


class TransactionType(str, Enum):
    TRADE = "TRADE"
    MONEY_MOVEMENT = "MONEY_MOVEMENT"
    POSITION_ADJUSTMENT = "POSITION_ADJUSTMENT"


class TransactionSubType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    DEPOSIT_RETURNED = "DEPOSIT_RETURNED"
    WITHDRAWAL_RETURNED = "WITHDRAWAL_RETURNED"
    DIVIDEND = "DIVIDEND"
    FEE = "FEE"
    REWARD = "REWARD"
    TREASURY_BILL_TRANSFER = "TREASURY_BILL_TRANSFER"
    INTEREST = "INTEREST"
    TRADE = "TRADE"
    TRANSFER = "TRANSFER"
    MISC = "MISC"


class TransactionSecurityType(str, Enum):
    EQUITY = "EQUITY"
    OPTION = "OPTION"
    CRYPTO = "CRYPTO"
    ALT = "ALT"
    TREASURY = "TREASURY"
    BOND = "BOND"


class TransactionSide(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class TransactionDirection(str, Enum):
    INCOMING = "INCOMING"
    OUTGOING = "OUTGOING"


class HistoryTransaction(BaseModel):
    id: str = Field(
        ...,
        description="The id of the transaction",
    )
    timestamp: datetime = Field(
        ...,
        description="The timestamp when the transaction happened",
    )
    type: TransactionType = Field(
        ...,
        description="The type of the transaction",
    )
    sub_type: Optional[TransactionSubType] = Field(
        None,
        alias="subType",
        description="The subtype of the transaction",
    )
    account_number: Optional[str] = Field(
        None,
        alias="accountNumber",
        description="The account the transaction happened on",
    )
    symbol: Optional[str] = Field(
        None,
        description="The symbol of the transaction",
    )
    security_type: Optional[TransactionSecurityType] = Field(
        None,
        alias="securityType",
        description="The security type of the transaction",
    )
    side: Optional[TransactionSide] = Field(
        None,
        alias="side",
        description="The side of the transaction - relevant for trades",
    )
    description: Optional[str] = Field(
        None,
        description="The description of the transaction",
    )
    net_amount: Optional[Decimal] = Field(
        None,
        alias="netAmount",
        description="The net amount of the transaction",
    )
    principal_amount: Optional[Decimal] = Field(
        None,
        alias="principalAmount",
        description="The principal amount of the transaction",
    )
    quantity: Optional[Decimal] = Field(
        None,
        description="The quantity of the transaction",
    )
    direction: Optional[TransactionDirection] = Field(
        None,
        description="The direction of the transaction",
    )
    fees: Optional[Decimal] = Field(
        None,
        description="The fees of the transaction",
    )


class HistoryResponsePage(BaseModel):
    transactions: List[HistoryTransaction] = Field(
        ...,
        description="List of transactions",
    )
    next_token: Optional[str] = Field(
        None,
        alias="nextToken",
        description="Token to retrieve the next page of results",
    )
    start: Optional[datetime] = Field(
        None,
        description="Start timestamp of the history query",
    )
    end: Optional[datetime] = Field(
        None,
        description="End timestamp of the history query",
    )
    page_size: Optional[int] = Field(
        None,
        alias="pageSize",
        description="Number of items to return",
    )
