from datetime import datetime
from decimal import Decimal
from typing import List, Optional

from .api_client import ApiClient
from .auth_config import AuthConfig
from .auth_manager import AuthManager
from .models import (
    AccountsResponse,
    BarAggregation,
    BarPeriod,
    BarsResponse,
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
    NewOrder,
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
    TimeInForce,
)
from .order_subscription_manager import OrderSubscriptionManager
from .price_stream import PriceStream
from .short_order import (
    FlattenAndShortResult,
    _build_flatten_long_order_request,
    _build_short_order_request,
    _build_short_preflight_request,
    _get_equity_position_quantity,
)
from .strategy_preflight import (
    StrategyPreflight,
    _SpreadKind,
    _build_two_leg_spread_order_request,
    _build_two_leg_spread_request,
)
from .subscription_manager import PriceSubscriptionManager

PROD_BASE_URL = "https://api.public.com"

_BAR_INSTRUMENT_TYPES = frozenset(
    {
        InstrumentType.EQUITY,
        InstrumentType.CRYPTO,
        InstrumentType.OPTION,
        InstrumentType.INDEX,
    }
)


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

        self.strategy_preflight = StrategyPreflight(
            preflight_func=self.perform_multi_leg_preflight_calculation
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

    def get_bars(
        self,
        symbol: str,
        period: BarPeriod,
        *,
        instrument_type: InstrumentType = InstrumentType.EQUITY,
        aggregation: Optional[BarAggregation] = None,
        purchase_date: Optional[str] = None,
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

        Returns:
            BarsResponse with pre-market, regular-market, and after-hours bars.
        """
        if instrument_type not in _BAR_INSTRUMENT_TYPES:
            raise ValueError(
                f"{instrument_type} is not supported for historic bars; "
                f"expected one of EQUITY, CRYPTO, OPTION, INDEX"
            )
        self.auth_manager.refresh_token_if_needed()
        path = (
            f"/userapigateway/historicdata/{instrument_type.value}"
            f"/{symbol}/{period.value}"
        )
        if aggregation is not None:
            path += f"/{aggregation.value}"
        params = {"purchaseDate": purchase_date} if purchase_date else None
        response = self.api_client.get(path, params=params)
        return BarsResponse(**response)

    def get_option_greeks(
        self,
        osi_symbols: List[str],
        account_id: Optional[str] = None,
    ) -> GreeksResponse:
        """
        Get option greeks for multiple option symbols (OSI-normalized format)

        Args:
            osi_symbols: List of OSI-normalized option symbols
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            GreeksResponse containing greeks for each requested symbol
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.get(
            f"/userapigateway/option-details/{account_id}/greeks",
            params={"osiSymbols": osi_symbols}
        )
        return GreeksResponse(**response)

    def get_option_greek(
        self,
        osi_symbol: str,
        account_id: Optional[str] = None,
    ) -> OptionGreeksResponse:
        """
        Get option greeks for a single option symbol (OSI-normalized format)

        Args:
            osi_symbol: OSI-normalized option symbol
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            OptionGreeks for the requested symbol
        """
        greeks_response = self.get_option_greeks(
            osi_symbols=[osi_symbol],
            account_id=account_id
        )
        if not greeks_response.greeks:
            raise ValueError(f"No greeks found for symbol: {osi_symbol}")
        return greeks_response.greeks[0]

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

    def preflight_short_order(
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
        """Preflight a quantity-based equity short-sale order.

        The API represents short-sale intent as ``SELL`` plus
        ``openCloseIndicator=OPEN``. This helper always sends that intent and
        does not expose notional ``amount`` orders.
        """
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
        return self.perform_preflight_calculation(request, account_id)

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

    def preflight_call_credit_spread(
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
        """Preflight a Bear Call Spread (CALL credit spread).

        Sells a lower-strike call and buys a higher-strike call as protection.
        Profits if the underlying stays *below* the sell strike at expiry. Net
        cash flow at entry is a credit.

        Args:
            sell_contract_osi: OSI symbol of the lower-strike CALL to sell
                (e.g. ``"AAPL251219C00190000"``).
            buy_contract_osi: OSI symbol of the higher-strike CALL to buy.
            quantity: Number of spread contracts.
            limit_price: Minimum net credit to accept, as a positive value
                (e.g. ``Decimal("2.50")`` for a $2.50 per-share credit). The
                SDK negates this for the API automatically.
            time_in_force: ``DAY`` (default) or ``GTD``.
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            validate_order: If ``False``, runs a hypothetical "what-if"
                preflight that doesn't check the order against current account
                state. Server defaults to ``True``.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Returns:
            ``PreflightMultiLegResponse`` with estimated credit, commission,
            and buying-power impact.

        Raises:
            ValueError: If either OSI fails to parse, the legs don't share an
                underlying or expiration, either leg is not a CALL, or
                ``sell_strike >= buy_strike``.
            ValidationError: If the API rejects the request (HTTP 400).
            APIError: For any other API error.
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
        return self.perform_multi_leg_preflight_calculation(request, account_id)

    def preflight_call_debit_spread(
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
        """Preflight a Bull Call Spread (CALL debit spread).

        Buys a lower-strike call and sells a higher-strike call to offset
        the cost. Profits if the underlying rises *above* the sell strike
        at expiry. Net cash flow at entry is a debit.

        Args:
            sell_contract_osi: OSI symbol of the higher-strike CALL to sell.
            buy_contract_osi: OSI symbol of the lower-strike CALL to buy.
            quantity: Number of spread contracts.
            limit_price: Maximum net debit to pay, as a positive value
                (e.g. ``Decimal("3.00")`` for a $3.00 per-share debit).
            time_in_force: ``DAY`` (default) or ``GTD``.
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            validate_order: If ``False``, skips account-state validation.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Returns:
            ``PreflightMultiLegResponse`` with estimated cost and impact.

        Raises:
            ValueError: If either OSI fails to parse, the legs don't share an
                underlying or expiration, either leg is not a CALL, or
                ``buy_strike >= sell_strike``.
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
        return self.perform_multi_leg_preflight_calculation(request, account_id)

    def preflight_put_credit_spread(
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
        """Preflight a Bull Put Spread (PUT credit spread).

        Sells a higher-strike put and buys a lower-strike put as protection.
        Profits if the underlying stays *above* the sell strike at expiry.
        Net cash flow at entry is a credit.

        Args:
            sell_contract_osi: OSI symbol of the higher-strike PUT to sell.
            buy_contract_osi: OSI symbol of the lower-strike PUT to buy.
            quantity: Number of spread contracts.
            limit_price: Minimum net credit to accept, as a positive value.
                The SDK negates this for the API automatically.
            time_in_force: ``DAY`` (default) or ``GTD``.
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            validate_order: If ``False``, skips account-state validation.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Raises:
            ValueError: If either OSI fails to parse, the legs don't share an
                underlying or expiration, either leg is not a PUT, or
                ``sell_strike <= buy_strike``.
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
        return self.perform_multi_leg_preflight_calculation(request, account_id)

    def preflight_put_debit_spread(
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
        """Preflight a Bear Put Spread (PUT debit spread).

        Buys a higher-strike put and sells a lower-strike put to offset
        the cost. Profits if the underlying falls *below* the sell strike
        at expiry. Net cash flow at entry is a debit.

        Args:
            sell_contract_osi: OSI symbol of the lower-strike PUT to sell.
            buy_contract_osi: OSI symbol of the higher-strike PUT to buy.
            quantity: Number of spread contracts.
            limit_price: Maximum net debit to pay, as a positive value.
            time_in_force: ``DAY`` (default) or ``GTD``.
            expiration_time: Required when ``time_in_force`` is ``GTD``.
            validate_order: If ``False``, skips account-state validation.
            account_id: Account ID (optional when ``default_account_number``
                is set on the client).

        Raises:
            ValueError: If either OSI fails to parse, the legs don't share an
                underlying or expiration, either leg is not a PUT, or
                ``buy_strike <= sell_strike``.
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
        return self.perform_multi_leg_preflight_calculation(request, account_id)

    def place_call_credit_spread(
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
    ) -> NewOrder:
        """Place a Bear Call Spread (CALL credit spread).

        This submits a live multi-leg order. Pass ``order_id`` to control the
        idempotency key; otherwise the SDK generates a UUIDv4 automatically.
        ``limit_price`` is the minimum credit to accept as a positive value.
        """
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
        return self.place_multileg_order(request, account_id)

    def place_call_debit_spread(
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
    ) -> NewOrder:
        """Place a Bull Call Spread (CALL debit spread).

        This submits a live multi-leg order. ``limit_price`` is the maximum
        debit to pay as a positive value.
        """
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
        return self.place_multileg_order(request, account_id)

    def place_put_credit_spread(
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
    ) -> NewOrder:
        """Place a Bull Put Spread (PUT credit spread).

        This submits a live multi-leg order. ``limit_price`` is the minimum
        credit to accept as a positive value.
        """
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
        return self.place_multileg_order(request, account_id)

    def place_put_debit_spread(
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
    ) -> NewOrder:
        """Place a Bear Put Spread (PUT debit spread).

        This submits a live multi-leg order. ``limit_price`` is the maximum
        debit to pay as a positive value.
        """
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
        return self.place_multileg_order(request, account_id)

    def place_short_order(
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
    ) -> NewOrder:
        """Place a quantity-based equity short-sale order.

        The API represents short-sale intent as ``SELL`` plus
        ``openCloseIndicator=OPEN``. This helper always sends that intent and
        does not expose notional ``amount`` orders. Pass ``order_id`` to
        control the idempotency key; otherwise the SDK generates a UUIDv4.
        """
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
        return self.place_order(request, account_id)

    def flatten_and_go_short(
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
    ) -> FlattenAndShortResult:
        """Flatten an existing long equity position, then place a short order.

        Experimental: use with caution. This is a two-order workflow, not an
        atomic exchange operation, and market conditions may change between
        the flatten fill and the short entry.

        If the account is long ``symbol``, this places a market SELL/CLOSE
        order for the long quantity, waits for it to fill, re-fetches the
        portfolio to confirm no long position remains, and only then places
        the short-sale order via :meth:`place_short_order`.

        If the account is already flat or short, no flatten order is placed and
        the short order is submitted immediately.
        """
        account_id = self.__get_account_id(account_id)
        normalized_symbol = symbol.strip().upper()

        portfolio = self.get_portfolio(account_id=account_id)
        initial_quantity = _get_equity_position_quantity(
            portfolio, normalized_symbol
        )

        flatten_order: Optional[NewOrder] = None
        flatten_filled_order: Optional[Order] = None

        if initial_quantity > 0:
            flatten_request = _build_flatten_long_order_request(
                symbol=normalized_symbol,
                quantity=initial_quantity,
                equity_market_session=equity_market_session,
                order_id=flatten_order_id,
            )
            flatten_order = self.place_order(flatten_request, account_id=account_id)
            flatten_filled_order = flatten_order.wait_for_fill(
                timeout=flatten_timeout,
                polling_interval=polling_interval,
            )

            refreshed_portfolio = self.get_portfolio(account_id=account_id)
            remaining_quantity = _get_equity_position_quantity(
                refreshed_portfolio, normalized_symbol
            )
            if remaining_quantity > 0:
                raise RuntimeError(
                    f"Long position in {normalized_symbol} remains after flatten "
                    f"order {flatten_order.order_id}: quantity={remaining_quantity}. "
                    "Short order was not placed."
                )

        short_order = self.place_short_order(
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

        return FlattenAndShortResult(
            initial_position_quantity=initial_quantity,
            flatten_order=flatten_order,
            flatten_filled_order=flatten_filled_order,
            short_order=short_order,
        )

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
        order_response = OrderResult(**response)

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
        order_result = OrderResult(**response)

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

    def cancel_and_replace_order(
        self,
        request: CancelAndReplaceRequest,
        account_id: Optional[str] = None,
    ) -> NewOrder:
        """Cancel an existing order and replace it with a new one atomically.

        Args:
            request: CancelAndReplaceRequest with the existing order ID, a unique
                request ID, and the new order parameters.
            account_id: Account ID (optional if `default_account_number` is set)

        Returns:
            NewOrder object for tracking the replacement order
        """
        account_id = self.__get_account_id(account_id)
        self.auth_manager.refresh_token_if_needed()
        response = self.api_client.put(
            f"/userapigateway/trading/{account_id}/order",
            json_data=request.model_dump(by_alias=True, exclude_none=True),
        )
        order_response = OrderResult(**response)
        return NewOrder(
            order_id=order_response.order_id,
            account_id=account_id,
            client=self,
            subscription_manager=self._order_subscription_manager,
        )
