from datetime import date
from decimal import Decimal
from enum import Enum
from typing import List, Optional

from pydantic import AliasChoices, BaseModel, Field, field_serializer


class SortDirection(str, Enum):
    """Sort direction for bond search results."""

    ASC = "ASC"
    DESC = "DESC"


class BondStatus(str, Enum):
    """Lifecycle status of a bond."""

    LIQUIDATED = "LIQUIDATED"
    CONVERTED = "CONVERTED"
    FUNGED = "FUNGED"
    REPAID = "REPAID"
    RESTRUCTURED = "RESTRUCTURED"
    CALLED = "CALLED"
    DEFAULTED = "DEFAULTED"
    MATURED = "MATURED"
    OUTSTANDING = "OUTSTANDING"
    PUT = "PUT"
    TENDERED = "TENDERED"
    REPURCHASED = "REPURCHASED"
    PRE_ISSUANCE = "PRE_ISSUANCE"
    UNKNOWN = "UNKNOWN"


class BondType(str, Enum):
    """Type of fixed income instrument."""

    AGENCY = "AGENCY"
    CD = "CD"
    CORPORATE = "CORPORATE"
    GOVERNMENT = "GOVERNMENT"
    MUNICIPAL = "MUNICIPAL"
    TREASURY = "TREASURY"


class TreasurySubtype(str, Enum):
    """Subtype of treasury instruments."""

    BOND = "BOND"
    BILL = "BILL"
    NOTE = "NOTE"
    STRIPS = "STRIPS"
    TIPS = "TIPS"
    FLOATING = "FLOATING"


class BondRating(str, Enum):
    """S&P credit rating."""

    AAA = "AAA"
    AA_PLUS = "AA+"
    AA = "AA"
    AA_MINUS = "AA-"
    SP_1_PLUS = "SP-1+"
    A_1_PLUS = "A-1+"
    A_PLUS = "A+"
    A = "A"
    A_1 = "A-1"
    A_MINUS = "A-"
    SP_1 = "SP-1"
    BBB_PLUS = "BBB+"
    A_2 = "A-2"
    BBB = "BBB"
    BBB_MINUS = "BBB-"
    A_3 = "A-3"
    BB_PLUS = "BB+"
    BB = "BB"
    BB_MINUS = "BB-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    CCC_PLUS = "CCC+"
    CCC = "CCC"
    CCC_MINUS = "CCC-"
    CC = "CC"
    C = "C"
    D = "D"
    NR = "NR"


class RatingCategory(str, Enum):
    """S&P rating category."""

    INVESTMENT_GRADE = "INVESTMENT_GRADE"
    SPECULATIVE_GRADE = "SPECULATIVE_GRADE"


class SpOutlook(str, Enum):
    """S&P rating outlook."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    DEVELOPING = "DEVELOPING"
    STABLE = "STABLE"
    NOT_RATED = "NOT_RATED"
    NOT_MEANINGFUL = "NOT_MEANINGFUL"


class SpCreditwatch(str, Enum):
    """S&P creditwatch status."""

    POSITIVE = "POSITIVE"
    NEGATIVE = "NEGATIVE"
    DEVELOPING = "DEVELOPING"
    NOT_MEANINGFUL = "NOT_MEANINGFUL"


class CouponFrequency(str, Enum):
    """Frequency of coupon payments."""

    AT_MATURITY = "AT_MATURITY"
    ZERO = "ZERO"
    MONTHLY = "MONTHLY"
    QUARTERLY = "QUARTERLY"
    SEMI_ANNUAL = "SEMI_ANNUAL"
    ANNUAL = "ANNUAL"


class BondSearchRequest(BaseModel):
    """Filters for the paged fixed income instrument search.

    All fields are optional; combine them to narrow down results.
    """

    model_config = {"populate_by_name": True}

    page_number: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("page_number", "pageNumber"),
        serialization_alias="pageNumber",
        description="Page number (zero-based). Defaults to 0.",
    )
    page_size: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("page_size", "pageSize"),
        serialization_alias="pageSize",
        description="Number of items per page. Defaults to 20.",
    )
    sort_property: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("sort_property", "sortProperty"),
        serialization_alias="sortProperty",
        description="Property to sort by.",
    )
    sort_direction: Optional[SortDirection] = Field(
        None,
        validation_alias=AliasChoices("sort_direction", "sortDirection"),
        serialization_alias="sortDirection",
        description="Sort direction. Defaults to DESC.",
    )
    issuer: Optional[str] = Field(
        None,
        description="Filter by issuer name.",
    )
    issuer_symbol: Optional[List[str]] = Field(
        None,
        validation_alias=AliasChoices("issuer_symbol", "issuerSymbol"),
        serialization_alias="issuerSymbol",
        description="Filter by issuer symbol(s).",
    )
    bond_status: Optional[List[BondStatus]] = Field(
        None,
        validation_alias=AliasChoices("bond_status", "bondStatus"),
        serialization_alias="bondStatus",
        description="Filter by bond status.",
    )
    bond_type: Optional[List[BondType]] = Field(
        None,
        validation_alias=AliasChoices("bond_type", "bondType"),
        serialization_alias="bondType",
        description="Filter by bond type(s).",
    )
    treasury_subtype: Optional[List[TreasurySubtype]] = Field(
        None,
        validation_alias=AliasChoices("treasury_subtype", "treasurySubtype"),
        serialization_alias="treasurySubtype",
        description="Filter by treasury subtype(s).",
    )
    rating: Optional[List[BondRating]] = Field(
        None,
        description="Filter by S&P credit rating(s).",
    )
    rating_category: Optional[RatingCategory] = Field(
        None,
        validation_alias=AliasChoices("rating_category", "ratingCategory"),
        serialization_alias="ratingCategory",
        description="Filter by rating category.",
    )
    sp_outlook: Optional[List[SpOutlook]] = Field(
        None,
        validation_alias=AliasChoices("sp_outlook", "spOutlook"),
        serialization_alias="spOutlook",
        description="Filter by S&P outlook.",
    )
    sp_creditwatch: Optional[List[SpCreditwatch]] = Field(
        None,
        validation_alias=AliasChoices("sp_creditwatch", "spCreditwatch"),
        serialization_alias="spCreditwatch",
        description="Filter by S&P creditwatch status.",
    )
    coupon_frequency: Optional[List[CouponFrequency]] = Field(
        None,
        validation_alias=AliasChoices("coupon_frequency", "couponFrequency"),
        serialization_alias="couponFrequency",
        description="Filter by coupon payment frequency.",
    )
    min_coupon: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("min_coupon", "minCoupon"),
        serialization_alias="minCoupon",
        description="Minimum coupon rate.",
    )
    max_coupon: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("max_coupon", "maxCoupon"),
        serialization_alias="maxCoupon",
        description="Maximum coupon rate.",
    )
    min_maturity_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("min_maturity_date", "minMaturityDate"),
        serialization_alias="minMaturityDate",
        description=(
            "Minimum maturity date (yyyy-MM-dd). Defaults to today + 14 days to"
            " exclude bonds nearing maturity with volatile yields."
        ),
    )
    max_maturity_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("max_maturity_date", "maxMaturityDate"),
        serialization_alias="maxMaturityDate",
        description="Maximum maturity date (yyyy-MM-dd).",
    )
    min_current_yield: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("min_current_yield", "minCurrentYield"),
        serialization_alias="minCurrentYield",
        description="Minimum current yield.",
    )
    max_current_yield: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("max_current_yield", "maxCurrentYield"),
        serialization_alias="maxCurrentYield",
        description="Maximum current yield.",
    )
    min_par_value: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("min_par_value", "minParValue"),
        serialization_alias="minParValue",
        description="Minimum par value.",
    )
    max_par_value: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("max_par_value", "maxParValue"),
        serialization_alias="maxParValue",
        description="Maximum par value.",
    )
    min_liquidity_rating: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("min_liquidity_rating", "minLiquidityRating"),
        serialization_alias="minLiquidityRating",
        description="Minimum liquidity rating.",
    )
    max_liquidity_rating: Optional[Decimal] = Field(
        None,
        validation_alias=AliasChoices("max_liquidity_rating", "maxLiquidityRating"),
        serialization_alias="maxLiquidityRating",
        description="Maximum liquidity rating.",
    )
    liquidity_rating: Optional[List[Decimal]] = Field(
        None,
        validation_alias=AliasChoices("liquidity_rating", "liquidityRating"),
        serialization_alias="liquidityRating",
        description="Filter by specific liquidity rating(s) — scores from 1 (low) to 5 (high).",
    )
    callable: Optional[bool] = Field(
        None,
        description="Filter by callable status.",
    )
    perpetual: Optional[bool] = Field(
        None,
        description="Filter by perpetual bond status.",
    )
    partial_par: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("partial_par", "partialPar"),
        serialization_alias="partialPar",
        description="Filter by partial par status.",
    )

    @field_serializer("min_maturity_date", "max_maturity_date")
    def serialize_date(self, value: Optional[date]) -> Optional[str]:
        return value.isoformat() if value is not None else None


class BondInstrument(BaseModel):
    """A fixed income instrument returned by the bond search."""

    model_config = {"populate_by_name": True}

    cusip: Optional[str] = Field(None)
    issuer: Optional[str] = Field(None)
    issuer_symbol: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("issuer_symbol", "issuerSymbol"),
        serialization_alias="issuerSymbol",
    )
    symbol: Optional[str] = Field(None)
    description: Optional[str] = Field(None)
    description_short: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("description_short", "descriptionShort"),
        serialization_alias="descriptionShort",
    )
    bond_type: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("bond_type", "bondType"),
        serialization_alias="bondType",
    )
    treasury_subtype: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("treasury_subtype", "treasurySubtype"),
        serialization_alias="treasurySubtype",
    )
    treasury_duration: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("treasury_duration", "treasuryDuration"),
        serialization_alias="treasuryDuration",
    )
    bond_status: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("bond_status", "bondStatus"),
        serialization_alias="bondStatus",
    )
    issue_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("issue_date", "issueDate"),
        serialization_alias="issueDate",
    )
    issue_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("issue_price", "issuePrice"),
        serialization_alias="issuePrice",
    )
    issue_size: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("issue_size", "issueSize"),
        serialization_alias="issueSize",
    )
    maturity_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("maturity_date", "maturityDate"),
        serialization_alias="maturityDate",
    )
    rating: Optional[str] = Field(None)
    rating_category: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("rating_category", "ratingCategory"),
        serialization_alias="ratingCategory",
    )
    coupon: Optional[str] = Field(None)
    coupon_frequency: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("coupon_frequency", "couponFrequency"),
        serialization_alias="couponFrequency",
    )
    next_coupon_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("next_coupon_date", "nextCouponDate"),
        serialization_alias="nextCouponDate",
    )
    par_value: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("par_value", "parValue"),
        serialization_alias="parValue",
    )
    accrued_interest: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("accrued_interest", "accruedInterest"),
        serialization_alias="accruedInterest",
    )
    callable: Optional[bool] = Field(None)
    next_call_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("next_call_date", "nextCallDate"),
        serialization_alias="nextCallDate",
    )
    next_call_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("next_call_price", "nextCallPrice"),
        serialization_alias="nextCallPrice",
    )
    current_yield: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("current_yield", "currentYield"),
        serialization_alias="currentYield",
    )
    current_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("current_price", "currentPrice"),
        serialization_alias="currentPrice",
    )
    sp_outlook: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("sp_outlook", "spOutlook"),
        serialization_alias="spOutlook",
    )
    sp_outlook_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("sp_outlook_date", "spOutlookDate"),
        serialization_alias="spOutlookDate",
    )
    sp_creditwatch: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("sp_creditwatch", "spCreditwatch"),
        serialization_alias="spCreditwatch",
    )
    sp_creditwatch_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("sp_creditwatch_date", "spCreditwatchDate"),
        serialization_alias="spCreditwatchDate",
    )
    perpetual: Optional[bool] = Field(None)
    country_issue: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("country_issue", "countryIssue"),
        serialization_alias="countryIssue",
    )
    country_domicile: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("country_domicile", "countryDomicile"),
        serialization_alias="countryDomicile",
    )
    days_until_maturity: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("days_until_maturity", "daysUntilMaturity"),
        serialization_alias="daysUntilMaturity",
    )
    liquidity_rating: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("liquidity_rating", "liquidityRating"),
        serialization_alias="liquidityRating",
    )
    seniority: Optional[str] = Field(None)
    partial_par: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("partial_par", "partialPar"),
        serialization_alias="partialPar",
    )
    minimum_order_size: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("minimum_order_size", "minimumOrderSize"),
        serialization_alias="minimumOrderSize",
    )
    minimum_order_increment: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("minimum_order_increment", "minimumOrderIncrement"),
        serialization_alias="minimumOrderIncrement",
    )


class SortInfo(BaseModel):
    """Sort state of a bond search page."""

    empty: Optional[bool] = Field(None)
    unsorted: Optional[bool] = Field(None)
    sorted: Optional[bool] = Field(None)


class PageInfo(BaseModel):
    """Pagination state of a bond search page."""

    model_config = {"populate_by_name": True}

    offset: Optional[int] = Field(None)
    paged: Optional[bool] = Field(None)
    page_size: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("page_size", "pageSize"),
        serialization_alias="pageSize",
    )
    sort: Optional[SortInfo] = Field(None)
    page_number: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("page_number", "pageNumber"),
        serialization_alias="pageNumber",
    )
    unpaged: Optional[bool] = Field(None)


class BondSearchResponsePage(BaseModel):
    """One page of fixed income instruments matching a bond search."""

    model_config = {"populate_by_name": True}

    total_elements: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("total_elements", "totalElements"),
        serialization_alias="totalElements",
    )
    total_pages: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("total_pages", "totalPages"),
        serialization_alias="totalPages",
    )
    size: Optional[int] = Field(None)
    content: List[BondInstrument] = Field(default_factory=list)
    number: Optional[int] = Field(None)
    number_of_elements: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("number_of_elements", "numberOfElements"),
        serialization_alias="numberOfElements",
    )
    sort: Optional[SortInfo] = Field(None)
    pageable: Optional[PageInfo] = Field(None)
    first: Optional[bool] = Field(None)
    last: Optional[bool] = Field(None)
    empty: Optional[bool] = Field(None)


class BondDetailsResponse(BaseModel):
    """Bond details combining instrument data and quote information."""

    model_config = {"populate_by_name": True}

    cusip: Optional[str] = Field(None, description="CUSIP identifier.")
    issuer: Optional[str] = Field(None, description="Name of the bond issuer.")
    issuer_symbol: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("issuer_symbol", "issuerSymbol"),
        serialization_alias="issuerSymbol",
        description="Symbol of the bond issuer.",
    )
    symbol: Optional[str] = Field(
        None, description="Bond symbol (typically CUSIP-BOND format)."
    )
    description: Optional[str] = Field(
        None, description="Full description of the bond."
    )
    description_short: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("description_short", "descriptionShort"),
        serialization_alias="descriptionShort",
        description="Short description of the bond.",
    )
    bond_type: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("bond_type", "bondType"),
        serialization_alias="bondType",
        description="Type of bond (e.g. TREASURY, CORPORATE, MUNICIPAL).",
    )
    treasury_subtype: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("treasury_subtype", "treasurySubtype"),
        serialization_alias="treasurySubtype",
        description="Treasury subtype (e.g. STRIPS).",
    )
    treasury_duration: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("treasury_duration", "treasuryDuration"),
        serialization_alias="treasuryDuration",
        description="Treasury duration (e.g. 30Y).",
    )
    bond_status: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("bond_status", "bondStatus"),
        serialization_alias="bondStatus",
        description="Bond status (e.g. OUTSTANDING).",
    )
    issue_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("issue_date", "issueDate"),
        serialization_alias="issueDate",
        description="Date when the bond was issued.",
    )
    issue_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("issue_price", "issuePrice"),
        serialization_alias="issuePrice",
        description="Original price at which the bond was issued.",
    )
    issue_size: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("issue_size", "issueSize"),
        serialization_alias="issueSize",
        description="Total size of the bond issue.",
    )
    maturity_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("maturity_date", "maturityDate"),
        serialization_alias="maturityDate",
        description="Date when the bond matures.",
    )
    rating: Optional[str] = Field(None, description="Credit rating of the bond.")
    rating_category: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("rating_category", "ratingCategory"),
        serialization_alias="ratingCategory",
        description="Rating category (e.g. INVESTMENT_GRADE).",
    )
    coupon: Optional[str] = Field(None, description="Coupon rate of the bond.")
    coupon_frequency: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("coupon_frequency", "couponFrequency"),
        serialization_alias="couponFrequency",
        description="Frequency of coupon payments.",
    )
    next_coupon_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("next_coupon_date", "nextCouponDate"),
        serialization_alias="nextCouponDate",
        description="Date of the next coupon payment.",
    )
    par_value: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("par_value", "parValue"),
        serialization_alias="parValue",
        description="Par value of the bond.",
    )
    accrued_interest: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("accrued_interest", "accruedInterest"),
        serialization_alias="accruedInterest",
        description="Accrued interest on the bond.",
    )
    callable: Optional[bool] = Field(
        None, description="Whether the bond is callable."
    )
    next_call_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("next_call_date", "nextCallDate"),
        serialization_alias="nextCallDate",
        description="Date of the next call option.",
    )
    next_call_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("next_call_price", "nextCallPrice"),
        serialization_alias="nextCallPrice",
        description="Price at which the bond can be called.",
    )
    current_yield: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("current_yield", "currentYield"),
        serialization_alias="currentYield",
        description="Current yield of the bond.",
    )
    current_price: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("current_price", "currentPrice"),
        serialization_alias="currentPrice",
        description="Current market price of the bond.",
    )
    sp_outlook: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("sp_outlook", "spOutlook"),
        serialization_alias="spOutlook",
        description="S&P rating outlook.",
    )
    sp_outlook_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("sp_outlook_date", "spOutlookDate"),
        serialization_alias="spOutlookDate",
        description="Date of S&P outlook.",
    )
    sp_creditwatch: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("sp_creditwatch", "spCreditwatch"),
        serialization_alias="spCreditwatch",
        description="S&P creditwatch status.",
    )
    sp_creditwatch_date: Optional[date] = Field(
        None,
        validation_alias=AliasChoices("sp_creditwatch_date", "spCreditwatchDate"),
        serialization_alias="spCreditwatchDate",
        description="Date of S&P creditwatch.",
    )
    perpetual: Optional[bool] = Field(
        None, description="Whether the bond is perpetual."
    )
    country_issue: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("country_issue", "countryIssue"),
        serialization_alias="countryIssue",
        description="Country where the bond was issued.",
    )
    country_domicile: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("country_domicile", "countryDomicile"),
        serialization_alias="countryDomicile",
        description="Country of issuer domicile.",
    )
    days_until_maturity: Optional[int] = Field(
        None,
        validation_alias=AliasChoices("days_until_maturity", "daysUntilMaturity"),
        serialization_alias="daysUntilMaturity",
        description="Number of days until the bond matures.",
    )
    liquidity_rating: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("liquidity_rating", "liquidityRating"),
        serialization_alias="liquidityRating",
        description="Liquidity rating of the bond.",
    )
    seniority: Optional[str] = Field(
        None, description="Seniority level of the bond."
    )
    partial_par: Optional[bool] = Field(
        None,
        validation_alias=AliasChoices("partial_par", "partialPar"),
        serialization_alias="partialPar",
        description="Whether partial par trading is allowed.",
    )
    minimum_order_size: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("minimum_order_size", "minimumOrderSize"),
        serialization_alias="minimumOrderSize",
        description="Minimum order size for trading.",
    )
    minimum_order_increment: Optional[str] = Field(
        None,
        validation_alias=AliasChoices("minimum_order_increment", "minimumOrderIncrement"),
        serialization_alias="minimumOrderIncrement",
        description="Minimum order increment for trading.",
    )
