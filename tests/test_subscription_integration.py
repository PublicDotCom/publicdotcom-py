# pylint: disable=protected-access,no-member
# Tests need to access private methods to verify implementation details

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from public_api_sdk import (
    PublicApiClient,
    PublicApiClientConfiguration,
    ApiKeyAuthConfig,
    OrderInstrument,
    InstrumentType,
    Quote,
    QuoteOutcome,
    PriceChange,
    SubscriptionConfig,
)


def test_subscription_integration() -> None:
    """Test full subscription flow with mocked API."""

    # track callback invocations
    price_changes = []

    def on_price_change(change: PriceChange) -> None:
        price_changes.append(change)

    # mock the API client's internal components
    with patch("public_api_sdk.public_api_client.ApiClient"), patch(
        "public_api_sdk.public_api_client.AuthManager"
    ):

        config = PublicApiClientConfiguration(
            default_account_number="TEST123"
        )
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )

        instrument = OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)

        # mock quotes that will be returned
        quote1 = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("150.00"),
            bid=Decimal("149.95"),
            ask=Decimal("150.05"),
            volume=1000000,
        )
        quote2 = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("151.00"),  # price increased
            bid=Decimal("150.95"),
            ask=Decimal("151.05"),
            volume=1100000,
        )

        # mock get_quotes to return different quotes on each call
        quotes_sequence = [[quote1], [quote1], [quote2]]
        # Patch the subscription manager's reference to get_quotes
        client._subscription_manager.get_quotes_func = MagicMock(
            side_effect=quotes_sequence
        )

        # subscribe with fast polling
        sub_id = client.price_stream.subscribe(
            instruments=[instrument],
            callback=on_price_change,
            config=SubscriptionConfig(
                polling_frequency_seconds=0.1, retry_on_error=True
            ),
        )

        # verify subscription was created
        assert sub_id is not None
        assert sub_id in client.price_stream.get_active_subscriptions()

        # get subscription info
        info = client.price_stream.get_subscription_info(sub_id)
        assert info is not None
        assert info.status == "ACTIVE"
        assert len(info.instruments) == 1
        assert info.polling_frequency == 0.1

        # wait for price change to be detected
        time.sleep(0.5)

        # verify callback was invoked
        assert len(price_changes) > 0

        # check the price change details
        change = price_changes[0]
        assert change.instrument.symbol == "AAPL"
        assert change.new_quote.last == Decimal("151.00")
        assert "last" in change.changed_fields

        # test frequency update
        assert client.price_stream.set_polling_frequency(sub_id, 2.0) is True

        # test unsubscribe
        assert client.price_stream.unsubscribe(sub_id) is True
        assert sub_id not in client.price_stream.get_active_subscriptions()

        client.close()

        print("✅ Integration test passed!")


def test_multiple_subscriptions() -> None:
    """Test managing multiple concurrent subscriptions."""

    with patch("public_api_sdk.public_api_client.ApiClient"), patch(
        "public_api_sdk.public_api_client.AuthManager"
    ):
        config = PublicApiClientConfiguration(
            default_account_number="TEST123"
        )
        client = PublicApiClient(
            auth_config=ApiKeyAuthConfig(api_secret_key="test_key"),
            config=config,
        )

        # mock get_quotes - patch the subscription manager's reference
        client._subscription_manager.get_quotes_func = MagicMock(return_value=[])

        # create multiple subscriptions
        instruments1 = [
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
        ]
        instruments2 = [
            OrderInstrument(symbol="MSFT", type=InstrumentType.EQUITY),
        ]

        callback1 = MagicMock()
        sub1 = client.price_stream.subscribe(
            instruments1,
            callback1,
            SubscriptionConfig(polling_frequency_seconds=1.0),
        )

        callback2 = MagicMock()
        sub2 = client.price_stream.subscribe(
            instruments2,
            callback2,
            SubscriptionConfig(polling_frequency_seconds=2.0),
        )

        # verify both subscriptions are active
        active = client.price_stream.get_active_subscriptions()
        assert len(active) == 2
        assert sub1 in active
        assert sub2 in active

        # test unsubscribe_all
        client.price_stream.unsubscribe_all()
        assert len(client.price_stream.get_active_subscriptions()) == 0

        client.close()

        print("✅ Multiple subscriptions test passed!")


if __name__ == "__main__":
    test_subscription_integration()
    test_multiple_subscriptions()
