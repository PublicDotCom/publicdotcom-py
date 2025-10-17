# pylint: disable=protected-access,no-member
# Tests need to access private methods to verify implementation details

import unittest
from decimal import Decimal
from unittest.mock import MagicMock, patch

from public_api_sdk import (
    PublicApiClient,
    PublicApiClientConfiguration,
    ApiKeyAuthConfig,
    PriceStream,
    OrderInstrument,
    InstrumentType,
    Quote,
    QuoteOutcome,
    SubscriptionConfig,
)
from public_api_sdk.subscription_manager import PriceSubscriptionManager


class TestPriceStream(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_manager = MagicMock(spec=PriceSubscriptionManager)
        self.price_stream = PriceStream(self.mock_manager)
        self.test_instruments = [
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
        ]
        self.callback = MagicMock()

    def test_subscribe_delegates_to_manager(self) -> None:
        """Test that subscribe method delegates to the manager."""
        config = SubscriptionConfig(polling_frequency_seconds=2.0)
        expected_id = "sub-123"
        self.mock_manager.subscribe.return_value = expected_id

        result = self.price_stream.subscribe(
            self.test_instruments, self.callback, config
        )

        self.assertEqual(result, expected_id)
        self.mock_manager.subscribe.assert_called_once_with(
            self.test_instruments, self.callback, config
        )

    def test_unsubscribe_delegates_to_manager(self) -> None:
        """Test that unsubscribe method delegates to the manager."""
        sub_id = "sub-123"
        self.mock_manager.unsubscribe.return_value = True

        result = self.price_stream.unsubscribe(sub_id)

        self.assertTrue(result)
        self.mock_manager.unsubscribe.assert_called_once_with(sub_id)

    def test_unsubscribe_all_delegates_to_manager(self) -> None:
        """Test that unsubscribe_all method delegates to the manager."""
        self.price_stream.unsubscribe_all()
        self.mock_manager.unsubscribe_all.assert_called_once()

    def test_set_polling_frequency_delegates_to_manager(self) -> None:
        """Test that set_polling_frequency method delegates to the manager."""
        sub_id = "sub-123"
        frequency = 3.0
        self.mock_manager.set_polling_frequency.return_value = True

        result = self.price_stream.set_polling_frequency(sub_id, frequency)

        self.assertTrue(result)
        self.mock_manager.set_polling_frequency.assert_called_once_with(
            sub_id, frequency
        )

    def test_get_active_subscriptions_delegates_to_manager(self) -> None:
        """Test that get_active_subscriptions method delegates to the manager."""
        expected = ["sub-1", "sub-2"]
        self.mock_manager.get_active_subscriptions.return_value = expected

        result = self.price_stream.get_active_subscriptions()

        self.assertEqual(result, expected)
        self.mock_manager.get_active_subscriptions.assert_called_once()

    def test_get_subscription_info_delegates_to_manager(self) -> None:
        """Test that get_subscription_info method delegates to the manager."""
        sub_id = "sub-123"
        expected_info = MagicMock()
        self.mock_manager.get_subscription_info.return_value = expected_info

        result = self.price_stream.get_subscription_info(sub_id)

        self.assertEqual(result, expected_info)
        self.mock_manager.get_subscription_info.assert_called_once_with(sub_id)

    def test_pause_delegates_to_manager(self) -> None:
        """Test that pause method delegates to the manager."""
        sub_id = "sub-123"
        self.mock_manager.pause_subscription.return_value = True

        result = self.price_stream.pause(sub_id)

        self.assertTrue(result)
        self.mock_manager.pause_subscription.assert_called_once_with(sub_id)

    def test_resume_delegates_to_manager(self) -> None:
        """Test that resume method delegates to the manager."""
        sub_id = "sub-123"
        self.mock_manager.resume_subscription.return_value = True

        result = self.price_stream.resume(sub_id)

        self.assertTrue(result)
        self.mock_manager.resume_subscription.assert_called_once_with(sub_id)


class TestPriceStreamIntegration(unittest.TestCase):
    def test_client_has_price_stream_property(self) -> None:
        """Test that PublicApiClient exposes price_stream property."""
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

            # verify price_stream property exists and is correct type
            self.assertIsInstance(client.price_stream, PriceStream)

            # verify it wraps the internal subscription manager
            self.assertIs(client.price_stream._manager, client._subscription_manager)

            client.close()

    def test_price_stream_end_to_end(self) -> None:
        """Test end-to-end price streaming through the new API."""
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

            # mock the get_quotes function
            instrument = OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY)
            quote = Quote(
                instrument=instrument,
                outcome=QuoteOutcome.SUCCESS,
                last=Decimal("150.00"),
                bid=Decimal("149.95"),
                ask=Decimal("150.05"),
            )
            client._subscription_manager.get_quotes_func = MagicMock(
                return_value=[quote]
            )

            # test subscription through price_stream
            callback = MagicMock()
            sub_id = client.price_stream.subscribe(
                [instrument],
                callback,
                SubscriptionConfig(polling_frequency_seconds=1.0),
            )

            # verify subscription
            self.assertIsNotNone(sub_id)
            self.assertIn(sub_id, client.price_stream.get_active_subscriptions())

            # test other operations
            self.assertTrue(client.price_stream.pause(sub_id))
            self.assertTrue(client.price_stream.resume(sub_id))
            self.assertTrue(client.price_stream.set_polling_frequency(sub_id, 2.0))

            # clean up
            self.assertTrue(client.price_stream.unsubscribe(sub_id))
            self.assertNotIn(sub_id, client.price_stream.get_active_subscriptions())

            client.close()
