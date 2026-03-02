"""AsyncPublicApiClient — async counterpart to PublicApiClient."""

from typing import List, Optional, TYPE_CHECKING

from .async_api_client import AsyncApiClient
from .async_auth_provider import AsyncAuthManager
from .async_order_subscription_manager import AsyncOrderSubscriptionManager
from .async_price_stream import AsyncPriceStream
from .async_subscription_manager import AsyncPriceSubscriptionManager
from .models import (
    AccountsResponse,
    GreeksResponse,
    HistoryRequest,
    HistoryResponsePage,
    Instrument,
    InstrumentsRequest,
    InstrumentsResponse,
    InstrumentType,
    MultilegOrderRequest,
    MultilegOrderResult,
    OptionChainRequest,
    OptionChainResponse,
    OptionExpirationsRequest,
    OptionExpirationsResponse,
    OptionGreeks,
    Order,
    OrderInstrument,
    OrderRequest,
    OrderResponse,
    Portfolio,
    PreflightMultiLegRequest,
    PreflightMultiLegResponse,
    PreflightRequest,
    PreflightResponse,
    Quote,
)
from .models.async_new_order import AsyncNewOrder

if TYPE_CHECKING:
    from .auth_config import AsyncAuthConfig

PROD_BASE_URL = "https://api.public.com"


class AsyncPublicApiClientConfiguration:
    """Configuration for AsyncPublicApiClient."""

    DEFAULT: "AsyncPublicApiClientConfiguration"

    def __init__(
        self,
        default_account_number: Optional[str] = None,
        base_url: Optional[str] = None,
    ) -> None:
        self.base_url = base_url or PROD_BASE_URL
        self.default_account_number = default_account_number

    def get_base_url(self) -> str:
        return self.base_url


AsyncPublicApiClientConfiguration.DEFAULT = AsyncPublicApiClientConfiguration()


class AsyncPublicApiClient:
    """Async Public.com trading API client.

    All API methods are coroutines and must be awaited.  Supports the async
    context manager protocol so resources are cleaned up automatically::

        async with AsyncPublicApiClient(auth_config) as client:
            accounts = await client.get_accounts()
            quotes   = await client.get_quotes([OrderInstrument(...)])

    Token acquisition is *lazy*: the first API call triggers a token fetch.
    No I/O is performed in ``__init__``.

    Args:
        auth_config: Authentication configuration (ApiKeyAuthConfig or OAuthAuthConfig)
        config: Optional client configuration (base URL, default account number)
    """

    def __init__(
        self,
        auth_config: "AsyncAuthConfig",
        config: AsyncPublicApiClientConfiguration = AsyncPublicApiClientConfiguration.DEFAULT,
    ) -> None:
        self.config = config

        self.api_client = AsyncApiClient(base_url=config.get_base_url())

        async_provider = auth_config.create_async_provider(self.api_client)
        self.auth_manager = AsyncAuthManager(auth_provider=async_provider)

        self._subscription_manager = AsyncPriceSubscriptionManager(
            get_quotes_func=self.get_quotes
        )
        self.price_stream = AsyncPriceStream(self._subscription_manager)

        self._order_subscription_manager = AsyncOrderSubscriptionManager(
            get_order_func=self.get_order
        )

    # ------------------------------------------------------------------ #
    # Context manager                                                      #
    # ------------------------------------------------------------------ #

    async def __aenter__(self) -> "AsyncPublicApiClient":
        return self

    async def __aexit__(
        self,
        exc_type: object,
        exc_val: object,
        exc_tb: object,
    ) -> None:
        await self.close()

    async def close(self) -> None:
        """Cancel subscription tasks and close the HTTP client."""
        await self._subscription_manager.stop()
        await self._order_subscription_manager.stop()
        await self.api_client.aclose()

    # ------------------------------------------------------------------ #
    # Endpoint property                                                    #
    # ------------------------------------------------------------------ #

    @property
    def api_endpoint(self) -> str:
        """The current API base URL.

        Assigning a new URL redirects all subsequent requests without
        recreating the client.
        """
        return self.api_client.base_url

    @api_endpoint.setter
    def api_endpoint(self, value: str) -> None:
        if not isinstance(value, str):
            raise TypeError("api_endpoint must be a string URL")
        self.api_client.base_url = value.rstrip("/")

    # ------------------------------------------------------------------ #
    # Internal helpers                                                     #
    # ------------------------------------------------------------------ #

    def _get_account_id(self, account_id: Optional[str] = None) -> str:
        if account_id:
            return account_id
        if self.config.default_account_number:
            return self.config.default_account_number
        raise ValueError("No account ID provided")

    # ------------------------------------------------------------------ #
    # Account / portfolio                                                  #
    # ------------------------------------------------------------------ #

    async def get_accounts(self) -> AccountsResponse:
        """Get all accounts associated with the authenticated user.

        Returns:
            AccountsResponse containing account list
        """
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get("/userapigateway/trading/account")
        return AccountsResponse(**response)

    async def get_portfolio(self, account_id: Optional[str] = None) -> Portfolio:
        """Retrieve a snapshot of an account's portfolio.

        Args:
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            Portfolio including positions, balances, and buying power
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/trading/{account_id}/portfolio/v2"
        )
        return Portfolio(**response)

    async def get_history(
        self,
        history_request: Optional[HistoryRequest] = None,
        account_id: Optional[str] = None,
    ) -> HistoryResponsePage:
        """Retrieve paginated account history.

        Args:
            history_request: Optional time range and pagination parameters
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            HistoryResponsePage with events and optional continuation token
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/trading/{account_id}/history",
            params=(
                history_request.model_dump(by_alias=True, exclude_none=True)
                if history_request
                else None
            ),
        )
        return HistoryResponsePage(**response)

    # ------------------------------------------------------------------ #
    # Instruments                                                          #
    # ------------------------------------------------------------------ #

    async def get_all_instruments(
        self,
        instruments_request: Optional[InstrumentsRequest] = None,
        account_id: Optional[str] = None,
    ) -> InstrumentsResponse:
        """Retrieve all available trading instruments.

        Args:
            instruments_request: Optional filters (type, capabilities)
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            InstrumentsResponse with the matching instruments
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            "/userapigateway/trading/instruments",
            params=(
                instruments_request.model_dump(by_alias=True, exclude_none=True)
                if instruments_request
                else None
            ),
        )
        return InstrumentsResponse(**response)

    async def get_instrument(
        self, symbol: str, instrument_type: InstrumentType
    ) -> Instrument:
        """Retrieve details for a specific instrument.

        Args:
            symbol: Ticker symbol
            instrument_type: Type of instrument (e.g. EQUITY, OPTION)

        Returns:
            Instrument details
        """
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/trading/instruments/{symbol}/{instrument_type.value}"
        )
        return Instrument(**response)

    # ------------------------------------------------------------------ #
    # Market data                                                          #
    # ------------------------------------------------------------------ #

    async def get_quotes(
        self,
        instruments: List[OrderInstrument],
        account_id: Optional[str] = None,
    ) -> List[Quote]:
        """Get quotes for one or more instruments.

        Args:
            instruments: List of instruments to quote
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            List of Quote objects
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/quotes",
            json_data={
                "instruments": [instrument.model_dump() for instrument in instruments]
            },
        )
        return [Quote(**q) for q in response.get("quotes", [])]

    async def get_option_expirations(
        self,
        expirations_request: OptionExpirationsRequest,
        account_id: Optional[str] = None,
    ) -> OptionExpirationsResponse:
        """Retrieve available option expiration dates for an instrument.

        Args:
            expirations_request: Instrument and type parameters
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            OptionExpirationsResponse with available expiration dates
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/option-expirations",
            json_data=expirations_request.model_dump(by_alias=True, exclude_none=True),
        )
        return OptionExpirationsResponse(**response)

    async def get_option_chain(
        self,
        option_chain_request: OptionChainRequest,
        account_id: Optional[str] = None,
    ) -> OptionChainResponse:
        """Retrieve the full option chain for an instrument.

        Args:
            option_chain_request: Instrument, expiration, and filter parameters
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            OptionChainResponse with calls and puts
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/option-chain",
            json_data=option_chain_request.model_dump(
                by_alias=True, exclude_none=True
            ),
        )
        return OptionChainResponse(**response)

    async def get_option_greeks(
        self,
        osi_symbols: List[str],
        account_id: Optional[str] = None,
    ) -> GreeksResponse:
        """Get option greeks for multiple OSI-normalized symbols.

        Args:
            osi_symbols: List of OSI-normalized option symbols
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            GreeksResponse with greeks for each requested symbol
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/option-details/{account_id}/greeks",
            params={"osiSymbols": osi_symbols},
        )
        return GreeksResponse(**response)

    async def get_option_greek(
        self,
        osi_symbol: str,
        account_id: Optional[str] = None,
    ) -> OptionGreeks:
        """Get option greeks for a single OSI-normalized symbol.

        Args:
            osi_symbol: OSI-normalized option symbol
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            OptionGreeks for the requested symbol
        """
        greeks_response = await self.get_option_greeks(
            osi_symbols=[osi_symbol], account_id=account_id
        )
        if not greeks_response.greeks:
            raise ValueError(f"No greeks found for symbol: {osi_symbol}")
        return greeks_response.greeks[0]

    # ------------------------------------------------------------------ #
    # Preflight calculations                                               #
    # ------------------------------------------------------------------ #

    async def perform_preflight_calculation(
        self,
        preflight_request: PreflightRequest,
        account_id: Optional[str] = None,
    ) -> PreflightResponse:
        """Estimate the financial impact of a single-leg order before placing it.

        Args:
            preflight_request: Order parameters to estimate
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            PreflightResponse with estimated commission, fees, and buying power impact
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/trading/{account_id}/preflight/single-leg",
            json_data=preflight_request.model_dump(by_alias=True, exclude_none=True),
        )
        return PreflightResponse(**response)

    async def perform_multi_leg_preflight_calculation(
        self,
        preflight_request: PreflightMultiLegRequest,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Estimate the financial impact of a multi-leg order before placing it.

        Args:
            preflight_request: Multi-leg order parameters to estimate
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            PreflightMultiLegResponse with net credit/debit, commission, and fees
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/trading/{account_id}/preflight/multi-leg",
            json_data=preflight_request.model_dump(by_alias=True, exclude_none=True),
        )
        return PreflightMultiLegResponse(**response)

    # ------------------------------------------------------------------ #
    # Order placement                                                      #
    # ------------------------------------------------------------------ #

    async def place_order(
        self,
        order_request: OrderRequest,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a single-leg order.

        Args:
            order_request: Order parameters
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            AsyncNewOrder for tracking the order status
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/trading/{account_id}/order",
            json_data=order_request.model_dump(by_alias=True, exclude_none=True),
        )
        order_response = OrderResponse(**response)
        return AsyncNewOrder(
            order_id=order_response.order_id,
            account_id=account_id,
            client=self,
            subscription_manager=self._order_subscription_manager,
        )

    async def place_multileg_order(
        self,
        order_request: MultilegOrderRequest,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a multi-leg order.

        Args:
            order_request: Multi-leg order parameters
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            AsyncNewOrder for tracking the order status
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/trading/{account_id}/order/multileg",
            json_data=order_request.model_dump(by_alias=True, exclude_none=True),
        )
        order_result = MultilegOrderResult(**response)
        return AsyncNewOrder(
            order_id=order_result.order_id,
            account_id=account_id,
            client=self,
            subscription_manager=self._order_subscription_manager,
        )

    # ------------------------------------------------------------------ #
    # Order retrieval / cancellation                                       #
    # ------------------------------------------------------------------ #

    async def get_order(
        self,
        order_id: str,
        account_id: Optional[str] = None,
    ) -> Order:
        """Retrieve the status and details of a specific order.

        Note: Order placement is asynchronous. The order may not be
        immediately visible after placement due to eventual consistency.

        Args:
            order_id: The order ID to retrieve
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            Order with current status and fill details
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/trading/{account_id}/order/{order_id}"
        )
        return Order(**response)

    async def cancel_order(
        self,
        order_id: str,
        account_id: Optional[str] = None,
    ) -> None:
        """Submit an asynchronous cancellation request for an order.

        Note: Use get_order() or subscribe_updates() to confirm cancellation.

        Args:
            order_id: The order ID to cancel
            account_id: Account ID (optional when default_account_number is set)
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        await self.api_client.delete(
            f"/userapigateway/trading/{account_id}/order/{order_id}"
        )
