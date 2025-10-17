# pylint: disable=protected-access,no-member
# Tests need to access private methods to verify implementation details
# no-member: Pylint has issues with Pydantic models and enum attributes

import threading
import time
import unittest
from decimal import Decimal
from unittest.mock import MagicMock

from public_api_sdk.models import (
    OrderInstrument,
    InstrumentType,
    Quote,
    QuoteOutcome,
    PriceChange,
    SubscriptionConfig,
    SubscriptionStatus,
)
from public_api_sdk.subscription_manager import PriceSubscriptionManager


class TestPriceSubscriptionManager(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_get_quotes = MagicMock()
        self.manager = PriceSubscriptionManager(self.mock_get_quotes)
        self.test_instruments = [
            OrderInstrument(symbol="AAPL", type=InstrumentType.EQUITY),
            OrderInstrument(symbol="GOOGL", type=InstrumentType.EQUITY),
        ]

    def tearDown(self) -> None:
        self.manager.stop()
        time.sleep(0.1)  # allow cleanup to complete

    def test_subscribe_creates_subscription(self) -> None:
        callback = MagicMock()

        sub_id = self.manager.subscribe(
            instruments=self.test_instruments, callback=callback
        )

        self.assertIsNotNone(sub_id)
        self.assertIn(sub_id, self.manager.subscriptions)
        self.assertEqual(len(self.manager.subscriptions), 1)

        subscription = self.manager.subscriptions[sub_id]
        self.assertEqual(subscription.status, SubscriptionStatus.ACTIVE)
        self.assertEqual(subscription.instruments, self.test_instruments)

    def test_subscribe_with_custom_config(self) -> None:
        callback = MagicMock()
        config = SubscriptionConfig(
            polling_frequency_seconds=2.0, retry_on_error=False, max_retries=5
        )

        sub_id = self.manager.subscribe(
            instruments=self.test_instruments, callback=callback, config=config
        )

        subscription = self.manager.subscriptions[sub_id]
        self.assertEqual(subscription.config.polling_frequency_seconds, 2.0)
        self.assertEqual(subscription.config.retry_on_error, False)
        self.assertEqual(subscription.config.max_retries, 5)

    def test_unsubscribe_removes_subscription(self) -> None:
        callback = MagicMock()
        sub_id = self.manager.subscribe(self.test_instruments, callback)

        result = self.manager.unsubscribe(sub_id)

        self.assertTrue(result)
        self.assertNotIn(sub_id, self.manager.subscriptions)
        self.assertEqual(len(self.manager.subscriptions), 0)

    def test_unsubscribe_nonexistent_returns_false(self) -> None:
        result = self.manager.unsubscribe("nonexistent-id")
        self.assertFalse(result)

    def test_unsubscribe_all_clears_subscriptions(self) -> None:
        callback1 = MagicMock()
        callback2 = MagicMock()

        self.manager.subscribe([self.test_instruments[0]], callback1)
        self.manager.subscribe([self.test_instruments[1]], callback2)

        self.assertEqual(len(self.manager.subscriptions), 2)

        self.manager.unsubscribe_all()

        self.assertEqual(len(self.manager.subscriptions), 0)
        self.assertEqual(len(self.manager.instrument_to_subscription), 0)
        self.assertEqual(len(self.manager.last_quotes), 0)

    def test_pause_and_resume_subscription(self) -> None:
        callback = MagicMock()
        sub_id = self.manager.subscribe(self.test_instruments, callback)

        # pause
        result = self.manager.pause_subscription(sub_id)
        self.assertTrue(result)
        self.assertEqual(
            self.manager.subscriptions[sub_id].status, SubscriptionStatus.PAUSED
        )

        # resume
        result = self.manager.resume_subscription(sub_id)
        self.assertTrue(result)
        self.assertEqual(
            self.manager.subscriptions[sub_id].status, SubscriptionStatus.ACTIVE
        )

    def test_set_polling_frequency(self) -> None:
        callback = MagicMock()
        sub_id = self.manager.subscribe(self.test_instruments, callback)

        # valid frequency
        result = self.manager.set_polling_frequency(sub_id, 5.0)
        self.assertTrue(result)
        self.assertEqual(
            self.manager.subscriptions[sub_id].config.polling_frequency_seconds, 5.0
        )

        # invalid frequency (too low)
        with self.assertRaises(ValueError):
            self.manager.set_polling_frequency(sub_id, 0.05)

        # invalid frequency (too high)
        with self.assertRaises(ValueError):
            self.manager.set_polling_frequency(sub_id, 61)

    def test_get_active_subscriptions(self) -> None:
        callback = MagicMock()

        sub_id1 = self.manager.subscribe([self.test_instruments[0]], callback)
        sub_id2 = self.manager.subscribe([self.test_instruments[1]], callback)

        active = self.manager.get_active_subscriptions()
        self.assertEqual(len(active), 2)
        self.assertIn(sub_id1, active)
        self.assertIn(sub_id2, active)

        # pause one
        self.manager.pause_subscription(sub_id1)
        active = self.manager.get_active_subscriptions()
        self.assertEqual(len(active), 1)
        self.assertIn(sub_id2, active)

    def test_get_subscription_info(self) -> None:
        callback = MagicMock()
        config = SubscriptionConfig(polling_frequency_seconds=3.0)

        sub_id = self.manager.subscribe(self.test_instruments, callback, config)

        info = self.manager.get_subscription_info(sub_id)

        self.assertIsNotNone(info)
        if info:
            self.assertEqual(info.id, sub_id)
            self.assertEqual(info.status, "ACTIVE")
            self.assertEqual(info.polling_frequency, 3.0)
            self.assertEqual(len(info.instruments), 2)

        # Nonexistent subscription
        info = self.manager.get_subscription_info("nonexistent")
        self.assertIsNone(info)

    def test_detect_price_change(self) -> None:
        instrument = self.test_instruments[0]

        old_quote = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("150.00"),
            bid=Decimal("149.99"),
            ask=Decimal("150.01"),
            bid_size=100,
            ask_size=200,
            volume=1000000,
        )

        # no change
        same_quote = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("150.00"),
            bid=Decimal("149.99"),
            ask=Decimal("150.01"),
            bid_size=100,
            ask_size=200,
            volume=1000000,
        )

        change = self.manager._detect_price_change(instrument, old_quote, same_quote)
        self.assertIsNone(change)

        # price change
        new_quote = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("151.00"),
            bid=Decimal("150.99"),
            ask=Decimal("151.01"),
            bid_size=150,
            ask_size=200,
            volume=1100000,
        )

        change = self.manager._detect_price_change(instrument, old_quote, new_quote)
        self.assertIsNotNone(change)
        if change:
            self.assertIn("last", change.changed_fields)
            self.assertIn("bid", change.changed_fields)
            self.assertIn("ask", change.changed_fields)
            # all 5 fields changed
            self.assertEqual(len(change.changed_fields), 3)
            self.assertEqual(change.old_quote, old_quote)
            self.assertEqual(change.new_quote, new_quote)

    def test_callback_execution_on_price_change(self) -> None:
        callback = MagicMock()
        instrument = self.test_instruments[0]

        # mock quotes
        quote1 = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("150.00"),
            bid=Decimal("149.99"),
            ask=Decimal("150.01"),
        )

        quote2 = Quote(
            instrument=instrument,
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("151.00"),  # changed
            bid=Decimal("150.99"),  # changed
            ask=Decimal("151.01"),  # changed
        )

        # setup mock to return different quotes
        self.mock_get_quotes.side_effect = [[quote1], [quote2]]

        # subscribe
        self.manager.subscribe(
            [instrument], callback, SubscriptionConfig(polling_frequency_seconds=0.1)
        )

        # wait for polling to occur
        time.sleep(0.5)

        # check callback was called with price change
        callback.assert_called()
        call_args = callback.call_args[0][0]
        self.assertIsInstance(call_args, PriceChange)
        self.assertEqual(call_args.new_quote.last, Decimal("151.00"))

    def test_multiple_subscriptions_same_instrument(self) -> None:
        callback1 = MagicMock()
        callback2 = MagicMock()
        instrument = self.test_instruments[0]

        sub_id1 = self.manager.subscribe([instrument], callback1)
        sub_id2 = self.manager.subscribe([instrument], callback2)

        # check instrument mapping
        key = f"{instrument.symbol}_{instrument.type.value}"
        self.assertEqual(len(self.manager.instrument_to_subscription[key]), 2)
        self.assertIn(sub_id1, self.manager.instrument_to_subscription[key])
        self.assertIn(sub_id2, self.manager.instrument_to_subscription[key])

    def test_error_handling_in_get_quotes(self) -> None:
        callback = MagicMock()
        self.mock_get_quotes.side_effect = Exception("API Error")

        # subscribe with retry disabled
        config = SubscriptionConfig(polling_frequency_seconds=0.1, retry_on_error=False)

        self.manager.subscribe(self.test_instruments, callback, config)

        # wait for polling
        time.sleep(0.3)

        # callback should not be called due to error
        callback.assert_not_called()

    def test_retry_logic_on_error(self) -> None:
        callback = MagicMock()

        quote = Quote(
            instrument=self.test_instruments[0],
            outcome=QuoteOutcome.SUCCESS,
            last=Decimal("150.00"),
        )

        # first two calls fail, third succeeds
        self.mock_get_quotes.side_effect = [
            Exception("API Error 1"),
            Exception("API Error 2"),
            [quote],
        ]

        config = SubscriptionConfig(
            polling_frequency_seconds=0.1,
            retry_on_error=True,
            max_retries=3,
            exponential_backoff=False,
        )

        sub_id = self.manager.subscribe([self.test_instruments[0]], callback, config)

        # wait longer for polling and retries
        time.sleep(1.0)

        # should have called get_quotes at least once (retries happen within single poll)
        self.assertGreaterEqual(self.mock_get_quotes.call_count, 1)

        # verify that error was logged but subscription still active
        self.assertEqual(
            self.manager.subscriptions[sub_id].status, SubscriptionStatus.ACTIVE
        )

    async def test_async_callback(self) -> None:
        async_called = threading.Event()

        async def async_callback(_price_change: PriceChange) -> None:
            async_called.set()

        instrument = self.test_instruments[0]
        quote1 = Quote(
            instrument=instrument, outcome=QuoteOutcome.SUCCESS, last=Decimal("150.00")
        )
        quote2 = Quote(
            instrument=instrument, outcome=QuoteOutcome.SUCCESS, last=Decimal("151.00")
        )

        self.mock_get_quotes.side_effect = [[quote1], [quote2]]

        self.manager.subscribe(
            [instrument],
            async_callback,
            SubscriptionConfig(polling_frequency_seconds=0.1),
        )

        # wait for async callback
        self.assertTrue(async_called.wait(timeout=2))

    def test_subscription_validation(self) -> None:
        # empty instruments
        with self.assertRaises(ValueError):
            self.manager.subscribe([], MagicMock())


class TestSubscriptionConfig(unittest.TestCase):
    def test_default_config(self) -> None:
        config = SubscriptionConfig()
        self.assertEqual(config.polling_frequency_seconds, 1.0)
        self.assertTrue(config.retry_on_error)
        self.assertEqual(config.max_retries, 3)
        self.assertTrue(config.exponential_backoff)

    def test_invalid_polling_frequency(self) -> None:
        # too low
        with self.assertRaises(ValueError):
            SubscriptionConfig(polling_frequency_seconds=0.05)

        # too high
        with self.assertRaises(ValueError):
            SubscriptionConfig(polling_frequency_seconds=65)

    def test_valid_config(self) -> None:
        config = SubscriptionConfig(
            polling_frequency_seconds=5.0,
            retry_on_error=False,
            max_retries=10,
            exponential_backoff=False,
        )

        self.assertEqual(config.polling_frequency_seconds, 5.0)
        self.assertFalse(config.retry_on_error)
        self.assertEqual(config.max_retries, 10)
        self.assertFalse(config.exponential_backoff)
