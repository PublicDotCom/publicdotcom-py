"""Async manual test script for OSI-direct spread preflight helpers.

Demonstrates all four spread types using AsyncPublicApiClient:
  - CALL credit spread  (Bear Call Spread)
  - PUT  credit spread  (Bull Put Spread)
  - CALL debit spread   (Bull Call Spread)
  - PUT  debit spread   (Bear Put Spread)

The script fetches a live AAPL quote and the nearest option expiration so it
runs end-to-end with no hardcoded dates or strikes.  Override the symbol via
the SYMBOL env variable if desired.

OSI format: SYMBOL(padded to 6) + YYMMDD + C|P + STRIKE(8 digits, 3 implied decimals)
Example:    AAPL251219C00190000  → AAPL, 2025-12-19, Call, $190.00

Usage::

    API_SECRET_KEY=<key> DEFAULT_ACCOUNT_NUMBER=<acct> python examples/example_async_strategy_preflight.py
"""

import asyncio
import math
import os
from decimal import Decimal

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    AsyncPublicApiClient,
    AsyncPublicApiClientConfiguration,
    InstrumentType,
    OptionExpirationsRequest,
    OptionType,
    OrderInstrument,
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
    sym = symbol.ljust(6)
    yy, mm, dd = expiration_date[2:4], expiration_date[5:7], expiration_date[8:10]
    cp = "C" if option_type == OptionType.CALL else "P"
    strike_int = int(strike * 1000)
    strike_str = str(strike_int).zfill(8)
    return f"{sym}{yy}{mm}{dd}{cp}{strike_str}"


async def main() -> None:
    api_secret_key = os.environ.get("API_SECRET_KEY")
    if not api_secret_key:
        raise ValueError("API_SECRET_KEY environment variable is required")

    symbol = os.environ.get("SYMBOL", "AAPL")

    async with AsyncPublicApiClient(
        ApiKeyAuthConfig(api_secret_key=api_secret_key),
        config=AsyncPublicApiClientConfiguration(
            default_account_number=os.environ.get("DEFAULT_ACCOUNT_NUMBER"),
        ),
    ) as client:
        # ------------------------------------------------------------------ #
        # 1. Fetch a live quote                                               #
        # ------------------------------------------------------------------ #
        print(f"Fetching quote for {symbol}...")
        instrument = OrderInstrument(symbol=symbol, type=InstrumentType.EQUITY)
        quotes = await client.get_quotes([instrument])
        last_price = float(quotes[0].last)
        print(f"  Last price: ${last_price:.2f}\n")

        # ------------------------------------------------------------------ #
        # 2. Fetch the nearest available expiration date                      #
        # ------------------------------------------------------------------ #
        print("Fetching option expirations...")
        expirations = await client.get_option_expirations(
            OptionExpirationsRequest(instrument=instrument)
        )
        expiration_date = expirations.expirations[0]
        print(f"  Using expiration: {expiration_date}\n")

        # ------------------------------------------------------------------ #
        # 3. Derive strike levels from the current price                      #
        # ------------------------------------------------------------------ #
        atm = _round_to_strike(last_price)
        otm_call = atm + Decimal("5")
        far_call = atm + Decimal("10")
        otm_put  = atm - Decimal("5")
        far_put  = atm - Decimal("10")

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

        # ------------------------------------------------------------------ #
        # 5. Run all four spread preflights concurrently                      #
        # ------------------------------------------------------------------ #
        print("Running all four spread preflights concurrently...\n")
        call_credit, put_credit, call_debit, put_debit = await asyncio.gather(
            client.preflight_call_credit_spread(
                sell_contract_osi=osi_otm_call,
                buy_contract_osi=osi_far_call,
                quantity=1,
                limit_price=Decimal("0.50"),
                time_in_force=TimeInForce.DAY,
            ),
            client.preflight_put_credit_spread(
                sell_contract_osi=osi_otm_put,
                buy_contract_osi=osi_far_put,
                quantity=1,
                limit_price=Decimal("0.50"),
                time_in_force=TimeInForce.DAY,
            ),
            client.preflight_call_debit_spread(
                sell_contract_osi=osi_far_call,
                buy_contract_osi=osi_otm_call,
                quantity=1,
                limit_price=Decimal("2.50"),
                time_in_force=TimeInForce.DAY,
            ),
            client.preflight_put_debit_spread(
                sell_contract_osi=osi_far_put,
                buy_contract_osi=osi_otm_put,
                quantity=1,
                limit_price=Decimal("2.50"),
                time_in_force=TimeInForce.DAY,
            ),
        )

        print("--- CALL Credit Spread (Bear Call Spread) ---")
        print(f"  sell: {osi_otm_call}  /  buy: {osi_far_call}")
        print(f"  Result: {call_credit}\n")

        print("--- PUT Credit Spread (Bull Put Spread) ---")
        print(f"  sell: {osi_otm_put}  /  buy: {osi_far_put}")
        print(f"  Result: {put_credit}\n")

        print("--- CALL Debit Spread (Bull Call Spread) ---")
        print(f"  buy: {osi_otm_call}  /  sell: {osi_far_call}")
        print(f"  Result: {call_debit}\n")

        print("--- PUT Debit Spread (Bear Put Spread) ---")
        print(f"  buy: {osi_otm_put}  /  sell: {osi_far_put}")
        print(f"  Result: {put_debit}\n")


if __name__ == "__main__":
    asyncio.run(main())
