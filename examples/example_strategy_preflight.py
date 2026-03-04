"""Manual test script for strategy preflight helpers.

Demonstrates all four spread types using live market data:
  - CALL credit spread  (Bear Call Spread)
  - PUT  credit spread  (Bull Put Spread)
  - CALL debit spread   (Bull Call Spread)
  - PUT  debit spread   (Bear Put Spread)

The script fetches a live AAPL quote and the nearest option expiration so it
runs end-to-end with no hardcoded dates or strikes.  Override the symbol via
the SYMBOL env variable if desired.

Usage::

    API_SECRET_KEY=<key> DEFAULT_ACCOUNT_NUMBER=<acct> python example_strategy_preflight.py
"""

import math
import os
from decimal import Decimal

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    InstrumentType,
    OptionExpirationsRequest,
    OptionType,
    OrderInstrument,
    PublicApiClient,
    PublicApiClientConfiguration,
    TimeInForce,
)

load_dotenv()


def _round_to_strike(price: float, increment: float = 5.0) -> Decimal:
    """Round a price to the nearest standard strike increment."""
    return Decimal(str(math.floor(price / increment) * increment))


def main() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    symbol = os.environ.get("SYMBOL", "AAPL")

    client = PublicApiClient(
        ApiKeyAuthConfig(api_secret_key=api_secret_key),
        config=PublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    )

    try:
        # ------------------------------------------------------------------ #
        # 1. Fetch a live quote to anchor strikes around the current price    #
        # ------------------------------------------------------------------ #
        print(f"Fetching quote for {symbol}...")
        instrument = OrderInstrument(symbol=symbol, type=InstrumentType.EQUITY)
        quotes = client.get_quotes([instrument])
        last_price = float(quotes[0].last)
        print(f"  Last price: ${last_price:.2f}\n")

        # ------------------------------------------------------------------ #
        # 2. Fetch the nearest available expiration date                      #
        # ------------------------------------------------------------------ #
        print("Fetching option expirations...")
        expirations = client.get_option_expirations(
            OptionExpirationsRequest(instrument=instrument)
        )
        expiration_date = expirations.expirations[0]
        print(f"  Using expiration: {expiration_date}\n")

        # ------------------------------------------------------------------ #
        # 3. Derive strike levels from the current price                      #
        #    ATM-ish → round down to nearest $5 increment                     #
        # ------------------------------------------------------------------ #
        atm = _round_to_strike(last_price)
        otm_call = atm + Decimal("5")   # one strike above ATM
        far_call = atm + Decimal("10")  # two strikes above ATM
        otm_put  = atm - Decimal("5")   # one strike below ATM
        far_put  = atm - Decimal("10")  # two strikes below ATM

        print(
            f"Strike levels → ATM: ${atm}  "
            f"OTM call: ${otm_call}  Far call: ${far_call}  "
            f"OTM put: ${otm_put}  Far put: ${far_put}\n"
        )

        # ------------------------------------------------------------------ #
        # 4. CALL credit spread (Bear Call Spread)                            #
        #    Sell the closer-to-money call, buy the further OTM call          #
        # ------------------------------------------------------------------ #
        print("--- CALL Credit Spread (Bear Call Spread) ---")
        print(f"  Sell ${otm_call} call / Buy ${far_call} call")
        call_credit = client.strategy_preflight.credit_spread(
            symbol=symbol,
            option_type=OptionType.CALL,
            expiration_date=expiration_date,
            sell_strike=otm_call,
            buy_strike=far_call,
            quantity=1,
            limit_price=Decimal("0.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {call_credit}\n")

        # ------------------------------------------------------------------ #
        # 5. PUT credit spread (Bull Put Spread)                              #
        #    Sell the closer-to-money put, buy the further OTM put            #
        # ------------------------------------------------------------------ #
        print("--- PUT Credit Spread (Bull Put Spread) ---")
        print(f"  Sell ${otm_put} put / Buy ${far_put} put")
        put_credit = client.strategy_preflight.credit_spread(
            symbol=symbol,
            option_type=OptionType.PUT,
            expiration_date=expiration_date,
            sell_strike=otm_put,
            buy_strike=far_put,
            quantity=1,
            limit_price=Decimal("0.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {put_credit}\n")

        # ------------------------------------------------------------------ #
        # 6. CALL debit spread (Bull Call Spread)                             #
        #    Buy the closer-to-money call, sell the further OTM call          #
        # ------------------------------------------------------------------ #
        print("--- CALL Debit Spread (Bull Call Spread) ---")
        print(f"  Buy ${otm_call} call / Sell ${far_call} call")
        call_debit = client.strategy_preflight.debit_spread(
            symbol=symbol,
            option_type=OptionType.CALL,
            expiration_date=expiration_date,
            buy_strike=otm_call,
            sell_strike=far_call,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {call_debit}\n")

        # ------------------------------------------------------------------ #
        # 7. PUT debit spread (Bear Put Spread)                               #
        #    Buy the closer-to-money put, sell the further OTM put            #
        # ------------------------------------------------------------------ #
        print("--- PUT Debit Spread (Bear Put Spread) ---")
        print(f"  Buy ${otm_put} put / Sell ${far_put} put")
        put_debit = client.strategy_preflight.debit_spread(
            symbol=symbol,
            option_type=OptionType.PUT,
            expiration_date=expiration_date,
            buy_strike=otm_put,
            sell_strike=far_put,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {put_debit}\n")

    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")

    finally:
        client.close()


if __name__ == "__main__":
    main()
