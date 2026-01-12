import os
from decimal import Decimal
import uuid

from dotenv import load_dotenv

from public_api_sdk import (
    AccountType,
    ApiKeyAuthConfig,
    EquityMarketSession,
    HistoryRequest,
    InstrumentsRequest,
    InstrumentType,
    Trading,
    PublicApiClient,
    PublicApiClientConfiguration,
    OrderExpirationRequest,
    OrderInstrument,
    OrderSide,
    OrderType,
    OrderRequest,
    PreflightRequest,
    TimeInForce,
)

# load env variables from .env file
load_dotenv()

def main() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")
    public_api_client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key=api_secret_key),
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )
    try:
        # get accounts
        accounts = public_api_client.get_accounts()
        print(f"Accounts: {accounts.accounts}\n\n")
        brokerage_account = next(
            (
                account
                for account in accounts.accounts
                if account.account_type == AccountType.BROKERAGE
            ),
            None,
        )
        print(f"Brokerage account: {brokerage_account}\n\n")
        account_id = brokerage_account.account_id if brokerage_account else ""

        # get instrument & stock quote
        print("Getting all instruments...")
        instruments = public_api_client.get_all_instruments(
            InstrumentsRequest(
                type_filter=[InstrumentType.EQUITY],
                trading_filter=[Trading.BUY_AND_SELL],
                fractional_trading_filter=None,
                option_trading_filter=None,
                option_spread_trading_filter=None,
            )
        )
        print(f"Instruments: {instruments}\n\n")
        print("Getting instrument for AAPL...")
        instrument = public_api_client.get_instrument(
            symbol="AAPL",
            instrument_type=InstrumentType.EQUITY,
        )
        print(f"Instrument: {instrument}\n\n")
        print("Getting quote for AAPL...")
        quotes = public_api_client.get_quotes(
            [
                OrderInstrument(
                    symbol="AAPL",
                    type=InstrumentType.EQUITY,
                )
            ],
            # account_id is optional if `default_account_number` is set
            # account_id=account_id,
        )
        print(f"AAPL quote: ${quotes}\n\n")

        # perform preflight calculation
        print("Performing preflight calculation...")
        preflight_request = PreflightRequest(
            instrument=OrderInstrument(
                symbol="AAPL",
                type=InstrumentType.EQUITY,
            ),
            order_side=OrderSide.BUY,
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(
                time_in_force=TimeInForce.DAY,
            ),
            quantity=Decimal(1),
            limit_price=Decimal(226.78),
            # Optional: specify market session for extended hours trading
            # equity_market_session=EquityMarketSession.EXTENDED,
        )
        preflight_response = public_api_client.perform_preflight_calculation(
            preflight_request, account_id=account_id
        )
        print(f"Preflight response: {preflight_response}\n\n")

        # place a equity order
        print("Placing a equity order...")
        new_order = public_api_client.place_order(
            OrderRequest(
                order_id=str(uuid.uuid4()),
                instrument=OrderInstrument(
                    symbol="AAPL",
                    type=InstrumentType.EQUITY,
                ),
                order_side=OrderSide.BUY,
                order_type=OrderType.LIMIT,
                expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                quantity=Decimal('1'),
                limit_price=Decimal(227.12),
                # Optional: specify market session (CORE for regular hours, EXTENDED for pre/after market)
                # equity_market_session=EquityMarketSession.CORE,
            ),
        )
        print(f"Order placed: {new_order.order_id}\n\n")

        # get order status and details
        order_response = public_api_client.get_order(
            order_id=new_order.order_id,
            # account_id="YOUR_ACCOUNT"  # optional if default set
        )
        print(f"Order status: {order_response.status}\n\n")
        order_details = order_response
        print(f"Order details: {order_details}\n\n")

        # get portfolio
        print("Getting portfolio...")
        portfolio = public_api_client.get_portfolio()
        print(f"Portfolio: {portfolio}\n\n")

        # get history
        print("Getting history...")
        history = public_api_client.get_history(HistoryRequest(page_size=5))
        print(f"History (first page): {history}\n\n")

    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")

    finally:
        public_api_client.close()


if __name__ == "__main__":
    main()
