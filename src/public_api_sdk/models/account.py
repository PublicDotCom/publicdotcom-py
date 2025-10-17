from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field


class AccountType(str, Enum):
    BROKERAGE = "BROKERAGE"
    HIGH_YIELD = "HIGH_YIELD"
    BOND_ACCOUNT = "BOND_ACCOUNT"
    RIA_ASSET = "RIA_ASSET"
    TREASURY = "TREASURY"
    TRADITIONAL_IRA = "TRADITIONAL_IRA"
    ROTH_IRA = "ROTH_IRA"


class OptionsLevel(str, Enum):
    NONE = "NONE"
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"
    LEVEL_4 = "LEVEL_4"


class BrokerageAccountType(str, Enum):
    CASH = "CASH"
    MARGIN = "MARGIN"


class TradePermissions(str, Enum):
    BUY_AND_SELL = "BUY_AND_SELL"
    RESTRICTED_SETTLED_FUNDS_ONLY = "RESTRICTED_SETTLED_FUNDS_ONLY"
    RESTRICTED_CLOSE_ONLY = "RESTRICTED_CLOSE_ONLY"
    RESTRICTED_NO_TRADING = "RESTRICTED_NO_TRADING"


class Account(BaseModel):
    account_id: str = Field(..., alias="accountId")
    account_type: AccountType = Field(..., alias="accountType")
    options_level: Optional[OptionsLevel] = Field(default=None, alias="optionsLevel")
    brokerage_account_type: Optional[BrokerageAccountType] = Field(
        default=None, alias="brokerageAccountType"
    )
    trade_permissions: Optional[TradePermissions] = Field(
        default=None, alias="tradePermissions"
    )


class AccountsResponse(BaseModel):
    accounts: List[Account] = Field(..., alias="accounts")
