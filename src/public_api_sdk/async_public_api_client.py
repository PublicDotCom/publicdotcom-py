"""AsyncPublicApiClient — async counterpart to PublicApiClient."""

from datetime import datetime
from decimal import Decimal
from typing import List, Optional, TYPE_CHECKING

import httpx

from .async_api_client import AsyncApiClient
from .async_auth_provider import AsyncAuthManager
from .async_order_subscription_manager import AsyncOrderSubscriptionManager
from .async_price_stream import AsyncPriceStream
from .async_strategy_preflight import AsyncStrategyPreflight
from .async_subscription_manager import AsyncPriceSubscriptionManager
from .strategy_preflight import (
    _SpreadKind,
    _build_two_leg_spread_order_request,
    _build_two_leg_spread_request,
)
from .models import (
    AccountsResponse,
    BarAggregation,
    BarPeriod,
    BarsResponse,
    Base64File,
    CancelAndReplaceRequest,
    EquityMarketSession,
    GreeksResponse,
    HistoryRequest,
    HistoryResponsePage,
    Instrument,
    InstrumentsRequest,
    InstrumentsResponse,
    InstrumentType,
    MultilegOrderRequest,
    OptionChainRequest,
    OptionChainResponse,
    OptionExpirationsRequest,
    OptionExpirationsResponse,
    OptionGreeksResponse,
    Order,
    OrderInstrument,
    OrderRequest,
    OrderResult,
    OrderType,
    Portfolio,
    PreflightMultiLegRequest,
    PreflightMultiLegResponse,
    PreflightRequest,
    PreflightResponse,
    Quote,
    QuoteRequest,
    StrategyQuoteDto,
    StrategyQuoteRequest,
    TimeInForce,
    TradingSessionToggle,
    UnrealizedLotsDetailResponse,
    UnrealizedLotsSummaryResponse,
)
from .models.async_new_order import AsyncNewOrder
from .short_order import (
    AsyncFlattenAndShortResult,
    _build_flatten_long_order_request,
    _build_short_order_request,
    _build_short_preflight_request,
    _get_equity_position_quantity,
)

if TYPE_CHECKING:
    from .auth_config import AsyncAuthConfig

PROD_BASE_URL = "https://api.public.com"

_BAR_INSTRUMENT_TYPES = frozenset(
    {
        InstrumentType.EQUITY,
        InstrumentType.CRYPTO,
        InstrumentType.OPTION,
        InstrumentType.INDEX,
    }
)


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
        http_client: Optional pre-configured httpx.AsyncClient. When provided,
            the SDK uses it for all requests and will not close it on
            ``close()`` — the caller owns the lifecycle.
    """

    def __init__(
        self,
        auth_config: "AsyncAuthConfig",
        config: AsyncPublicApiClientConfiguration = AsyncPublicApiClientConfiguration.DEFAULT,
        *,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        self.config = config

        self.api_client = AsyncApiClient(
            base_url=config.get_base_url(), http_client=http_client
        )

        async_provider = auth_config.create_async_provider(self.api_client)
        self.auth_manager = AsyncAuthManager(auth_provider=async_provider)

        self._subscription_manager = AsyncPriceSubscriptionManager(
            get_quotes_func=self.get_quotes
        )
        self.price_stream = AsyncPriceStream(self._subscription_manager)

        self._order_subscription_manager = AsyncOrderSubscriptionManager(
            get_order_func=self.get_order
        )

        self.strategy_preflight = AsyncStrategyPreflight(
            preflight_func=self.perform_multi_leg_preflight_calculation
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

    async def get_unrealized_tax_lots(
        self, account_id: Optional[str] = None
    ) -> UnrealizedLotsSummaryResponse:
        """Retrieve an overview of unrealized tax lots for an account. Async.

        Requires the ``portfolio`` scope.

        Args:
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            UnrealizedLotsSummaryResponse with per-symbol lot summaries and totals
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/trading/{account_id}/taxlots/unrealized"
        )
        return UnrealizedLotsSummaryResponse(**response)

    async def get_unrealized_tax_lots_for_symbol(
        self,
        symbol: str,
        account_id: Optional[str] = None,
        price: Optional[str] = None,
    ) -> UnrealizedLotsDetailResponse:
        """Retrieve detailed unrealized tax lots for a specific symbol. Async.

        Requires the ``portfolio`` scope.

        Args:
            symbol: The ticker to retrieve lots for.
            account_id: Account ID (optional when default_account_number is set)
            price: Optional explicit price used to calculate gain/loss.

        Returns:
            UnrealizedLotsDetailResponse with the individual lots for the symbol
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        params = {"price": price} if price is not None else None
        response = await self.api_client.get(
            f"/userapigateway/trading/{account_id}/taxlots/unrealized/{symbol}",
            params=params,
        )
        return UnrealizedLotsDetailResponse(**response)

    async def get_unrealized_tax_lots_csv(
        self, account_id: Optional[str] = None
    ) -> Base64File:
        """Retrieve unrealized tax lots for an account as a base64 CSV. Async.

        Requires the ``portfolio`` scope.

        Args:
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            Base64File whose ``base64_data`` holds the base64-encoded CSV export
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.get(
            f"/userapigateway/trading/{account_id}/taxlots/csv/unrealized"
        )
        return Base64File(**response)

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
        request = QuoteRequest(instruments=instruments)
        response = await self.api_client.post(
            f"/userapigateway/marketdata/{account_id}/quotes",
            json_data=request.model_dump(by_alias=True, exclude_none=True),
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

    async def get_bars(
        self,
        symbol: str,
        period: BarPeriod,
        *,
        instrument_type: InstrumentType = InstrumentType.EQUITY,
        aggregation: Optional[BarAggregation] = None,
        purchase_date: Optional[str] = None,
        trading_session_toggle: Optional[TradingSessionToggle] = None,
    ) -> BarsResponse:
        """Fetch OHLCV bar data for a symbol over a given time period.

        Args:
            symbol: The ticker symbol (e.g. ``"AAPL"``).
            period: The time window to retrieve (e.g. ``BarPeriod.YEAR``).
            instrument_type: One of ``EQUITY``, ``CRYPTO``, ``OPTION``, ``INDEX``.
                Defaults to ``EQUITY``.
            aggregation: Optional bar size override. When omitted the server
                chooses an appropriate aggregation for the period.
            purchase_date: Required when ``period`` is ``BarPeriod.SINCE_PURCHASE``.
                Format: ``"YYYY-MM-DD"``.
            trading_session_toggle: Which sessions to include on the DAY equity
                chart. When omitted the server defaults to
                ``REGULAR_AND_EXTENDED_HOURS``. ``ALL_SESSIONS`` adds the
                overnight ATS sessions (``pre_market_overnight`` and
                ``post_market_overnight`` on the response).

        Returns:
            BarsResponse with pre-market, regular-market, and after-hours bars.
        """
        if instrument_type not in _BAR_INSTRUMENT_TYPES:
            raise ValueError(
                f"{instrument_type} is not supported for historic bars; "
                f"expected one of EQUITY, CRYPTO, OPTION, INDEX"
            )
        await self.auth_manager.refresh_token_if_needed()
        path = (
            f"/userapigateway/historicdata/{instrument_type.value}"
            f"/{symbol}/{period.value}"
        )
        if aggregation is not None:
            path += f"/{aggregation.value}"
        params = {}
        if purchase_date:
            params["purchaseDate"] = purchase_date
        if trading_session_toggle is not None:
            params["tradingSessionToggle"] = trading_session_toggle.value
        response = await self.api_client.get(path, params=params or None)
        return BarsResponse(**response)

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
    ) -> OptionGreeksResponse:
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

    async def get_strategy_quote(
        self,
        request: StrategyQuoteRequest,
        account_id: Optional[str] = None,
    ) -> StrategyQuoteDto:
        """Get a quote for a multi-leg option strategy. Async.

        Args:
            request: StrategyQuoteRequest describing the base symbol and legs.
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            StrategyQuoteDto with the strategy price, bid/ask, and per-leg quotes
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.post(
            f"/userapigateway/option-details/{account_id}/strategy-details/quote",
            json_data=request.model_dump(by_alias=True, exclude_none=True),
        )
        return StrategyQuoteDto(**response)

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

    async def preflight_short_order(
        self,
        symbol: str,
        quantity: Decimal,
        *,
        order_type: OrderType = OrderType.MARKET,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        limit_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        equity_market_session: Optional[EquityMarketSession] = None,
        validate_order: Optional[bool] = None,
        account_id: Optional[str] = None,
    ) -> PreflightResponse:
        """Preflight a quantity-based equity short-sale order. Async."""
        request = _build_short_preflight_request(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            limit_price=limit_price,
            stop_price=stop_price,
            equity_market_session=equity_market_session,
            validate_order=validate_order,
        )
        return await self.perform_preflight_calculation(request, account_id)

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

    async def preflight_call_credit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        validate_order: Optional[bool] = None,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Preflight a Bear Call Spread (CALL credit spread). Async.

        See :meth:`PublicApiClient.preflight_call_credit_spread` for full
        argument and behaviour documentation.
        """
        request = _build_two_leg_spread_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.CALL_CREDIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            validate_order=validate_order,
        )
        return await self.perform_multi_leg_preflight_calculation(request, account_id)

    async def preflight_call_debit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        validate_order: Optional[bool] = None,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Preflight a Bull Call Spread (CALL debit spread). Async.

        See :meth:`PublicApiClient.preflight_call_debit_spread` for full
        argument and behaviour documentation.
        """
        request = _build_two_leg_spread_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.CALL_DEBIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            validate_order=validate_order,
        )
        return await self.perform_multi_leg_preflight_calculation(request, account_id)

    async def preflight_put_credit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        validate_order: Optional[bool] = None,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Preflight a Bull Put Spread (PUT credit spread). Async.

        See :meth:`PublicApiClient.preflight_put_credit_spread` for full
        argument and behaviour documentation.
        """
        request = _build_two_leg_spread_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.PUT_CREDIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            validate_order=validate_order,
        )
        return await self.perform_multi_leg_preflight_calculation(request, account_id)

    async def preflight_put_debit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        validate_order: Optional[bool] = None,
        account_id: Optional[str] = None,
    ) -> PreflightMultiLegResponse:
        """Preflight a Bear Put Spread (PUT debit spread). Async.

        See :meth:`PublicApiClient.preflight_put_debit_spread` for full
        argument and behaviour documentation.
        """
        request = _build_two_leg_spread_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.PUT_DEBIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            validate_order=validate_order,
        )
        return await self.perform_multi_leg_preflight_calculation(request, account_id)

    async def place_call_credit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        order_id: Optional[str] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a Bear Call Spread (CALL credit spread). Async."""
        request = _build_two_leg_spread_order_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.CALL_CREDIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            order_id=order_id,
        )
        return await self.place_multileg_order(request, account_id)

    async def place_call_debit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        order_id: Optional[str] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a Bull Call Spread (CALL debit spread). Async."""
        request = _build_two_leg_spread_order_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.CALL_DEBIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            order_id=order_id,
        )
        return await self.place_multileg_order(request, account_id)

    async def place_put_credit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        order_id: Optional[str] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a Bull Put Spread (PUT credit spread). Async."""
        request = _build_two_leg_spread_order_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.PUT_CREDIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            order_id=order_id,
        )
        return await self.place_multileg_order(request, account_id)

    async def place_put_debit_spread(
        self,
        sell_contract_osi: str,
        buy_contract_osi: str,
        quantity: int,
        limit_price: Decimal,
        *,
        order_id: Optional[str] = None,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a Bear Put Spread (PUT debit spread). Async."""
        request = _build_two_leg_spread_order_request(
            sell_contract_osi=sell_contract_osi,
            buy_contract_osi=buy_contract_osi,
            kind=_SpreadKind.PUT_DEBIT,
            quantity=quantity,
            limit_price=limit_price,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            order_id=order_id,
        )
        return await self.place_multileg_order(request, account_id)

    async def place_short_order(
        self,
        symbol: str,
        quantity: Decimal,
        *,
        order_id: Optional[str] = None,
        order_type: OrderType = OrderType.MARKET,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        limit_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        equity_market_session: Optional[EquityMarketSession] = None,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Place a quantity-based equity short-sale order. Async."""
        request = _build_short_order_request(
            symbol=symbol,
            quantity=quantity,
            order_type=order_type,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            limit_price=limit_price,
            stop_price=stop_price,
            equity_market_session=equity_market_session,
            order_id=order_id,
        )
        return await self.place_order(request, account_id)

    async def flatten_and_go_short(
        self,
        symbol: str,
        short_quantity: Decimal,
        *,
        order_id: Optional[str] = None,
        flatten_order_id: Optional[str] = None,
        order_type: OrderType = OrderType.MARKET,
        time_in_force: TimeInForce = TimeInForce.DAY,
        expiration_time: Optional[datetime] = None,
        limit_price: Optional[Decimal] = None,
        stop_price: Optional[Decimal] = None,
        equity_market_session: Optional[EquityMarketSession] = None,
        flatten_timeout: Optional[float] = 60.0,
        polling_interval: float = 1.0,
        account_id: Optional[str] = None,
    ) -> AsyncFlattenAndShortResult:
        """Flatten an existing long equity position, then place a short order.

        Experimental: use with caution. This is a two-order workflow, not an
        atomic exchange operation, and market conditions may change between
        the flatten fill and the short entry.
        """
        account_id = self._get_account_id(account_id)
        normalized_symbol = symbol.strip().upper()

        portfolio = await self.get_portfolio(account_id=account_id)
        initial_quantity = _get_equity_position_quantity(
            portfolio, normalized_symbol
        )

        flatten_order: Optional[AsyncNewOrder] = None
        flatten_filled_order: Optional[Order] = None

        if initial_quantity > 0:
            flatten_request = _build_flatten_long_order_request(
                symbol=normalized_symbol,
                quantity=initial_quantity,
                equity_market_session=equity_market_session,
                order_id=flatten_order_id,
            )
            flatten_order = await self.place_order(
                flatten_request, account_id=account_id
            )
            flatten_filled_order = await flatten_order.wait_for_fill(
                timeout=flatten_timeout,
                polling_interval=polling_interval,
            )

            refreshed_portfolio = await self.get_portfolio(account_id=account_id)
            remaining_quantity = _get_equity_position_quantity(
                refreshed_portfolio, normalized_symbol
            )
            if remaining_quantity > 0:
                raise RuntimeError(
                    f"Long position in {normalized_symbol} remains after flatten "
                    f"order {flatten_order.order_id}: quantity={remaining_quantity}. "
                    "Short order was not placed."
                )

        short_order = await self.place_short_order(
            symbol=normalized_symbol,
            quantity=short_quantity,
            order_id=order_id,
            order_type=order_type,
            time_in_force=time_in_force,
            expiration_time=expiration_time,
            limit_price=limit_price,
            stop_price=stop_price,
            equity_market_session=equity_market_session,
            account_id=account_id,
        )

        return AsyncFlattenAndShortResult(
            initial_position_quantity=initial_quantity,
            flatten_order=flatten_order,
            flatten_filled_order=flatten_filled_order,
            short_order=short_order,
        )

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
        order_response = OrderResult(**response)
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
        order_result = OrderResult(**response)
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

    async def cancel_and_replace_order(
        self,
        request: CancelAndReplaceRequest,
        account_id: Optional[str] = None,
    ) -> AsyncNewOrder:
        """Cancel an existing order and replace it with a new one atomically.

        Args:
            request: CancelAndReplaceRequest with the existing order ID, a unique
                request ID, and the new order parameters.
            account_id: Account ID (optional when default_account_number is set)

        Returns:
            AsyncNewOrder for tracking the replacement order
        """
        account_id = self._get_account_id(account_id)
        await self.auth_manager.refresh_token_if_needed()
        response = await self.api_client.put(
            f"/userapigateway/trading/{account_id}/order",
            json_data=request.model_dump(by_alias=True, exclude_none=True),
        )
        order_response = OrderResult(**response)
        return AsyncNewOrder(
            order_id=order_response.order_id,
            account_id=account_id,
            client=self,
            subscription_manager=self._order_subscription_manager,
        )
