"""Tests for the bond search / bond details endpoints and their models.

Client tests patch ApiClient/AsyncApiClient and the auth managers at
construction time so no real HTTP calls are made, mirroring the other client
test modules.
"""

from datetime import date
from decimal import Decimal
from typing import Optional
from unittest.mock import AsyncMock, Mock, patch

import pytest

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    PublicApiClient,
    PublicApiClientConfiguration,
)
from public_api_sdk.models.bond import (
    BondDetailsResponse,
    BondRating,
    BondSearchRequest,
    BondSearchResponsePage,
    BondStatus,
    BondType,
    CouponFrequency,
    RatingCategory,
    SortDirection,
    TreasurySubtype,
)

_ACCOUNT = "ACC123"


def _make_client(default_account: Optional[str] = _ACCOUNT) -> PublicApiClient:
    """Return a PublicApiClient with ApiClient and AuthManager patched out."""
    with patch("public_api_sdk.public_api_client.ApiClient"), patch(
        "public_api_sdk.public_api_client.AuthManager"
    ):
        config = PublicApiClientConfiguration(default_account_number=default_account)
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )
    return client


def _make_async_client(
    default_account: Optional[str] = _ACCOUNT,
) -> AsyncPublicApiClient:
    """Return AsyncPublicApiClient with AsyncApiClient and AsyncAuthManager patched."""
    with patch("public_api_sdk.async_public_api_client.AsyncApiClient"), patch(
        "public_api_sdk.async_public_api_client.AsyncAuthManager"
    ):
        config = AsyncPublicApiClientConfiguration(
            default_account_number=default_account
        )
        client = AsyncPublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )
    client.auth_manager.refresh_token_if_needed = AsyncMock()
    return client


def _bond_payload(symbol: str = "912810TM0-BOND") -> dict:
    return {
        "cusip": "912810TM0",
        "issuer": "United States Treasury",
        "issuerSymbol": "UST",
        "symbol": symbol,
        "description": "US Treasury Bond 3.375% due 2048",
        "descriptionShort": "T 3.375 08/15/48",
        "bondType": "TREASURY",
        "treasurySubtype": "BOND",
        "treasuryDuration": "30Y",
        "bondStatus": "OUTSTANDING",
        "issueDate": "2018-08-15",
        "issuePrice": "99.32",
        "maturityDate": "2048-08-15",
        "rating": "AA+",
        "ratingCategory": "INVESTMENT_GRADE",
        "coupon": "3.375",
        "couponFrequency": "SEMI_ANNUAL",
        "nextCouponDate": "2027-02-15",
        "parValue": "1000",
        "accruedInterest": "12.34",
        "callable": False,
        "currentYield": "4.21",
        "currentPrice": "80.15",
        "spOutlook": "STABLE",
        "perpetual": False,
        "countryIssue": "US",
        "daysUntilMaturity": 8045,
        "liquidityRating": "5",
        "seniority": "SENIOR",
        "partialPar": True,
        "minimumOrderSize": "1000",
        "minimumOrderIncrement": "1000",
    }


def _bond_page_payload() -> dict:
    return {
        "totalElements": 1,
        "totalPages": 1,
        "size": 20,
        "content": [_bond_payload()],
        "number": 0,
        "numberOfElements": 1,
        "sort": {"empty": False, "unsorted": False, "sorted": True},
        "pageable": {
            "offset": 0,
            "paged": True,
            "pageSize": 20,
            "pageNumber": 0,
            "unpaged": False,
            "sort": {"empty": False, "unsorted": False, "sorted": True},
        },
        "first": True,
        "last": True,
        "empty": False,
    }


# ---------------------------------------------------------------------------
# Model tests
# ---------------------------------------------------------------------------


class TestBondSearchRequestSerialization:
    def test_empty_request_serializes_to_empty_dict(self) -> None:
        params = BondSearchRequest().model_dump(by_alias=True, exclude_none=True)
        assert params == {}

    def test_fields_serialize_with_camel_case_aliases(self) -> None:
        request = BondSearchRequest(
            page_number=2,
            page_size=50,
            sort_property="maturityDate",
            sort_direction=SortDirection.ASC,
            issuer="Apple",
            issuer_symbol=["AAPL"],
            bond_status=[BondStatus.OUTSTANDING],
            bond_type=[BondType.CORPORATE, BondType.TREASURY],
            treasury_subtype=[TreasurySubtype.STRIPS],
            rating=[BondRating.AA_PLUS, BondRating.AAA],
            rating_category=RatingCategory.INVESTMENT_GRADE,
            coupon_frequency=[CouponFrequency.SEMI_ANNUAL],
            min_coupon=Decimal("2.5"),
            max_current_yield=Decimal("6.0"),
            min_par_value=Decimal("1000"),
            callable=False,
            perpetual=False,
            partial_par=True,
        )
        params = request.model_dump(by_alias=True, exclude_none=True)
        assert params["pageNumber"] == 2
        assert params["pageSize"] == 50
        assert params["sortProperty"] == "maturityDate"
        assert params["sortDirection"] == SortDirection.ASC
        assert params["issuerSymbol"] == ["AAPL"]
        assert params["bondStatus"] == [BondStatus.OUTSTANDING]
        assert params["bondType"] == [BondType.CORPORATE, BondType.TREASURY]
        assert params["treasurySubtype"] == [TreasurySubtype.STRIPS]
        assert params["rating"] == [BondRating.AA_PLUS, BondRating.AAA]
        assert params["ratingCategory"] == RatingCategory.INVESTMENT_GRADE
        assert params["couponFrequency"] == [CouponFrequency.SEMI_ANNUAL]
        assert params["minCoupon"] == Decimal("2.5")
        assert params["maxCurrentYield"] == Decimal("6.0")
        assert params["minParValue"] == Decimal("1000")
        assert params["callable"] is False
        assert params["perpetual"] is False
        assert params["partialPar"] is True
        # unset filters must not appear in the query at all
        assert "spOutlook" not in params
        assert "minMaturityDate" not in params

    def test_dates_serialize_to_iso_strings(self) -> None:
        request = BondSearchRequest(
            min_maturity_date=date(2027, 1, 15),
            max_maturity_date=date(2050, 12, 31),
        )
        params = request.model_dump(by_alias=True, exclude_none=True)
        assert params["minMaturityDate"] == "2027-01-15"
        assert params["maxMaturityDate"] == "2050-12-31"

    def test_populate_by_camel_case_name(self) -> None:
        request = BondSearchRequest(pageNumber=1, bondType=[BondType.MUNICIPAL])
        assert request.page_number == 1
        assert request.bond_type == [BondType.MUNICIPAL]

    def test_rating_enum_values_keep_symbols(self) -> None:
        assert BondRating.AA_PLUS.value == "AA+"
        assert BondRating.BBB_MINUS.value == "BBB-"
        assert BondRating.SP_1_PLUS.value == "SP-1+"
        assert BondRating.A_1.value == "A-1"


class TestBondSearchResponsePageDeserialization:
    def test_full_page(self) -> None:
        page = BondSearchResponsePage(**_bond_page_payload())
        assert page.total_elements == 1
        assert page.total_pages == 1
        assert page.number_of_elements == 1
        assert page.first is True
        assert page.last is True
        assert page.empty is False
        assert page.sort is not None and page.sort.sorted is True
        assert page.pageable is not None
        assert page.pageable.page_size == 20
        assert page.pageable.page_number == 0
        bond = page.content[0]
        assert bond.cusip == "912810TM0"
        assert bond.symbol == "912810TM0-BOND"
        assert bond.bond_type == "TREASURY"
        assert bond.maturity_date == date(2048, 8, 15)
        assert bond.days_until_maturity == 8045
        assert bond.partial_par is True

    def test_empty_page(self) -> None:
        page = BondSearchResponsePage(
            **{"totalElements": 0, "totalPages": 0, "content": [], "empty": True}
        )
        assert page.content == []
        assert page.empty is True

    def test_minimal_payload(self) -> None:
        page = BondSearchResponsePage()
        assert page.content == []
        assert page.total_elements is None


class TestBondDetailsResponseDeserialization:
    def test_full_details(self) -> None:
        details = BondDetailsResponse(**_bond_payload())
        assert details.cusip == "912810TM0"
        assert details.issuer == "United States Treasury"
        assert details.rating == "AA+"
        assert details.rating_category == "INVESTMENT_GRADE"
        assert details.coupon == "3.375"
        assert details.coupon_frequency == "SEMI_ANNUAL"
        assert details.next_coupon_date == date(2027, 2, 15)
        assert details.callable is False
        assert details.current_yield == "4.21"
        assert details.minimum_order_size == "1000"

    def test_nullable_fields_default_to_none(self) -> None:
        details = BondDetailsResponse(**{"cusip": "912810TM0"})
        assert details.cusip == "912810TM0"
        assert details.issuer is None
        assert details.maturity_date is None
        assert details.next_call_date is None


# ---------------------------------------------------------------------------
# Sync client tests
# ---------------------------------------------------------------------------


class TestSearchBonds:
    def test_hits_bonds_endpoint_without_params(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_bond_page_payload())
        page = client.search_bonds()
        url = client.api_client.get.call_args[0][0]
        assert url == "/userapigateway/trading/instruments/bonds"
        assert client.api_client.get.call_args.kwargs["params"] is None
        assert page.total_elements == 1

    def test_passes_filters_as_camel_case_params(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_bond_page_payload())
        client.search_bonds(
            BondSearchRequest(
                bond_type=[BondType.TREASURY],
                min_maturity_date=date(2027, 1, 15),
                page_size=50,
            )
        )
        params = client.api_client.get.call_args.kwargs["params"]
        assert params["bondType"] == [BondType.TREASURY]
        assert params["minMaturityDate"] == "2027-01-15"
        assert params["pageSize"] == 50


class TestGetBondDetails:
    def test_hits_bond_details_endpoint(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_bond_payload())
        details = client.get_bond_details("912810TM0-BOND")
        url = client.api_client.get.call_args[0][0]
        assert url == (
            f"/userapigateway/marketdata/{_ACCOUNT}/bond-details/912810TM0-BOND"
        )
        assert details.cusip == "912810TM0"

    def test_explicit_account_overrides_default(self) -> None:
        client = _make_client()
        client.api_client.get = Mock(return_value=_bond_payload())
        client.get_bond_details("912810TM0-BOND", account_id="OTHER_ACC")
        url = client.api_client.get.call_args[0][0]
        assert "/marketdata/OTHER_ACC/" in url

    def test_no_account_raises_value_error(self) -> None:
        client = _make_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            client.get_bond_details("912810TM0-BOND")


# ---------------------------------------------------------------------------
# Async client tests
# ---------------------------------------------------------------------------


class TestAsyncSearchBonds:
    @pytest.mark.asyncio
    async def test_hits_bonds_endpoint(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_bond_page_payload())
        page = await client.search_bonds()
        url = client.api_client.get.call_args[0][0]
        assert url == "/userapigateway/trading/instruments/bonds"
        assert page.content[0].symbol == "912810TM0-BOND"

    @pytest.mark.asyncio
    async def test_passes_filters_as_camel_case_params(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_bond_page_payload())
        await client.search_bonds(
            BondSearchRequest(rating_category=RatingCategory.INVESTMENT_GRADE)
        )
        params = client.api_client.get.call_args.kwargs["params"]
        assert params["ratingCategory"] == RatingCategory.INVESTMENT_GRADE


class TestAsyncGetBondDetails:
    @pytest.mark.asyncio
    async def test_hits_bond_details_endpoint(self) -> None:
        client = _make_async_client()
        client.api_client.get = AsyncMock(return_value=_bond_payload())
        details = await client.get_bond_details("912810TM0-BOND")
        url = client.api_client.get.call_args[0][0]
        assert url == (
            f"/userapigateway/marketdata/{_ACCOUNT}/bond-details/912810TM0-BOND"
        )
        assert details.issuer == "United States Treasury"

    @pytest.mark.asyncio
    async def test_no_account_raises_value_error(self) -> None:
        client = _make_async_client(default_account=None)
        with pytest.raises(ValueError, match="No account ID provided"):
            await client.get_bond_details("912810TM0-BOND")
