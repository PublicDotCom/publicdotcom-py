import os
from decimal import Decimal
import uuid

from dotenv import load_dotenv

from public_api_sdk import (
    ApiKeyAuthConfig,
    InstrumentType,
    PublicApiClient,
    PublicApiClientConfiguration,
    OrderInstrument,
    OptionExpirationsRequest,
    OptionChainRequest,
    OrderSide,
    OrderType,
    OrderExpirationRequest,
    TimeInForce,
    PreflightMultiLegRequest,
    LegInstrument,
    LegInstrumentType,
    OrderLegRequest,
    MultilegOrderRequest,
    OpenCloseIndicator,
)

# load env variables from .env file
load_dotenv()

# Set DRY_RUN=false to enable live order placement. Defaults to true (safe).
DRY_RUN = os.environ.get("DRY_RUN", "true").lower() != "false"


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
        print("Getting instrument for AAPL...")
        instrument_details = public_api_client.get_instrument(
            symbol="AAPL",
            instrument_type=InstrumentType.EQUITY,
        )
        print(f"Instrument: {instrument_details}\n\n")
        print("Getting quote for AAPL...")
        instrument = OrderInstrument(
            symbol="AAPL",
            type=InstrumentType.EQUITY,
        )
        quotes = public_api_client.get_quotes([instrument])
        print(f"Quote: ${quotes}\n\n")

        print("Getting option expirations for AAPL...")
        expirations = public_api_client.get_option_expirations(
            OptionExpirationsRequest(instrument=instrument)
        )
        print(f"Option expirations: {expirations}\n\n")

        print("Getting option chain for AAPL...")
        option_chain = public_api_client.get_option_chain(
            OptionChainRequest(
                instrument=instrument,
                expiration_date=expirations.expirations[0],
            )
        )
        print(f"Option chain: {option_chain}\n\n")

        # Derive live OSI symbols from the chain so the example always uses valid symbols.
        if len(option_chain.calls) < 2:
            raise ValueError("Not enough call options in chain to run multi-leg example")
        # calls[0] = lower strike, calls[1] = higher strike (bull call spread / debit)
        leg1_symbol = option_chain.calls[0].instrument.symbol
        leg2_symbol = option_chain.calls[1].instrument.symbol
        print(f"Using call symbols from live chain: {leg1_symbol}, {leg2_symbol}\n")

        print("Getting option greeks...")
        option_greeks = public_api_client.get_option_greek(
            osi_symbol=leg1_symbol,
        )
        print(f"Option greeks: {option_greeks}\n\n")

        print("Performing preflight calculation (bull call spread)...")
        preflight_request = PreflightMultiLegRequest(
            order_type=OrderType.LIMIT,
            expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
            quantity=1,
            limit_price=Decimal("0.50"),
            legs=[
                OrderLegRequest(
                    instrument=LegInstrument(
                        symbol=leg1_symbol,
                        type=LegInstrumentType.OPTION,
                    ),
                    side=OrderSide.BUY,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                ),
                OrderLegRequest(
                    instrument=LegInstrument(
                        symbol=leg2_symbol,
                        type=LegInstrumentType.OPTION,
                    ),
                    side=OrderSide.SELL,
                    open_close_indicator=OpenCloseIndicator.OPEN,
                    ratio_quantity=1,
                ),
            ],
        )
        preflight_response = public_api_client.perform_multi_leg_preflight_calculation(
            preflight_request
        )
        print(f"Preflight response: {preflight_response}\n\n")

        if DRY_RUN:
            print(
                "[DRY_RUN] Skipping multi-leg order placement.\n"
                "          Set DRY_RUN=false in your environment to enable live trading.\n"
            )
        else:
            print("Placing a multi-leg order...")
            new_order = public_api_client.place_multileg_order(
                MultilegOrderRequest(
                    order_id=str(uuid.uuid4()),
                    quantity=1,
                    type=OrderType.LIMIT,
                    limit_price=Decimal("0.50"),
                    expiration=OrderExpirationRequest(time_in_force=TimeInForce.DAY),
                    legs=[
                        OrderLegRequest(
                            instrument=LegInstrument(
                                symbol=leg1_symbol,
                                type=LegInstrumentType.OPTION,
                            ),
                            side=OrderSide.BUY,
                            open_close_indicator=OpenCloseIndicator.OPEN,
                            ratio_quantity=1,
                        ),
                        OrderLegRequest(
                            instrument=LegInstrument(
                                symbol=leg2_symbol,
                                type=LegInstrumentType.OPTION,
                            ),
                            side=OrderSide.SELL,
                            open_close_indicator=OpenCloseIndicator.OPEN,
                            ratio_quantity=1,
                        ),
                    ],
                ),
            )
            print(f"Order placed: {new_order.order_id}\n\n")

            # get order status
            order_status = new_order.get_status()
            print(f"Order status: {order_status}\n\n")
    except Exception as e:  # pylint: disable=broad-except
        print(f"Error: {e}")

    finally:
        public_api_client.close()


if __name__ == "__main__":
    main()
