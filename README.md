[![Public API Python SDK](banner.png)](https://public.com/api)

![Version](https://img.shields.io/badge/version-0.1.15-brightgreen?style=flat-square)
![Python](https://img.shields.io/badge/python-3.9%2B-blue?style=flat-square)
![License](https://img.shields.io/badge/license-Apache%202.0-green?style=flat-square)

# Public API Python SDK

A Python SDK for interacting with the Public Trading API, providing a simple and intuitive interface for trading operations, market data retrieval, and account management.

## Installation

### From PyPI

```bash
$ pip install publicdotcom-py
```

### Run locally

```bash
$ python3 -m venv .venv
$ source .venv/bin/activate
$ pip install .

$ pip install -e .
$ pip install -e ".[dev]"  # for dev dependencies

$ # run example
$ python example.py
```

### Run tests

```bash
$ pytest
```

### Run examples

Inside of the examples folder are multiple python scripts showcasing specific ways to use the SDK. To run these Python files, first add your `API_SECRET_KEY` and `DEFAULT_ACCOUNT_NUMBER` to the `.env.example` file and change the filename to `.env`.

## Quick Start

```python
from public_api_sdk import PublicApiClient, PublicApiClientConfiguration, ApiKeyAuthConfig

# Initialize the client
client = PublicApiClient(
    ApiKeyAuthConfig(api_secret_key="INSERT_API_SECRET_KEY"),
    config=PublicApiClientConfiguration(
        default_account_number="INSERT_ACCOUNT_NUMBER"
    )
)

# Get accounts
accounts = client.get_accounts()

# Get a quote
from public_api_sdk import OrderInstrument, InstrumentType

quotes = client.get_quotes([
    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
])
```

## Async Quick Start

The SDK ships an `AsyncPublicApiClient` for use in `async`/`await` code. It uses [`httpx`](https://www.python-httpx.org/) as the HTTP transport, so no background threads are needed.

```python
import asyncio
from public_api_sdk import (
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    ApiKeyAuthConfig,
    OrderInstrument,
    InstrumentType,
)

async def main():
    async with AsyncPublicApiClient(
        auth_config=ApiKeyAuthConfig(api_secret_key="INSERT_API_SECRET_KEY"),
        config=AsyncPublicApiClientConfiguration(
            default_account_number="INSERT_ACCOUNT_NUMBER"
        ),
    ) as client:
        accounts = await client.get_accounts()

        quotes = await client.get_quotes([
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
        ])
        for q in quotes:
            print(f"{q.instrument.symbol}: ${q.last}")

asyncio.run(main())
```

The `async with` block automatically cancels any active price subscriptions and closes the HTTP connection when the block exits — no `try/finally` or manual `close()` call required.

## API Reference

### Client Configuration

The `PublicApiClient` is initialized with an API secret key create in your settings page at public.com and optional configuration. The SDK client will handle generation and refresh of access tokens:

```python
from public_api_sdk import PublicApiClient, PublicApiClientConfiguration
from public_api_sdk.auth_config import ApiKeyAuthConfig

config = PublicApiClientConfiguration(
    default_account_number="INSERT_ACCOUNT_NUMBER",  # Optional default account
)

client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key="INSERT_API_SECRET_KEY"),
        config=config
    )
```

#### Access Token Validity

`ApiKeyAuthConfig` accepts an optional `validity_minutes` argument (default: `15`) that controls how long each minted access token stays valid on the server. Valid range is **5 to 1440 minutes (24 hours)**; values outside this range raise `ValueError`.

```python
# Long-lived session for a batch job — refresh every ~1 hour
client = PublicApiClient(
    ApiKeyAuthConfig(
        api_secret_key="INSERT_API_SECRET_KEY",
        validity_minutes=60,
    ),
    config=config,
)
```

The SDK automatically refreshes the token ahead of its expiry (5 minutes of slack), so you don't need to manage refresh yourself — longer `validity_minutes` just means fewer token-mint round trips.

#### Default Account Number

The `default_account_number` configuration option simplifies API calls by eliminating the need to specify `account_id` in every method call. When set, any method that accepts an optional `account_id` parameter will automatically use the default account number if no account ID is explicitly provided.

```python
# With default_account_number configured
from public_api_sdk import OrderInstrument, InstrumentType

config = PublicApiClientConfiguration(
    default_account_number="INSERT_ACCOUNT_NUMBER"
)

client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key="INSERT_API_SECRET_KEY"), 
        config=config
    )

instruments = [
    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY)
]

# No need to specify account_id
portfolio = client.get_portfolio()  # Uses default account number
quotes = client.get_quotes(instruments)   # Uses default account number

# You can still override with a specific account
other_portfolio = client.get_portfolio(account_id="DIFFERENT123")  # Uses "DIFFERENT123"
```

```python
# Without default_account_number
config = PublicApiClientConfiguration()

client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key="INSERT_API_SECRET_KEY"), 
        config=config
    )

# Must specify account_id for each call
portfolio = client.get_portfolio(account_id="INSERT_ACCOUNT_NUMBER")  # Required
quotes = client.get_quotes(instruments, account_id="INSERT_ACCOUNT_NUMBER")  # Required
```

This is particularly useful when working with a single account, as it reduces code repetition and makes the API calls cleaner.

### Account Management

#### Get Accounts

Retrieve all accounts associated with the authenticated user.

```python
accounts_response = client.get_accounts()
for account in accounts_response.accounts:
    print(f"Account ID: {account.account_id}, Type: {account.account_type}")
```

#### Get Portfolio

Get a snapshot of account portfolio including positions, equity, buying power, open orders, and multi-leg option strategies.

```python
portfolio = client.get_portfolio(account_id="YOUR_ACCOUNT_NUMBER")  # account_id optional if default set
print(f"Total equity: {portfolio.equity}")
print(f"Buying power: {portfolio.buying_power}")

# Positions include the strategy IDs they belong to (empty list if not part of any strategy)
for position in portfolio.positions:
    if position.strategy_ids:
        print(f"{position.instrument.symbol} is part of strategies: {position.strategy_ids}")

# Multi-leg option strategies (e.g. spreads). Null if the backend does not support strategies.
if portfolio.strategies:
    for strategy in portfolio.strategies:
        print(f"\n{strategy.display_name} (id={strategy.strategy_id})")
        print(f"  Quantity: {strategy.quantity}, current value: ${strategy.current_value}")
        for leg in strategy.option_legs:
            print(f"  {leg.position_type} {leg.ratio_quantity}x {leg.symbol}")
```

#### Get Account History

Retrieve paginated account history with optional filtering.

```python
from public_api_sdk import HistoryRequest

history = client.get_history(
    HistoryRequest(page_size=10),
    account_id="YOUR_ACCOUNT"
)
```

### Market Data

#### Get Quotes

Retrieve real-time quotes for multiple instruments. Each `Quote` includes the last/bid/ask, volume, open interest, previous close, a one-day change breakdown, and option-specific details (strike, mid price, and greeks) when the instrument is an option.

```python
from public_api_sdk import OrderInstrument, InstrumentType

quotes = client.get_quotes([
    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY)
])

for quote in quotes:
    print(f"{quote.instrument.symbol}: ${quote.last} (prev close ${quote.previous_close})")
    if quote.one_day_change:
        print(f"  1d change: ${quote.one_day_change.change} ({quote.one_day_change.percent_change}%)")
```

For option quotes (either via `get_quotes` on an `OPTION` instrument, or the calls/puts inside `get_option_chain`), `quote.option_details` exposes greeks and mid price:

```python
if quote.option_details:
    print(f"Strike: ${quote.option_details.strike_price}, mid: ${quote.option_details.mid_price}")
    if quote.option_details.greeks:
        g = quote.option_details.greeks
        print(f"  Δ={g.delta} Γ={g.gamma} Θ={g.theta} ν={g.vega} IV={g.implied_volatility}")
```

> All fields on `GreekValues` are optional — the API may omit greeks for illiquid or expired contracts. Always guard with `if quote.option_details.greeks:` before reading individual values.

#### Get Instrument Details

Get detailed information about a specific instrument, including trading permissions, short-selling availability, option price increments, and type-specific details (bond or crypto).

```python
from public_api_sdk import (
    BondInstrumentDetails,
    CryptoInstrumentDetails,
    ShortingAvailability,
)

instrument = client.get_instrument(
    symbol="AAPL",
    instrument_type=InstrumentType.EQUITY
)

print(f"Symbol: {instrument.instrument.symbol}")
print(f"Type: {instrument.instrument.type}")
print(f"Trading: {instrument.trading}")
print(f"Fractional Trading: {instrument.fractional_trading}")
print(f"Option Trading: {instrument.option_trading}")
print(f"Option Spread Trading: {instrument.option_spread_trading}")

# Short-selling — only populated for shortable equities
if instrument.shorting_availability:
    print(f"Shorting: {instrument.shorting_availability.value}")
    if instrument.shorting_availability == ShortingAvailability.HARD_TO_BORROW:
        print(f"  HTB rate: {instrument.hard_to_borrow_percentage_rate}%")

# Option price increments — present for optionable equities
if instrument.option_contract_price_increments:
    inc = instrument.option_contract_price_increments
    print(f"Option increments: below $3 = {inc.increment_below_3}, above $3 = {inc.increment_above_3}")

# Type-specific details (polymorphic on payload_type)
details = instrument.instrument_details
if isinstance(details, CryptoInstrumentDetails):
    print(f"Crypto precision: qty={details.crypto_quantity_precision}, price={details.crypto_price_precision}")
    print(f"Tradable in NY: {details.tradable_in_new_york}")
elif isinstance(details, BondInstrumentDetails):
    print(f"Bond outstanding: {details.has_outstanding}")
```

#### Get All Instruments

Retrieve all available trading instruments with optional filtering.

```python
from public_api_sdk import InstrumentsRequest, InstrumentType, TradingPermission

instruments = client.get_all_instruments(
    InstrumentsRequest(
        type_filter=[InstrumentType.EQUITY],
        trading_filter=[TradingPermission.BUY_AND_SELL],
    )
)
```

### Options Trading

#### Get Historic Bar Data

Fetch OHLCV bar data for any symbol over a standard time period. The response is split into pre-market, regular-market, and after-hours sessions, each containing a list of `Bar` objects.

```python
from public_api_sdk import BarPeriod

bars = client.get_bars("AAPL", BarPeriod.YEAR)

print(f"Total expected bars: {bars.total_expected_bars}")
for bar in bars.regular_market.bars:
    print(f"  {bar.timestamp}  O={bar.open}  H={bar.high}  L={bar.low}  C={bar.close}  V={bar.volume}")
```

Available periods: `DAY`, `WEEK`, `MONTH`, `QUARTER`, `HALF_YEAR`, `YEAR`, `FIVE_YEARS`, `YTD`, `SINCE_PURCHASE`.

##### Aggregation override

Override the bar size by passing an `aggregation`:

```python
from public_api_sdk import BarAggregation

# Today's intraday bars at 5-minute resolution
bars = client.get_bars("AAPL", BarPeriod.DAY, aggregation=BarAggregation.FIVE_MINUTES)

# Past week at 30-minute resolution
bars = client.get_bars("AAPL", BarPeriod.WEEK, aggregation=BarAggregation.THIRTY_MINUTES)
```

Available aggregations: `ONE_MINUTE`, `FIVE_MINUTES`, `TEN_MINUTES`, `FIFTEEN_MINUTES`, `THIRTY_MINUTES`, `ONE_HOUR`, `ONE_DAY`, `ONE_WEEK`, `ONE_MONTH`, `THREE_MONTHS`, `SIX_MONTHS`, `ONE_YEAR`.

##### Instrument type

`get_bars` defaults to `InstrumentType.EQUITY`. Pass `instrument_type` to request bars for crypto, options, or indices:

```python
from public_api_sdk import BarAggregation, BarPeriod, InstrumentType

# Bitcoin year-to-date, hourly bars
bars = client.get_bars(
    "BTC",
    BarPeriod.YTD,
    instrument_type=InstrumentType.CRYPTO,
    aggregation=BarAggregation.ONE_HOUR,
)

# Index bars
bars = client.get_bars("SPX", BarPeriod.YEAR, instrument_type=InstrumentType.INDEX)
```

Supported values: `EQUITY`, `CRYPTO`, `OPTION`, `INDEX`. Any other `InstrumentType` raises `ValueError`.

##### Last regular trading session close

`bars.last_regular_trading_session_close` is a `LastSessionClose` model (or `None`) carrying the prior session's close price and change:

```python
last = bars.last_regular_trading_session_close
if last is not None:
    print(f"Prior close: ${last.close} on {last.close_date}  ({last.percent_change}%)")
```

##### Performance since purchase

Use `BarPeriod.SINCE_PURCHASE` with a `purchase_date` to chart performance from a specific entry point:

```python
bars = client.get_bars(
    "AAPL",
    BarPeriod.SINCE_PURCHASE,
    purchase_date="2024-01-02",  # YYYY-MM-DD
)

if bars.total_gain_loss is not None:
    print(f"Gain/loss since purchase: ${bars.total_gain_loss} ({bars.total_gain_loss_percentage}%)")
```

#### Get Option Expirations

Retrieve available option expiration dates for an underlying instrument.

```python
from public_api_sdk import OptionExpirationsRequest, OrderInstrument, InstrumentType

expirations = client.get_option_expirations(
    OptionExpirationsRequest(
        instrument=OrderInstrument(
            symbol="AAPL", 
            type=InstrumentType.EQUITY
        )
    )
)
print(f"Available expirations: {expirations.expirations}")
```

#### Get Option Chain

Retrieve the option chain for a specific expiration date.

```python
from public_api_sdk import OptionChainRequest, InstrumentType

option_chain = client.get_option_chain(
    OptionChainRequest(
        instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        expiration_date=expirations.expirations[0]
    )
)
```

#### Get Option Greeks

Get Greeks for a single option contract (OSI format). The API may return a symbol without any greeks (e.g. for illiquid contracts), and individual greek fields can be null — always guard before reading them.

```python
greeks = client.get_option_greek(
    osi_symbol="AAPL260116C00270000"
)
if greeks.greeks:
    print(f"Delta: {greeks.greeks.delta}, Gamma: {greeks.greeks.gamma}")
else:
    print("No greeks available for this contract")
```

For multiple option symbols, use `get_option_greeks` (plural):

```python
greeks_response = client.get_option_greeks(
    osi_symbols=["AAPL260116C00270000", "AAPL260116P00270000"]
)
for greek in greeks_response.greeks:
    if greek.greeks:
        print(f"{greek.symbol}: Δ={greek.greeks.delta} Γ={greek.greeks.gamma} IV={greek.greeks.implied_volatility}")
```

### Order Management

#### Market Session Selection

When placing equity orders, you can optionally specify the market session using the `equity_market_session` parameter:

- `EquityMarketSession.CORE` - Trade during regular market hours (9:30 AM - 4:00 PM ET)
- `EquityMarketSession.EXTENDED` - Trade during pre-market (4:00 AM - 9:30 AM ET) and after-hours (4:00 PM - 8:00 PM ET)

```python
from public_api_sdk import EquityMarketSession

# For regular market hours
equity_market_session=EquityMarketSession.CORE

# For extended hours trading
equity_market_session=EquityMarketSession.EXTENDED
```

This parameter is optional and applies to both preflight calculations and order placement for equity instruments.

#### Preflight Calculations

##### Equity Preflight

Calculate estimated costs and impact before placing an equity order.

```python
from public_api_sdk import PreflightRequest, OrderSide, OrderType, TimeInForce, OrderInstrument, InstrumentType
from public_api_sdk import OrderExpirationRequest, EquityMarketSession
from decimal import Decimal

preflight_request = PreflightRequest(
    instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    order_side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
    quantity=10,
    limit_price=Decimal("227.50"),
    equity_market_session=EquityMarketSession.CORE  # Optional: CORE or EXTENDED
)

preflight_response = client.perform_preflight_calculation(preflight_request)
commission = preflight_response.estimated_commission or 0
execution_fee = preflight_response.estimated_execution_fee or 0
print(f"Estimated commission: ${commission:.2f}")
print(f"Estimated execution fee: ${execution_fee:.2f}")
print(f"Order value: ${preflight_response.order_value:.2f}")

# Short-selling diagnostics — populated when the order side is SELL and the
# instrument is a shortable equity.
if preflight_response.short_selling:
    ss = preflight_response.short_selling
    print(f"Shorting: {ss.availability.value}, uptick rule: {ss.uptick_rule.value}")
    if ss.hard_to_borrow_percentage_rate is not None:
        print(f"  HTB rate: {ss.hard_to_borrow_percentage_rate}%")
```

##### Short-Sale Preflight

For quantity-based equity short-sale estimates, use `preflight_short_order()`. The SDK sets the API-required short intent for you: `orderSide=SELL` and `openCloseIndicator=OPEN`. Notional short orders are not supported.

```python
short_preflight = client.preflight_short_order(
    symbol="AAPL",
    quantity=Decimal("10"),
    order_type=OrderType.LIMIT,
    limit_price=Decimal("227.50"),
    equity_market_session=EquityMarketSession.CORE,
)

if short_preflight.short_selling:
    ss = short_preflight.short_selling
    print(f"Shorting: {ss.availability.value}, uptick rule: {ss.uptick_rule.value}")
```

The same helper exists on `AsyncPublicApiClient`; just `await` it.

> Pass `validate_order=False` on the request to run a hypothetical "what-if" calculation that **doesn't** check the order against your current account state (buying power, permissions, etc.). The server defaults to `true`. The same flag is accepted on `PreflightMultiLegRequest`.

```python
hypothetical = client.perform_preflight_calculation(
    PreflightRequest(
        instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=1000,                 # more than account buying power
        limit_price=Decimal("227.50"),
        validate_order=False,          # skip account-state checks
    )
)
```

##### Multi-Leg Preflight

Calculate estimated costs for complex multi-leg option strategies.

```python
preflight_multi = PreflightMultiLegRequest(
    order_type=OrderType.LIMIT,
    expiration=OrderExpirationRequest(
        time_in_force=TimeInForce.GTD,
        expiration_time=datetime(2025, 12, 1, tzinfo=timezone.utc)
    ),
    quantity=1,
    limit_price=Decimal("3.45"),
    legs=[
        OrderLegRequest(
            instrument=LegInstrument(symbol="AAPL251024C00110000", type=LegInstrumentType.OPTION),
            side=OrderSide.SELL,
            open_close_indicator=OpenCloseIndicator.OPEN,
            ratio_quantity=1
        ),
        OrderLegRequest(
            instrument=LegInstrument(symbol="AAPL251024C00120000", type=LegInstrumentType.OPTION),
            side=OrderSide.BUY,
            open_close_indicator=OpenCloseIndicator.OPEN,
            ratio_quantity=1
        )
    ]
)

# Calculate preflight to get strategy details and costs
preflight_result = client.perform_multi_leg_preflight_calculation(preflight_multi)

# Display results
print("\n" + "="*70)
print(f"Strategy: {preflight_result.strategy_name}")
print("="*70)

print(f"\nOrder Details:")
print(f"  Order Type: {preflight_multi.order_type.value}")
print(f"  Quantity: {preflight_multi.quantity}")
print(f"  Limit Price: ${preflight_multi.limit_price}")

print(f"\nLegs:")
for i, leg in enumerate(preflight_multi.legs, 1):
    print(f"  {i}. {leg.side.value} {leg.instrument.symbol}")

cost = float(preflight_result.estimated_cost or 0)
cost_label = "Debit (Cost)" if cost > 0 else "Credit"
print(f"\nCost Analysis:")
print(f"  {cost_label}: ${abs(cost):.2f}")
commission = preflight_result.estimated_commission or 0
bpr = preflight_result.buying_power_requirement or 0
print(f"  Commission: ${commission:.2f}")
print(f"  Buying Power Required: ${bpr:.2f}")

print("\n" + "="*70)
```

##### Vertical Spread Preflight (OSI-direct)

For each of the four common vertical spread strategies the SDK exposes a dedicated preflight method on the client. Pass the OSI symbols of the two contracts, the contract count, and the limit price — the SDK validates that both legs share an underlying and expiration, that the strikes are ordered correctly for the strategy, and signs the limit price for credit vs. debit before sending.

OSI symbols can be obtained directly from `get_option_chain()` (each `OptionContract` has a `symbol` field in OSI format), or built manually. The format is: symbol padded to 6 characters + `YYMMDD` + `C`/`P` + 8-digit strike (3 implied decimal places). For example, AAPL $190 call expiring 2025-12-19 → `AAPL251219C00190000`.

```python
from decimal import Decimal
from public_api_sdk import TimeInForce

# Bear Call Spread — profits if AAPL stays below $190 at expiry.
# limit_price is the minimum credit you'll accept (always positive).
result = client.preflight_call_credit_spread(
    sell_contract_osi="AAPL251219C00190000",
    buy_contract_osi="AAPL251219C00195000",
    quantity=1,
    limit_price=Decimal("2.50"),
)
print(f"Estimated credit: ${abs(result.estimated_cost or 0):.2f}")
print(f"Buying power required: ${result.buying_power_requirement or 0:.2f}")

# Bull Call Spread — profits if AAPL rises above $200 at expiry.
# limit_price is the maximum debit you'll pay (positive).
result = client.preflight_call_debit_spread(
    sell_contract_osi="AAPL251219C00200000",
    buy_contract_osi="AAPL251219C00195000",
    quantity=1,
    limit_price=Decimal("3.00"),
)

# Bull Put Spread — profits if AAPL stays above $185 at expiry.
result = client.preflight_put_credit_spread(
    sell_contract_osi="AAPL251219P00185000",
    buy_contract_osi="AAPL251219P00180000",
    quantity=1,
    limit_price=Decimal("1.20"),
)

# Bear Put Spread — profits if AAPL falls below $185 at expiry.
result = client.preflight_put_debit_spread(
    sell_contract_osi="AAPL251219P00180000",
    buy_contract_osi="AAPL251219P00185000",
    quantity=1,
    limit_price=Decimal("2.10"),
)
```

All four methods accept the same optional kwargs:

- `time_in_force` — `TimeInForce.DAY` (default) or `TimeInForce.GTD`
- `expiration_time` — required when `time_in_force=TimeInForce.GTD`
- `validate_order` — set to `False` for hypothetical "what-if" calculations that don't check buying power / permissions
- `account_id` — overrides `default_account_number`

> **Strike-ordering is validated locally before the network call**, so typos and copy-paste errors are caught immediately:
> - **CALL credit** (Bear): `sell_strike < buy_strike`
> - **CALL debit** (Bull): `buy_strike < sell_strike`
> - **PUT credit** (Bull): `sell_strike > buy_strike`
> - **PUT debit** (Bear): `buy_strike > sell_strike`
>
> The SDK also rejects pairs that don't share the same underlying or expiration date — a `ValueError` is raised before any HTTP request is made.

The same four methods exist on `AsyncPublicApiClient`; just `await` them.

##### Vertical Spread Order Placement (OSI-direct)

The same OSI-direct convenience shape is available for submitting live multi-leg spread orders. These methods build a `MultilegOrderRequest`, validate the legs locally, sign credit/debit limit prices the same way as preflight, and call `place_multileg_order()`.

```python
from decimal import Decimal

# Bear Call Spread — submits a live order.
# order_id is optional; pass one when you want explicit idempotency control.
new_order = client.place_call_credit_spread(
    sell_contract_osi="AAPL251219C00190000",
    buy_contract_osi="AAPL251219C00195000",
    quantity=1,
    limit_price=Decimal("2.50"),
)
print(f"Order placed: {new_order.order_id}")

new_order = client.place_call_debit_spread(
    sell_contract_osi="AAPL251219C00200000",
    buy_contract_osi="AAPL251219C00195000",
    quantity=1,
    limit_price=Decimal("3.00"),
)

new_order = client.place_put_credit_spread(
    sell_contract_osi="AAPL251219P00185000",
    buy_contract_osi="AAPL251219P00180000",
    quantity=1,
    limit_price=Decimal("1.20"),
)

new_order = client.place_put_debit_spread(
    sell_contract_osi="AAPL251219P00180000",
    buy_contract_osi="AAPL251219P00185000",
    quantity=1,
    limit_price=Decimal("2.10"),
)
```

All four placement methods accept the same optional kwargs:

- `order_id` — optional UUID idempotency key; generated automatically if omitted
- `time_in_force` — `TimeInForce.DAY` (default) or `TimeInForce.GTD`
- `expiration_time` — required when `time_in_force=TimeInForce.GTD`
- `account_id` — overrides `default_account_number`

The same four methods exist on `AsyncPublicApiClient`; just `await` them.

##### Strategy Preflight Helpers (strikes-based)

For an alternative interface that takes strikes + symbol instead of pre-built OSI symbols, the SDK provides high-level helpers on `client.strategy_preflight` that build the multi-leg request for you — no OSI symbols or leg wiring required.

**CALL credit spread (Bear Call Spread)** — profits if the underlying stays *below* the sell strike at expiry.

```python
from decimal import Decimal
from public_api_sdk import OptionType, TimeInForce

result = client.strategy_preflight.credit_spread(
    symbol="AAPL",
    option_type=OptionType.CALL,
    expiration_date="2025-12-19",
    sell_strike=Decimal("195"),   # sell_strike < buy_strike for calls
    buy_strike=Decimal("200"),
    quantity=1,
    limit_price=Decimal("1.50"),  # minimum credit to accept (positive value)
)
cost = float(result.estimated_cost or 0)
bpr = result.buying_power_requirement or 0
print(f"Estimated credit: ${abs(cost):.2f}")
print(f"Buying power required: ${bpr:.2f}")
```

**PUT credit spread (Bull Put Spread)** — profits if the underlying stays *above* the sell strike at expiry.

```python
result = client.strategy_preflight.credit_spread(
    symbol="AAPL",
    option_type=OptionType.PUT,
    expiration_date="2025-12-19",
    sell_strike=Decimal("185"),   # sell_strike > buy_strike for puts
    buy_strike=Decimal("180"),
    quantity=1,
    limit_price=Decimal("1.50"),
)
```

**CALL debit spread (Bull Call Spread)** — profits if the underlying rises *above* the sell strike at expiry.

```python
result = client.strategy_preflight.debit_spread(
    symbol="AAPL",
    option_type=OptionType.CALL,
    expiration_date="2025-12-19",
    buy_strike=Decimal("195"),    # buy_strike < sell_strike for calls
    sell_strike=Decimal("200"),
    quantity=1,
    limit_price=Decimal("2.50"),  # maximum debit to pay (positive value)
)
cost = float(result.estimated_cost)
print(f"Estimated debit: ${cost:.2f}")
```

**PUT debit spread (Bear Put Spread)** — profits if the underlying falls *below* the sell strike at expiry.

```python
result = client.strategy_preflight.debit_spread(
    symbol="AAPL",
    option_type=OptionType.PUT,
    expiration_date="2025-12-19",
    buy_strike=Decimal("185"),    # buy_strike > sell_strike for puts
    sell_strike=Decimal("180"),
    quantity=1,
    limit_price=Decimal("2.50"),
)
```

> **Strike ordering rules** are enforced before the network call:
> - CALL credit / PUT debit: `sell_strike < buy_strike` / `buy_strike > sell_strike`
> - PUT credit / CALL debit: `sell_strike > buy_strike` / `buy_strike < sell_strike`
>
> `limit_price` is always a positive value regardless of strategy direction.
> A `ValueError` with a clear message is raised immediately if any constraint is violated.

See `examples/example_strategy_preflight.py` for a complete runnable example that fetches live quotes and expirations to auto-derive strikes.

#### Place Orders

##### Place Single-Leg Order

Submit a single-leg equity or option order.

```python
from public_api_sdk import OrderRequest, OrderInstrument, InstrumentType, EquityMarketSession
import uuid

order_request = OrderRequest(
    order_id=str(uuid.uuid4()),
    instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    order_side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
    quantity=10,
    limit_price=Decimal("227.50"),
    equity_market_session=EquityMarketSession.EXTENDED  # Optional: CORE or EXTENDED
)

order_response = client.place_order(order_request)
print(f"Order placed with ID: {order_response.order_id}")
```

##### Place Short Order

Submit a quantity-based equity short-sale order. The SDK sets the API-required short intent for you: `orderSide=SELL` and `openCloseIndicator=OPEN`. Notional short orders are not supported. Use `preflight_short_order()` first when you want borrow, uptick-rule, and margin diagnostics before sending the live order.

```python
short_order = client.place_short_order(
    symbol="AAPL",
    quantity=Decimal("10"),
    order_type=OrderType.LIMIT,
    limit_price=Decimal("227.50"),
    equity_market_session=EquityMarketSession.CORE,
)

print(f"Short order placed: {short_order.order_id}")
```

Pass `order_id` when you want explicit idempotency control; otherwise the SDK generates a UUIDv4. The same helper exists on `AsyncPublicApiClient`; just `await` it.

##### Flatten and Go Short

> **Experimental:** Use this helper with caution. It sends two separate orders
> and is not an atomic exchange operation. Market conditions may change between
> the flatten fill and the short entry.

If you may already be long a symbol, use `flatten_and_go_short()` to avoid sending one oversized sell order. The helper places a market sell-to-close order for the current long quantity, waits for that flatten order to fill, re-fetches the portfolio to confirm no long position remains, and only then places the short order.

```python
result = client.flatten_and_go_short(
    symbol="AAPL",
    short_quantity=Decimal("200"),
    order_type=OrderType.LIMIT,
    limit_price=Decimal("227.50"),
    flatten_timeout=60,
)

if result.flatten_order:
    print(f"Flattened long position with order: {result.flatten_order.order_id}")
print(f"Short order placed: {result.short_order.order_id}")
```

This is a two-order workflow, not an atomic exchange operation. If the flatten order does not fill before `flatten_timeout`, or if the refreshed portfolio still shows a long position after the fill, the short order is not placed. The same helper exists on `AsyncPublicApiClient`; just `await` it.

##### Place Multi-Leg Order

Submit a multi-leg option strategy order.

```python
from datetime import datetime, timezone
from public_api_sdk import MultilegOrderRequest
import uuid

multileg_order = MultilegOrderRequest(
    order_id=str(uuid.uuid4()),
    quantity=1,
    type=OrderType.LIMIT,
    limit_price=Decimal("3.45"),
    expiration=OrderExpirationRequest(
        time_in_force=TimeInForce.GTD,
        expiration_time=datetime(2025, 10, 31, tzinfo=timezone.utc)
    ),
    legs=[
        OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL251024C00110000",
                type=LegInstrumentType.OPTION
            ),
            side=OrderSide.SELL,
            open_close_indicator=OpenCloseIndicator.OPEN,
            ratio_quantity=1
        ),
        OrderLegRequest(
            instrument=LegInstrument(
                symbol="AAPL251024C00120000",
                type=LegInstrumentType.OPTION
            ),
            side=OrderSide.BUY,
            open_close_indicator=OpenCloseIndicator.OPEN,
            ratio_quantity=1
        )
    ]
)

multileg_response = client.place_multileg_order(multileg_order)
print(f"Multi-leg order placed: {multileg_response.order_id}")
```

#### Get Order Status

Retrieve the status and details of a specific order.

```python
order_details = client.get_order(
    order_id="YOUR_ORDER_ID",
    account_id="YOUR_ACCOUNT"  # optional if default set
)
print(f"Order status: {order_details.status}")
```

#### Cancel Order

Submit an asynchronous request to cancel an order.

```python
client.cancel_order(
    order_id="YOUR_ORDER_ID",
    account_id="YOUR_ACCOUNT"  # optional if default set
)
# Note: Check order status after to confirm cancellation
```

#### Cancel and Replace Order

Atomically cancel an existing open order and submit a replacement with updated parameters in a single API call.

> **Note:** Cancel-and-replace currently supports **crypto (quantity-based) orders** and **options orders** only. Equity order support is coming soon.

```python
from public_api_sdk import CancelAndReplaceRequest
import uuid

replacement = client.cancel_and_replace_order(
    CancelAndReplaceRequest(
        order_id="EXISTING_ORDER_ID",          # order to cancel
        request_id=str(uuid.uuid4()),          # unique idempotency key
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=Decimal("5"),
        limit_price=Decimal("228.00"),
        # stop_price=Decimal("225.00"),        # required for STOP or STOP_LIMIT
    ),
    account_id="YOUR_ACCOUNT"                  # optional if default set
)
print(f"Replacement order ID: {replacement.order_id}")
```

The returned `NewOrder` (or `AsyncNewOrder` for the async client) can be used to track the replacement order's status exactly like a freshly placed order:

```python
# Sync: poll until filled
filled = replacement.wait_for_fill(timeout=60)
print(f"Filled at ${filled.average_price}")

# Sync: get current status
details = replacement.get_status()
print(f"Status: {details.status}")
```


### Price Subscription

#### Basic Usage

```python
from public_api_sdk import (
    PublicApiClient,
    PublicApiClientConfiguration,
    OrderInstrument,
    InstrumentType,
    PriceChange,
    SubscriptionConfig,
)

# initialize client
client = PublicApiClient(
    ApiKeyAuthConfig(api_secret_key="YOUR_KEY"),
    config=PublicApiClientConfiguration(default_account_number="YOUR_ACCOUNT"),
)

# define callback
def on_price_change(price_change: PriceChange):
    print(f"{price_change.instrument.symbol}: "
          f"{price_change.old_quote.last} -> {price_change.new_quote.last}")

instruments = [
    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
]

subscription_id = client.price_stream.subscribe(
    instruments=instruments,
    callback=on_price_change,
    config=SubscriptionConfig(polling_frequency_seconds=2.0)
)

# ...

# unsubscribe
client.price_stream.unsubscribe(subscription_id)
```

#### Async Callbacks

```python
async def async_price_handler(price_change: PriceChange):
    # Async processing
    await process_price_change(price_change)

client.price_stream.subscribe(
    instruments=instruments,
    callback=async_price_handler  # Async callbacks are automatically detected
)
```

#### Subscription Management

```python
# update polling frequency
client.price_stream.set_polling_frequency(subscription_id, 5.0)

# get all active subscriptions
active = client.price_stream.get_active_subscriptions()

# unsubscribe all
client.price_stream.unsubscribe_all()
```

#### Custom Configuration

```python
config = SubscriptionConfig(
    polling_frequency_seconds=1.0,  # poll every second
    retry_on_error=True,            # retry on API errors
    max_retries=5,                  # maximum retry attempts
    exponential_backoff=True        # use exponential backoff for retries
)

subscription_id = client.price_stream.subscribe(
    instruments=instruments,
    callback=on_price_change,
    config=config
)
```




## Async Client

`AsyncPublicApiClient` mirrors every method on the sync `PublicApiClient` — the difference is that all API calls are coroutines that must be `await`ed, and the price subscription API is fully async-native.

### Configuration

```python
from public_api_sdk import (
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    ApiKeyAuthConfig,
)

config = AsyncPublicApiClientConfiguration(
    default_account_number="INSERT_ACCOUNT_NUMBER",  # optional default account
)

client = AsyncPublicApiClient(
    auth_config=ApiKeyAuthConfig(api_secret_key="INSERT_API_SECRET_KEY"),
    config=config,
)
```

> **Token acquisition is lazy.** No network call is made in `__init__`. The first `await`ed API call fetches a token and stores it for subsequent requests.

### Context Manager

The recommended way to use the async client is with `async with`. Resources are released automatically whether the block exits normally or via an exception.

```python
async with AsyncPublicApiClient(auth_config=..., config=...) as client:
    accounts = await client.get_accounts()
    # subscriptions cancelled + HTTP client closed on exit
```

You can also manage the lifecycle manually if needed:

```python
client = AsyncPublicApiClient(auth_config=..., config=...)
try:
    accounts = await client.get_accounts()
finally:
    await client.close()  # cancels subscriptions and closes HTTP connection
```

### Concurrent Requests with asyncio.gather

Because every method is a coroutine, you can fire multiple independent requests simultaneously:

```python
import asyncio

accounts, portfolio, quotes = await asyncio.gather(
    client.get_accounts(),
    client.get_portfolio(),
    client.get_quotes([OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)]),
)
```

### Account & Portfolio

All account and portfolio methods work identically to the sync client — just `await` them.

```python
# Get all accounts
accounts = await client.get_accounts()

# Portfolio snapshot
portfolio = await client.get_portfolio()                        # uses default account
portfolio = await client.get_portfolio(account_id="ACC123")    # explicit account

# Paginated history
from public_api_sdk import HistoryRequest

history = await client.get_history(HistoryRequest(page_size=10))
print(f"Transactions: {len(history.transactions)}")
```

### Market Data

```python
# One-off quotes
quotes = await client.get_quotes([
    OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY),
    OrderInstrument(symbol="NVDA", type=InstrumentType.EQUITY),
])

# Instrument details
instrument = await client.get_instrument("AAPL", InstrumentType.EQUITY)

# All tradeable instruments
from public_api_sdk import InstrumentsRequest, TradingPermission

instruments = await client.get_all_instruments(
    InstrumentsRequest(type_filter=[InstrumentType.EQUITY], trading_filter=[TradingPermission.BUY_AND_SELL])
)
```

#### Historic Bar Data (Async)

`get_bars` is a coroutine on the async client — `await` it directly, or use `asyncio.gather` to fetch multiple symbols concurrently:

```python
from public_api_sdk import BarAggregation, BarPeriod, InstrumentType

# Single symbol (defaults to EQUITY)
bars = await client.get_bars("AAPL", BarPeriod.YEAR)

# With aggregation override
bars = await client.get_bars("AAPL", BarPeriod.DAY, aggregation=BarAggregation.FIVE_MINUTES)

# Crypto / options / indices via instrument_type
btc_bars = await client.get_bars(
    "BTC",
    BarPeriod.YTD,
    instrument_type=InstrumentType.CRYPTO,
    aggregation=BarAggregation.ONE_HOUR,
)

# Multiple symbols concurrently
aapl_bars, msft_bars = await asyncio.gather(
    client.get_bars("AAPL", BarPeriod.YEAR),
    client.get_bars("MSFT", BarPeriod.YEAR),
)
for bar in aapl_bars.regular_market.bars:
    print(f"  {bar.timestamp}  O={bar.open}  C={bar.close}  V={bar.volume}")
```

### Order Placement and Tracking

`place_order` and `place_multileg_order` return an `AsyncNewOrder`, which exposes async helpers for polling and subscribing to status changes.

```python
import uuid
from decimal import Decimal
from public_api_sdk import (
    OrderRequest, OrderInstrument, InstrumentType,
    OrderSide, OrderType, OrderExpirationRequest, TimeInForce,
)

order = await client.place_order(
    OrderRequest(
        order_id=str(uuid.uuid4()),
        instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=Decimal("10"),
        limit_price=Decimal("227.50"),
    )
)
print(f"Placed: {order.order_id}")
```

#### AsyncNewOrder — waiting for a fill

```python
from public_api_sdk import WaitTimeoutError

try:
    # Poll until filled; raises WaitTimeoutError after 60 seconds
    filled = await order.wait_for_fill(timeout=60)
    print(f"Filled at ${filled.average_price}")
except WaitTimeoutError:
    print("Order not filled within 60 seconds")
    await order.cancel()
```

#### AsyncNewOrder — waiting for any terminal status

```python
# FILLED, CANCELLED, REJECTED, EXPIRED, or REPLACED
result = await order.wait_for_terminal_status(timeout=120)
print(f"Final status: {result.status}")
```

#### AsyncNewOrder — status update subscriptions

```python
async def on_order_update(update):
    print(f"{update.old_status} -> {update.new_status}")

await order.subscribe_updates(on_order_update)

# ... later
await order.unsubscribe()
```

#### Get and Cancel Orders

```python
# Get current status
order_details = await client.get_order(order_id="ORDER-ID")
print(f"Status: {order_details.status}")

# Cancel
await client.cancel_order(order_id="ORDER-ID")
```

#### Cancel and Replace Order (Async)

Atomically cancel an existing open order and submit a replacement.

> **Note:** Cancel-and-replace currently supports **crypto (quantity-based) orders** and **options orders** only. Equity order support is coming soon.

```python
from public_api_sdk import CancelAndReplaceRequest
import uuid

replacement = await client.cancel_and_replace_order(
    CancelAndReplaceRequest(
        order_id="EXISTING_ORDER_ID",
        request_id=str(uuid.uuid4()),
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=Decimal("5"),
        limit_price=Decimal("228.00"),
    )
)
print(f"Replacement order ID: {replacement.order_id}")

# Track the replacement the same way as any placed order
filled = await replacement.wait_for_fill(timeout=60)
print(f"Filled at ${filled.average_price}")
```

### Async Price Subscriptions

The async client exposes `client.price_stream`, an `AsyncPriceStream` instance backed by per-subscription `asyncio.Task`s. No background threads are used.

#### Subscribe

```python
from public_api_sdk import PriceChange, SubscriptionConfig

async def on_price_change(change: PriceChange) -> None:
    symbol = change.instrument.symbol
    print(f"{symbol}: ${change.new_quote.last}  (bid=${change.new_quote.bid}, ask=${change.new_quote.ask})")

sub_id = await client.price_stream.subscribe(
    instruments=[
        OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    ],
    callback=on_price_change,
    config=SubscriptionConfig(polling_frequency_seconds=1.0),
)
```

Callbacks can be sync (`def`) or async (`async def`) — both are detected automatically.

#### Independent subscriptions per symbol

Create one subscription per instrument to control each one independently:

```python
msft_sub = await client.price_stream.subscribe(
    instruments=[OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY)],
    callback=on_msft_change,
    config=SubscriptionConfig(polling_frequency_seconds=1.0),
)

nvda_sub = await client.price_stream.subscribe(
    instruments=[OrderInstrument(symbol="NVDA", type=InstrumentType.EQUITY)],
    callback=on_nvda_change,
    config=SubscriptionConfig(polling_frequency_seconds=1.0),
)
```

#### Pause, Resume, and Retune

```python
# Pause one subscription without cancelling it
client.price_stream.pause(nvda_sub)

await asyncio.sleep(5)

# Resume it
client.price_stream.resume(nvda_sub)

# Slow down polling without re-subscribing (valid range: 0.1 – 60 seconds)
client.price_stream.set_polling_frequency(msft_sub, 3.0)
```

#### Inspect active subscriptions

```python
active_ids = client.price_stream.get_active_subscriptions()

info = client.price_stream.get_subscription_info(msft_sub)
if info:
    print(f"MSFT polling every {info.polling_frequency}s")
```

#### Unsubscribe

```python
# Cancel a single subscription
await client.price_stream.unsubscribe(msft_sub)

# Cancel all at once (also called automatically by the context manager)
await client.price_stream.unsubscribe_all()
```

### Preflight Calculations (Async)

```python
from public_api_sdk import PreflightRequest, OrderSide, OrderType, OrderExpirationRequest, TimeInForce
from decimal import Decimal

preflight = await client.perform_preflight_calculation(
    PreflightRequest(
        instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
        order_side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
        quantity=Decimal("10"),
        limit_price=Decimal("227.50"),
    )
)
commission = preflight.estimated_commission or 0
print(f"Estimated commission: ${commission:.2f}")
print(f"Order value: ${preflight.order_value:.2f}")
```

### Strategy Preflight Helpers (Async)

All four spread helpers are available on the async client with identical parameters — just `await` them.

```python
from decimal import Decimal
from public_api_sdk import OptionType

result = await client.strategy_preflight.credit_spread(
    symbol="AAPL",
    option_type=OptionType.CALL,
    expiration_date="2025-12-19",
    sell_strike=Decimal("195"),
    buy_strike=Decimal("200"),
    quantity=1,
    limit_price=Decimal("1.50"),
)
cost = float(result.estimated_cost)
print(f"Estimated credit: ${abs(cost):.2f}")
```

### Error Handling (Async)

```python
from public_api_sdk.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

async with AsyncPublicApiClient(auth_config=..., config=...) as client:
    try:
        order = await client.place_order(order_request)
        filled = await order.wait_for_fill(timeout=60)
    except ValueError as e:
        # Local validation failed before any network call (e.g. bad strike order)
        print(f"Invalid parameters: {e}")
    except AuthenticationError:
        print("Invalid or expired credentials — regenerate your API key")
    except ValidationError as e:
        # HTTP 400 — invalid symbol, bad strike, insufficient buying power, etc.
        print(f"Request rejected: {e.message}")
        print(f"Details: {e.response_data}")
    except NotFoundError:
        # HTTP 404 — order not indexed yet (async placement) or unknown resource
        print("Resource not found — if this is an order, retry after a moment")
    except RateLimitError as e:
        wait = e.retry_after or 5
        print(f"Rate limited — retry after {wait}s")
    except ServerError:
        print("API server error — retry later")
    except APIError as e:
        # Catch-all for any other API error
        print(f"Unexpected API error ({e.status_code}): {e.message}")
```

The context manager ensures cleanup even when an exception propagates out of the `async with` block.

## Examples

### Complete Trading Workflow

See `example.py` for a complete trading workflow example that demonstrates:
- Getting accounts
- Retrieving quotes
- Performing preflight calculations
- Placing orders
- Checking order status
- Cancel and replace an open order
- Getting portfolio information
- Retrieving account history

### Strategy Preflight Example

See `example_strategy_preflight.py` for a self-contained example that:
- Fetches a live quote to anchor strikes to the current market price
- Resolves the nearest option expiration automatically
- Runs all four spread types (CALL/PUT × credit/debit) back-to-back

### Historic Bar Data Example

See `example_historic_data.py` for a runnable example that demonstrates:
- Fetching a full year of daily bars
- Intraday bars with an aggregation override (5-minute, 30-minute)
- Performance-since-purchase using `BarPeriod.SINCE_PURCHASE`
- Fetching multiple symbols concurrently with the async client

### Options Trading Example

See `example_options.py` for a comprehensive options trading example that shows:
- Getting option expirations
- Retrieving option chains
- Getting option Greeks
- Performing multi-leg preflight calculations
- Placing multi-leg option orders

### Price Subscription (Sync)

See `example_price_subscription.py` for complete examples including:
- Basic subscription usage
- Advanced async callbacks
- Multiple concurrent subscriptions
- Custom price alert system

### Async Client

See `example_async_client.py` for a full async example that demonstrates:
- API-key authentication with the async context manager
- Concurrent account + portfolio fetch with `asyncio.gather`
- One-off quote snapshot before subscribing
- Cancel and replace an open order (commented-out template; crypto/options only)
- Two independent async price subscriptions (one per symbol, 1-second polling)
- Async callbacks with bid-ask spread and percentage-change tracking
- Mid-run pause and resume of an individual subscription
- Dynamic polling-frequency adjustment without re-subscribing
- Subscription-info inspection at runtime
- End-of-run summary stats

## Error Handling

All API errors inherit from `APIError` and carry a `status_code` and `response_data` for full context.

| Exception | HTTP status | Typical cause |
|-----------|-------------|---------------|
| `AuthenticationError` | 401 | Expired or revoked API key / token |
| `ValidationError` | 400 | Invalid symbol, bad strike, wrong price sign, insufficient buying power |
| `NotFoundError` | 404 | Order not yet indexed after async placement, unknown resource |
| `RateLimitError` | 429 | Too many requests — check `retry_after` for backoff duration |
| `ServerError` | 5xx | Transient server error — retry after a short wait |
| `APIError` | any | Base class; catches all of the above |

```python
from public_api_sdk.exceptions import (
    APIError,
    AuthenticationError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)

try:
    result = client.strategy_preflight.credit_spread(
        symbol="AAPL",
        option_type=OptionType.CALL,
        expiration_date="2025-12-19",
        sell_strike=Decimal("195"),
        buy_strike=Decimal("200"),
        quantity=1,
        limit_price=Decimal("1.50"),
    )
except ValueError as e:
    # Local validation failed before any network call
    # e.g. strikes in the wrong order, non-positive limit_price
    print(f"Invalid parameters: {e}")
except AuthenticationError:
    print("Invalid or expired credentials — regenerate your API key")
except ValidationError as e:
    # HTTP 400 from the API — bad symbol, unsupported expiration, etc.
    print(f"Request rejected: {e.message}")
    print(f"Details: {e.response_data}")
except NotFoundError:
    print("Resource not found")
except RateLimitError as e:
    import time
    wait = e.retry_after or 5
    print(f"Rate limited — waiting {wait}s")
    time.sleep(wait)
    # retry ...
except ServerError:
    print("Server error — retry after a moment")
except APIError as e:
    print(f"Unexpected API error ({e.status_code}): {e.message}")
finally:
    client.close()
```

## Important Notes

- Order placement is asynchronous on the exchange side. Always use `get_order()` or `wait_for_fill()` to confirm the final status.
- For accounts with a default account number configured, the `account_id` parameter is optional in most methods.
- Both clients manage token acquisition and refresh automatically — no manual token handling is needed.
- **Sync client:** always call `client.close()` when done to clean up resources.
- **Async client:** prefer `async with AsyncPublicApiClient(...) as client:` — this cancels all subscriptions and closes the HTTP connection automatically. If you manage the lifecycle manually, call `await client.close()`.
