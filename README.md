[![Public API Python SDK](banner.png)](https://public.com/api)

![Version](https://img.shields.io/badge/version-0.1.3-brightgreen?style=flat-square)
![Python](https://img.shields.io/badge/python-3.8%2B-blue?style=flat-square)
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
from public_api_sdk import PublicApiClient, PublicApiClientConfiguration
from public_api_sdk.auth_config import ApiKeyAuthConfig

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

Get a snapshot of account portfolio including positions, equity, and buying power.

```python
portfolio = client.get_portfolio(account_id="YOUR_ACCOUNT_NUMBER")  # account_id optional if default set
print(f"Total equity: {portfolio.equity}")
print(f"Buying power: {portfolio.buying_power}")
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

Retrieve real-time quotes for multiple instruments.

```python
from public_api_sdk import OrderInstrument, InstrumentType

quotes = client.get_quotes([
    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY)
])

for quote in quotes:
    print(f"{quote.instrument.symbol}: ${quote.last}")
```

#### Get Instrument Details

Get detailed information about a specific instrument.

```python
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
```

#### Get All Instruments

Retrieve all available trading instruments with optional filtering.

```python
from public_api_sdk import InstrumentsRequest, InstrumentType, Trading

instruments = client.get_all_instruments(
    InstrumentsRequest(
        type_filter=[InstrumentType.EQUITY],
        trading_filter=[Trading.BUY_AND_SELL],
    )
)
```

### Options Trading

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

Get Greeks for a specific option contract (OSI format).

```python
greeks = client.get_option_greeks(
    osi_option_symbol="AAPL260116C00270000"
)
print(f"Delta: {greeks.delta}, Gamma: {greeks.gamma}")
```

### Order Management

#### Preflight Calculations

##### Equity Preflight

Calculate estimated costs and impact before placing an equity order.

```python
from public_api_sdk import PreflightRequest, OrderSide, OrderType, TimeInForce, OrderInstrument, InstrumentType
from public_api_sdk import OrderExpirationRequest
from decimal import Decimal

preflight_request = PreflightRequest(
    instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    order_side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
    quantity=10,
    limit_price=Decimal("227.50")
)

preflight_response = client.perform_preflight_calculation(preflight_request)
print(f"Estimated commission: ${preflight_response.estimated_commission}")
print(f"Order value: ${preflight_response.order_value}")
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

cost = float(preflight_result.estimated_cost)
cost_label = "Debit (Cost)" if cost > 0 else "Credit"
print(f"\nCost Analysis:")
print(f"  {cost_label}: ${abs(cost):.2f}")
print(f"  Commission: ${preflight_result.estimated_commission}")
print(f"  Buying Power Required: ${preflight_result.buying_power_requirement}")

print("\n" + "="*70)
```

#### Place Orders

##### Place Single-Leg Order

Submit a single-leg equity or option order.

```python
from public_api_sdk import OrderRequest, OrderInstrument, InstrumentType
import uuid

order_request = OrderRequest(
    order_id=str(uuid.uuid4()),
    instrument=OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    order_side=OrderSide.BUY,
    order_type=OrderType.LIMIT,
    expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
    quantity=10,
    limit_price=Decimal("227.50")
)

order_response = client.place_order(order_request)
print(f"Order placed with ID: {order_response.order_id}")
```

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
config = PublicApiClientConfiguration(
    default_account_number="YOUR_ACCOUNT"
)
client = PublicApiClient(
    api_secret_key="YOUR_KEY",
    config=config
)

# define callback
def on_price_change(price_change: PriceChange):
    print(f"{price_change.instrument.symbol}: "
          f"{price_change.old_quote.last} -> {price_change.new_quote.last}")

instruments = [
    OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
    OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
]

subscription_id = client.subscribe_to_price_changes(
    instruments=instruments,
    callback=on_price_change,
    config=SubscriptionConfig(polling_frequency_seconds=2.0)
)

# ...

# unsubscribe
client.unsubscribe(subscription_id)
```

#### Async Callbacks

```python
async def async_price_handler(price_change: PriceChange):
    # Async processing
    await process_price_change(price_change)

client.subscribe_to_price_changes(
    instruments=instruments,
    callback=async_price_handler  # Async callbacks are automatically detected
)
```

#### Subscription Management

```python
# update polling frequency
client.set_polling_frequency(subscription_id, 5.0)

# get all active subscriptions
active = client.get_active_subscriptions()

# unsubscribe all
client.unsubscribe_all()
```

#### Custom Configuration

```python
config = SubscriptionConfig(
    polling_frequency_seconds=1.0,  # poll every second
    retry_on_error=True,            # retry on API errors
    max_retries=5,                  # maximum retry attempts
    exponential_backoff=True        # use exponential backoff for retries
)

subscription_id = client.subscribe_to_price_changes(
    instruments=instruments,
    callback=on_price_change,
    config=config
)
```




## Examples

### Complete Trading Workflow

See `example.py` for a complete trading workflow example that demonstrates:
- Getting accounts
- Retrieving quotes
- Performing preflight calculations
- Placing orders
- Checking order status
- Getting portfolio information
- Retrieving account history

### Options Trading Example

See `example_options.py` for a comprehensive options trading example that shows:
- Getting option expirations
- Retrieving option chains
- Getting option Greeks
- Performing multi-leg preflight calculations
- Placing multi-leg option orders

### Price Subscription

See `example_price_subscription.py` for complete examples including:
- Basic subscription usage
- Advanced async callbacks
- Multiple concurrent subscriptions
- Custom price alert system


## Error Handling

The SDK will raise exceptions for API errors. It's recommended to wrap API calls in try-except blocks:

```python
try:
    order_response = client.place_order(order_request)
except Exception as e:
    print(f"Error placing order: {e}")
finally:
    client.close()
```

## Important Notes

- Order placement is asynchronous. Always use `get_order()` to verify order status.
- For accounts with a default account number configured, the `account_id` parameter is optional in most methods.
- The client manages token refresh automatically.
- Always call `client.close()` when done to clean up resources.
