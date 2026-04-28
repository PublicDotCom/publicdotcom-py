"""Manual test script for strategy preflight helpers.

Demonstrates all four spread types using two interfaces:

  1. OSI-direct (new):   client.preflight_call_credit_spread(sell_osi, buy_osi, ...)
  2. Strikes-based (old): client.strategy_preflight.credit_spread(symbol, type, ...)

The script fetches a live AAPL quote and the nearest option expiration so it
runs end-to-end with no hardcoded dates or strikes.  Override the symbol via
the SYMBOL env variable if desired.

OSI format: SYMBOL(padded to 6) + YYMMDD + C|P + STRIKE(8 digits, 3 implied decimals)
Example:    AAPL251219C00190000  → AAPL, 2025-12-19, Call, $190.00

Usage::

    API_SECRET_KEY=<key> DEFAULT_ACCOUNT_NUMBER=<acct> python examples/example_strategy_preflight.py
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


def _make_osi(symbol: str, expiration_date: str, option_type: OptionType, strike: Decimal) -> str:
    """Build an OSI option symbol from its components.

    expiration_date: "YYYY-MM-DD" string
    strike:          strike price as a Decimal (e.g. Decimal("190.00"))
    """
    # Pad symbol to 6 characters
    sym = symbol.ljust(6)
    # YYMMDD from YYYY-MM-DD
    yy, mm, dd = expiration_date[2:4], expiration_date[5:7], expiration_date[8:10]
    # Option type character
    cp = "C" if option_type == OptionType.CALL else "P"
    # Strike: 8 digits, 3 implied decimal places (multiply by 1000, zero-pad)
    strike_int = int(strike * 1000)
    strike_str = str(strike_int).zfill(8)
    return f"{sym}{yy}{mm}{dd}{cp}{strike_str}"


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
        # 4. Build OSI symbols for each leg                                   #
        # ------------------------------------------------------------------ #
        osi_otm_call = _make_osi(symbol, expiration_date, OptionType.CALL, otm_call)
        osi_far_call = _make_osi(symbol, expiration_date, OptionType.CALL, far_call)
        osi_otm_put  = _make_osi(symbol, expiration_date, OptionType.PUT, otm_put)
        osi_far_put  = _make_osi(symbol, expiration_date, OptionType.PUT, far_put)

        print("OSI symbols:")
        print(f"  OTM call: {osi_otm_call}")
        print(f"  Far call: {osi_far_call}")
        print(f"  OTM put:  {osi_otm_put}")
        print(f"  Far put:  {osi_far_put}\n")

        # ==================================================================== #
        #  OSI-DIRECT INTERFACE (new)                                          #
        # ==================================================================== #

        # ------------------------------------------------------------------ #
        # 5a. CALL credit spread — OSI-direct (Bear Call Spread)              #
        #     Sell the closer-to-money call, buy the further OTM call         #
        # ------------------------------------------------------------------ #
        print("=== OSI-Direct Interface ===\n")
        print("--- CALL Credit Spread (Bear Call Spread) ---")
        print(f"  sell: {osi_otm_call}  /  buy: {osi_far_call}")
        call_credit = client.preflight_call_credit_spread(
            sell_contract_osi=osi_otm_call,
            buy_contract_osi=osi_far_call,
            quantity=1,
            limit_price=Decimal("0.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {call_credit}\n")

        # ------------------------------------------------------------------ #
        # 5b. PUT credit spread — OSI-direct (Bull Put Spread)                #
        #     Sell the closer-to-money put, buy the further OTM put           #
        # ------------------------------------------------------------------ #
        print("--- PUT Credit Spread (Bull Put Spread) ---")
        print(f"  sell: {osi_otm_put}  /  buy: {osi_far_put}")
        put_credit = client.preflight_put_credit_spread(
            sell_contract_osi=osi_otm_put,
            buy_contract_osi=osi_far_put,
            quantity=1,
            limit_price=Decimal("0.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {put_credit}\n")

        # ------------------------------------------------------------------ #
        # 5c. CALL debit spread — OSI-direct (Bull Call Spread)               #
        #     Buy the closer-to-money call, sell the further OTM call         #
        # ------------------------------------------------------------------ #
        print("--- CALL Debit Spread (Bull Call Spread) ---")
        print(f"  buy: {osi_otm_call}  /  sell: {osi_far_call}")
        call_debit = client.preflight_call_debit_spread(
            sell_contract_osi=osi_far_call,
            buy_contract_osi=osi_otm_call,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {call_debit}\n")

        # ------------------------------------------------------------------ #
        # 5d. PUT debit spread — OSI-direct (Bear Put Spread)                 #
        #     Buy the closer-to-money put, sell the further OTM put           #
        # ------------------------------------------------------------------ #
        print("--- PUT Debit Spread (Bear Put Spread) ---")
        print(f"  buy: {osi_otm_put}  /  sell: {osi_far_put}")
        put_debit = client.preflight_put_debit_spread(
            sell_contract_osi=osi_far_put,
            buy_contract_osi=osi_otm_put,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {put_debit}\n")

        # ==================================================================== #
        #  STRIKES-BASED INTERFACE (original helper, still supported)          #
        # ==================================================================== #

        print("=== Strikes-Based Interface ===\n")
        print("--- CALL Credit Spread (Bear Call Spread) ---")
        print(f"  Sell ${otm_call} call / Buy ${far_call} call")
        call_credit_sb = client.strategy_preflight.credit_spread(
            symbol=symbol,
            option_type=OptionType.CALL,
            expiration_date=expiration_date,
            sell_strike=otm_call,
            buy_strike=far_call,
            quantity=1,
            limit_price=Decimal("0.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {call_credit_sb}\n")

        print("--- PUT Credit Spread (Bull Put Spread) ---")
        print(f"  Sell ${otm_put} put / Buy ${far_put} put")
        put_credit_sb = client.strategy_preflight.credit_spread(
            symbol=symbol,
            option_type=OptionType.PUT,
            expiration_date=expiration_date,
            sell_strike=otm_put,
            buy_strike=far_put,
            quantity=1,
            limit_price=Decimal("0.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {put_credit_sb}\n")

        print("--- CALL Debit Spread (Bull Call Spread) ---")
        print(f"  Buy ${otm_call} call / Sell ${far_call} call")
        call_debit_sb = client.strategy_preflight.debit_spread(
            symbol=symbol,
            option_type=OptionType.CALL,
            expiration_date=expiration_date,
            buy_strike=otm_call,
            sell_strike=far_call,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {call_debit_sb}\n")

        print("--- PUT Debit Spread (Bear Put Spread) ---")
        print(f"  Buy ${otm_put} put / Sell ${far_put} put")
        put_debit_sb = client.strategy_preflight.debit_spread(
            symbol=symbol,
            option_type=OptionType.PUT,
            expiration_date=expiration_date,
            buy_strike=otm_put,
            sell_strike=far_put,
            quantity=1,
            limit_price=Decimal("2.50"),
            time_in_force=TimeInForce.DAY,
        )
        print(f"  Result: {put_debit_sb}\n")

    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")

    finally:
        client.close()


if __name__ == "__main__":
    main()
