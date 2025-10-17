from typing import List, Optional

from .api_client import ApiClient
from .auth_manager import AuthManager
from .auth_config import AuthConfig
from .subscription_manager import PriceSubscriptionManager
from .price_stream import PriceStream
from .order_subscription_manager import OrderSubscriptionManager
from .models import (
    AccountsResponse,
    HistoryRequest,
    HistoryResponsePage,
    Instrument,
    InstrumentsRequest,
    InstrumentsResponse,
    InstrumentType,
    OrderInstrument,
    Quote,
    PreflightRequest,
    PreflightResponse,
    PreflightMultiLegRequest,
    PreflightMultiLegResponse,
    Order,
    OrderRequest,
    OrderResponse,
    MultilegOrderRequest,
    MultilegOrderResult,
    Portfolio,
    OptionExpirationsRequest,
    OptionExpirationsResponse,
    OptionChainRequest,
    OptionChainResponse,
    OptionGreeks,
    NewOrder,
)


PROD_BASE_URL = "https://api.public.com"


class PublicApiClientConfiguration:
    DEFAULT: "PublicApiClientConfiguration"

    def __init__(
        self,
        default_account_number: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        # explicit base_url overrides the default production URL
        self.base_url = base_url or PROD_BASE_URL
        self.default_account_number = default_account_number

    def get_base_url(self) -> str:
        return self.base_url


PublicApiClientConfiguration.DEFAULT = PublicApiClientConfiguration()


class PublicApiClient:
    """Public API client"""

    def __init__(
        self,
        auth_config: AuthConfig,
        config: PublicApiClientConfiguration = PublicApiClientConfiguration.DEFAULT,
    ) -> None:
        """Initialize the trading client.

        Args:
            auth_config: Authentication configuration
            config: Configuration for the API client
        """
        super().__init__()

        self.config = config

        self.api_client = ApiClient(base_url=config.get_base_url())

        self.auth_manager = AuthManager(
            auth_provider=auth_config.create_provider(self.api_client)
        )

        # initialize subscription manager and price stream
        self._subscription_manager = PriceSubscriptionManager(
            get_quotes_func=self.get_quotes
        )
        self.price_stream = PriceStream(self._subscription_manager)

        # initialize order subscription manager
        self._order_subscription_manager = OrderSubscriptionManager(
            get_order_func=self.get_order
        )

    @property
    def api_endpoint(self) -> str:
        """The current API endpoint (base URL).

        This returns the underlying ApiClient's base URL. Assigning to this
        property will change the base URL used for subsequent requests, which
        is useful for directing a client to a different environment without
        recreating the client.
        """
        return self.api_client.base_url

    @api_endpoint.setter
    def api_endpoint(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("api_endpoint must be a string URL")
        # normalize and set on the ApiClient so subsequent requests use it
        self.api_client.base_url = value.rstrip("/")

    def close(self) -> None:
        # stop subscription managers first
        if hasattr(self, "_subscription_manager"):
            self._subscription_manager.stop()
        if hasattr(self, "_order_subscription_manager"):
            self._order_subscription_manager.stop()
        self.api_client.close()

    def __get_account_id(self, account_id: Optional[str] = None) -> str:
        if account_id:
            return account_id
        if self.config.default_account_number:
            return self.config.default_account_number
        raise ValueError("No account ID provided")

    def get_accounts(self) -> AccountsResponse:
        """Get accounts.

        Returns:
            Account list
        """
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get("/userapigateway/trading/account")
        return AccountsResponse(**response)

    def get_portfolio(self, account_id: Optional[str] = None) -> Portfolio:
        """
        Retrieves a snapshot of a specified account’s portfolio, including
        positions, equity breakdown, buying power, and open orders.
        Only non-IRA accounts are supported.

        Args:
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            Portfolio data including positions and balances
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            f"/userapigateway/trading/{account_id}/portfolio/v2"
        )
        return Portfolio(**response)

    def get_history(
        self,
        history_request: Optional[HistoryRequest] = None,
        account_id: Optional[str] = None,
    ) -> HistoryResponsePage:
        """
        Retrieve account history.

        Fetches a paginated list of historical events for the specified account.
        Supports optional time range filtering and pagination via a continuation token.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            f"/userapigateway/trading/{account_id}/history",
            params=(
                history_request.model_dump(by_alias=True, exclude_none=True)
                if history_request
                else None
            ),
        )
        return HistoryResponsePage(**response)

    def get_all_instruments(
        self,
        instruments_request: Optional[InstrumentsRequest] = None,
        account_id: Optional[str] = None,
    ) -> InstrumentsResponse:
        """
        Retrieves all available trading instruments with optional filtering capabilities.

        This method returns a comprehensive list of instruments available for trading,
        with support for filtering by security type and various trading capabilities.
        All filter parameters are optional and can be combined to narrow down results.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            "/userapigateway/trading/instruments",
            params=(
                instruments_request.model_dump(by_alias=True, exclude_none=True)
                if instruments_request
                else None
            ),
        )
        return InstrumentsResponse(**response)

    def get_instrument(
        self, symbol: str, instrument_type: InstrumentType
    ) -> Instrument:
        """
        Get instrument details.
        """
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            f"/userapigateway/trading/instruments/{symbol}/{instrument_type.value}"
        )
        return Instrument(**response)

    def get_quotes(
        self, instruments: List[OrderInstrument], account_id: Optional[str] = None
    ) -> List[Quote]:
        """Get quotes for multiple symbols.

        Args:
            symbols: List of symbols
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            List of quotes
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/quotes",
            json_data={
                "instruments": [instrument.model_dump() for instrument in instruments]
            },
        )
        quotes = response.get("quotes", [])
        return [Quote(**quote) for quote in quotes]

    def get_option_expirations(
        self,
        expirations_request: OptionExpirationsRequest,
        account_id: Optional[str] = None,
    ) -> OptionExpirationsResponse:
        """
        Retrieve option expiration dates.

        Returns available option expiration dates for a given instrument.
        Requires the `marketdata` scope. Supported types: EQUITY,
        UNDERLYING_SECURITY_FOR_INDEX_OPTION.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/option-expirations",
            json_data=expirations_request.model_dump(by_alias=True, exclude_none=True),
        )
        return OptionExpirationsResponse(**response)

    def get_option_chain(
        self,
        option_chain_request: OptionChainRequest,
        account_id: Optional[str] = None,
    ) -> OptionChainResponse:
        """
        Retrieve option chain.

        Returns the option chain for a given instrument. Requires the `marketdata`
        scope. Supported types: EQUITY, UNDERLYING_SECURITY_FOR_INDEX_OPTION.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/option-chain",
            json_data=option_chain_request.model_dump(by_alias=True, exclude_none=True),
        )
        return OptionChainResponse(**response)

    def get_option_greeks(
        self,
        osi_option_symbol: str,
        account_id: Optional[str] = None,
    ) -> OptionGreeks:
        """
        Get option greeks for a specific option symbol (OSI-normalized format)

        Args:
            osi_option_symbol: OSI-normalized option symbol
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            Option greeks
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            f"/userapigateway/option-details/{account_id}/{osi_option_symbol}/greeks"
        )
        return OptionGreeks(**response)

    def perform_preflight_calculation(
        self,
        preflight_request: PreflightRequest,
        account_id: Optional[str] = None,
    ) -> PreflightResponse:
        """
        Calculates the estimated financial impact of a potential trade before execution.

        Performs preflight calculations for a single-leg order (a transaction
        involving a single security) to provide comprehensive cost estimates
        and account impact details. Returns estimated
        commission, regulatory fees, order value, buying power requirements,
        margin impact, and other trade-specific information to help users make
        informed trading decisions before order placement. Note that these are
        estimates only, and actual execution values may vary depending on
        market conditions.

        This may be called before submitting an actual order to understand the
        potential financial implications.

        Args:
            preflight_request: PreflightRequest
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            Response contains estimated costs, fees, and other information
            needed before placing a single-leg order.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/trading/{account_id}/preflight/single-leg",
            json_data=preflight_request.model_dump(by_alias=True, exclude_none=True),
        )
        return PreflightResponse(**response)

    def perform_multi_leg_preflight_calculation(
        self,
        preflight_request: PreflightMultiLegRequest,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """
        Calculates the estimated financial impact of a complex multi-leg trade
        before execution.

        Performs preflight calculations for a multi-leg order (a transaction
        involving multiple securities or options strategies such as spreads,
        straddles, or combinations) to provide comprehensive cost estimates
        and account impact details. Returns estimated commission, regulatory
        fees, total order value, buying power requirements, margin impact,
        net credit/debit amounts, and strategy-specific information to help users
        make informed trading decisions before order placement.

        This handles complex options strategies and calculates the combined
        effect of all legs in the trade. Note that these are estimates only,
        and actual execution values may vary depending on market conditions and
        fill prices.

        This may be called before submitting an actual multi-leg order to understand
        the potential financial implications of the strategy.

        Args:
            preflight_request: PreflightRequest
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            Response contains estimated costs, fees, and other information
            needed before placing a single-leg order.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/trading/{account_id}/preflight/multi-leg",
            json_data=preflight_request.model_dump(by_alias=True, exclude_none=True),
        )
        return PreflightMultiLegResponse(**response)

    def place_order(
        self,
        order_request: OrderRequest,
        account_id: Optional[str] = None,
    ) -> NewOrder:
        """Place a single-leg order.

        Args:
            order_request: OrderRequest
            account_id: Account ID

        Returns:
            NewOrder object for tracking and managing the order
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/trading/{account_id}/order",
            json_data=order_request.model_dump(by_alias=True, exclude_none=True),
        )
        order_response = OrderResponse(**response)

        return NewOrder(
            order_id=order_response.order_id,
            account_id=account_id,
            client=self,
            subscription_manager=self._order_subscription_manager,
        )

    def place_multileg_order(
        self,
        order_request: MultilegOrderRequest,
        account_id: Optional[str] = None,
    ) -> NewOrder:
        """Place a multi-leg order.

        Submits a new multi-leg order asynchronously for the specified account.
        Note: Order placement is asynchronous. This response confirms submission only.
        Use the returned NewOrder object to track status and updates.

        Args:
            order_request: MultilegOrderRequest
            account_id: Account ID

        Returns:
            NewOrder object for tracking and managing the order
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.post(
            f"/userapigateway/trading/{account_id}/order/multileg",
            json_data=order_request.model_dump(by_alias=True, exclude_none=True),
        )
        order_result = MultilegOrderResult(**response)

        return NewOrder(
            order_id=order_result.order_id,
            account_id=account_id,
            client=self,
            subscription_manager=self._order_subscription_manager,
        )

    def get_order(
        self,
        order_id: str,
        account_id: Optional[str] = None,
    ) -> Order:
        """
        Retrieves the status and details of a specific order for the given account.\n\n
        Note: Order placement is asynchronous. This endpoint may return an error
        if the order has not yet been indexed for retrieval.\nIn some cases,
        the order may already be active in the market but momentarily not yet
        visible through the API due to eventual consistency.

        Args:
            order_id: Order ID
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            Order details, including the status.
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            f"/userapigateway/trading/{account_id}/order/{order_id}"
        )
        return Order(**response)

    def cancel_order(
        self,
        order_id: str,
        account_id: Optional[str] = None,
    ) -> None:
        """
        Submits an asynchronous request to cancel the specified order.\n\n
        Note: While most cancellations are processed immediately during market
        hours, this is not guaranteed.\nAlways use the `get_order` method to
        confirm whether the order has been cancelled.

        Args:
            order_id: Order ID to cancel
            account_id: Account ID (optional if `default_account_number` is set)
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        self.api_client.delete(f"/userapigateway/trading/{account_id}/order/{order_id}")
