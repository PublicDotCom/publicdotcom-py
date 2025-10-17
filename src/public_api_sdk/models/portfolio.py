from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field

from .instrument_type import InstrumentType
from .order import Order


class AccountType(str, Enum):
    BROKERAGE = "BROKERAGE"
    HIGH_YIELD = "HIGH_YIELD"
    BOND_ACCOUNT = "BOND_ACCOUNT"
    RIA_ASSET = "RIA_ASSET"
    TREASURY = "TREASURY"
    TRADITIONAL_IRA = "TRADITIONAL_IRA"
    ROTH_IRA = "ROTH_IRA"


class BuyingPower(BaseModel):
    cash_only_buying_power: Decimal = Field(
        ...,
        alias="cashOnlyBuyingPower",
        description="Buying power available for trading on cash only without taking loans.",
    )
    buying_power: Decimal = Field(
        ...,
        alias="buyingPower",
        description="Buying power available for trading marginable assets.",
    )
    options_buying_power: Decimal = Field(
        ...,
        alias="optionsBuyingPower",
        description="Buying power available for trading options.",
    )


class AssetType(str, Enum):
    CASH = "CASH"
    JIKO_ACCOUNT = "JIKO_ACCOUNT"
    STOCK = "STOCK"
    OPTIONS_LONG = "OPTIONS_LONG"
    OPTIONS_SHORT = "OPTIONS_SHORT"
    BONDS = "BONDS"
    CRYPTO = "CRYPTO"


class PortfolioEquity(BaseModel):
    type: AssetType = Field(
        ...,
        description="Type of asset.",
    )
    value: Decimal = Field(
        ...,
        description="Total value for the given asset type.",
    )
    percentage_of_portfolio: Optional[Decimal] = Field(
        None,
        alias="percentageOfPortfolio",
        description="The percentage of the portfolio this asset type constitutes.",
    )


class PortfolioInstrument(BaseModel):
    symbol: str = Field(...)
    name: str = Field(...)
    type: InstrumentType = Field(...)


class Price(BaseModel):
    last_price: Optional[Decimal] = Field(None, alias="lastPrice")
    timestamp: Optional[datetime] = Field(None)


class Gain(BaseModel):
    gain_value: Optional[Decimal] = Field(None, alias="gainValue")
    gain_percentage: Optional[Decimal] = Field(None, alias="gainPercentage")
    timestamp: Optional[datetime] = Field(None)


class CostBasis(BaseModel):
    total_cost: Optional[Decimal] = Field(
        None,
        alias="totalCost",
        description="What is the dollars paid for entering this position",
    )
    unit_cost: Optional[Decimal] = Field(
        None,
        alias="unitCost",
        description="Total cost divided by the quantity.",
    )
    gain_value: Optional[Decimal] = Field(
        None,
        alias="gainValue",
        description="Amount of dollars this position gained or lost. Current value - total cost",
    )
    gain_percentage: Optional[Decimal] = Field(
        None,
        alias="gainPercentage",
        description="100 * gainValue / totalcost",
    )
    last_update: Optional[datetime] = Field(
        None,
        alias="lastUpdate",
        description="When was the cost cases last updated.",
    )


class PortfolioPosition(BaseModel):
    instrument: PortfolioInstrument = Field(...)
    quantity: Decimal = Field(...)
    opened_at: Optional[datetime] = Field(
        None,
        alias="openedAt",
        description="When was this position opened. Null if unknown.",
    )
    current_value: Optional[Decimal] = Field(
        None,
        alias="currentValue",
        description="How much the position is worth. Calculated from quantity * lastSalePrice.",
    )
    percent_of_portfolio: Optional[Decimal] = Field(
        None,
        alias="percentOfPortfolio",
        description="The percent that this position makes of the entire portfolio.",
    )
    last_price: Optional[Price] = Field(None, alias="lastPrice")
    instrument_gain: Optional[Gain] = Field(None, alias="instrumentGain")
    position_daily_gain: Optional[Gain] = Field(None, alias="positionDailyGain")
    cost_basis: Optional[CostBasis] = Field(None, alias="costBasis")


class Portfolio(BaseModel):
    account_id: str = Field(..., alias="accountId")
    account_type: AccountType = Field(..., alias="accountType")
    buying_power: BuyingPower = Field(..., alias="buyingPower")
    equity: List[PortfolioEquity] = Field(..., description="List of equity summaries")
    positions: List[PortfolioPosition] = Field(...)
    orders: List[Order] = Field(...)
