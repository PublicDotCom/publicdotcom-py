"""Unit tests for the transport-independent pieces of the account stream."""

import json
from decimal import Decimal

import pytest

from public_api_sdk import (
    OrderStatus,
    OrderType,
    OrderUpdateEvent,
    StreamChannel,
    StreamHandshakeError,
    StreamOrder,
    TradeEvent,
    TradeStatus,
)
from public_api_sdk.models.instrument_type import InstrumentType
from public_api_sdk.models.order import EquityMarketSession, OrderSide
from public_api_sdk.stream_common import (
    STABLE_CONNECTION_SECONDS,
    FrameKind,
    FrameParser,
    ReconnectPolicy,
    build_headers,
    build_stream_url,
    handshake_error,
    normalize_accounts,
    normalize_channels,
)


def order_frame(version: int = 1, status: str = "NEW", **order_fields: object) -> str:
    order = {
        "orderId": "0b0b6a6e-6a41-4b5b-9d33-0d9c6a3a8f10",
        "accountNumber": "5RE12345",
        "version": version,
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "type": "LIMIT",
        "side": "BUY",
        "status": status,
        "quantity": 10,
        "expiration": {"timeInForce": "DAY", "expirationTime": None},
        "limitPrice": 180.10,
        "session": "CORE",
        "effective": True,
        "editable": True,
        "cancellable": True,
        "createdAt": "2026-10-28T20:00:00Z",
        "lastModified": "2026-10-28T20:00:00Z",
    }
    order.update(order_fields)
    return json.dumps(
        {
            "channel": "order",
            "type": "ORDER_UPDATE",
            "payload": {"order": order},
            "timestamp": "2026-10-28T20:00:00.120Z",
        }
    )


def trade_frame(trade_id: str = "T-1", status: str = "NEW", **fields: object) -> str:
    trade = {
        "tradeId": trade_id,
        "orderId": "0b0b6a6e-6a41-4b5b-9d33-0d9c6a3a8f10",
        "originalTradeId": None,
        "accountNumber": "5RE12345",
        "status": status,
        "instrument": {"symbol": "AAPL", "type": "EQUITY"},
        "quantity": "1",
        "price": "170.00",
        "side": "BUY",
        "timestamp": "2026-10-28T19:59:59Z",
        "marketIdentificationCode": "XNAS",
    }
    trade.update(fields)
    return json.dumps(
        {
            "channel": "trade",
            "type": "TRADE",
            "payload": trade,
            "timestamp": "2026-10-28T20:00:00Z",
        }
    )


# --------------------------------------------------------------------------- #
# Arguments and URL                                                            #
# --------------------------------------------------------------------------- #


class TestNormalizeAccounts:
    def test_none_uses_default_account(self) -> None:
        assert normalize_accounts(None, "5RE12345") == ["5RE12345"]

    def test_none_without_default_means_all_accounts(self) -> None:
        assert normalize_accounts(None, None) == ["*"]

    def test_list_and_comma_separated_strings(self) -> None:
        assert normalize_accounts(["5RE1", "5RE2,5RE3", "5RE1"], None) == [
            "5RE1",
            "5RE2",
            "5RE3",
        ]
        assert normalize_accounts("5RE1, 5RE2", None) == ["5RE1", "5RE2"]

    def test_star_cannot_be_combined(self) -> None:
        with pytest.raises(ValueError, match="cannot be combined"):
            normalize_accounts(["*", "5RE1"], None)

    def test_empty_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            normalize_accounts([], None)
        with pytest.raises(ValueError):
            normalize_accounts(" , ", None)

    def test_non_string_is_rejected(self) -> None:
        with pytest.raises(TypeError):
            normalize_accounts([123], None)  # type: ignore[list-item]


class TestNormalizeChannels:
    def test_default_is_all_known_channels(self) -> None:
        assert normalize_channels(None) == ["order", "trade"]

    def test_enum_string_and_dedupe(self) -> None:
        assert normalize_channels([StreamChannel.TRADE, "ORDER", "trade"]) == [
            "trade",
            "order",
        ]

    def test_single_value(self) -> None:
        assert normalize_channels(StreamChannel.ORDER) == ["order"]
        assert normalize_channels("trade") == ["trade"]  # type: ignore[arg-type]

    def test_unknown_channel_is_passed_through(self) -> None:
        assert normalize_channels(["position"]) == ["position"]

    def test_empty_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            normalize_channels([])


class TestBuildStreamUrl:
    def test_https_becomes_wss(self) -> None:
        url = build_stream_url("https://api.public.com", ["5RE1", "5RE2"], ["order", "trade"])
        assert url == (
            "wss://api.public.com/userapigateway"
            "?accountIds=5RE1,5RE2&channels=order,trade"
        )

    def test_http_becomes_ws_and_base_path_is_kept(self) -> None:
        url = build_stream_url("http://localhost:8080/gw/", ["*"], ["order"])
        assert url == "ws://localhost:8080/gw/userapigateway?accountIds=*&channels=order"

    def test_unsupported_scheme(self) -> None:
        with pytest.raises(ValueError):
            build_stream_url("ftp://example.com", ["*"], ["order"])

    def test_token_goes_in_header_not_url(self) -> None:
        headers = build_headers("tok")
        assert headers["Authorization"] == "Bearer tok"
        assert "tok" not in build_stream_url("https://a.b", ["*"], ["order"])


# --------------------------------------------------------------------------- #
# Frame parsing                                                                #
# --------------------------------------------------------------------------- #


class TestFrameParserOrders:
    def test_parses_order_update(self) -> None:
        kind, event = FrameParser().parse(order_frame())
        assert kind is FrameKind.EVENT
        assert isinstance(event, OrderUpdateEvent)
        order = event.order
        assert order.order_id == "0b0b6a6e-6a41-4b5b-9d33-0d9c6a3a8f10"
        assert order.account_number == "5RE12345"
        assert order.version == 1
        assert order.type is OrderType.LIMIT
        assert order.side is OrderSide.BUY
        assert order.status is OrderStatus.NEW
        assert order.session is EquityMarketSession.CORE
        assert order.instrument.type is InstrumentType.EQUITY
        assert order.effective is True
        assert event.timestamp is not None

    def test_json_numbers_are_parsed_exactly(self) -> None:
        _, event = FrameParser().parse(order_frame(limitPrice=0.1, averagePrice=179.85))
        assert isinstance(event, OrderUpdateEvent)
        assert event.order.limit_price == Decimal("0.1")
        assert event.order.average_price == Decimal("179.85")
        assert event.order.quantity == Decimal("10")

    def test_unknown_enum_values_and_fields_are_tolerated(self) -> None:
        raw = order_frame(
            type="TRAILING_STOP",
            session="OVERNIGHT",
            instrument={"symbol": "XYZ", "type": "PERPETUAL"},
            trailingStop={"type": "PERCENTAGE", "value": 0.05, "limitOffset": None},
            somethingNew={"a": 1},
        )
        _, event = FrameParser().parse(raw)
        assert isinstance(event, OrderUpdateEvent)
        assert event.order.type == "TRAILING_STOP"
        assert event.order.session == "OVERNIGHT"
        assert event.order.instrument.type == "PERPETUAL"
        assert event.order.trailing_stop is not None
        assert event.order.trailing_stop.value == Decimal("0.05")

    def test_lower_or_equal_version_is_dropped(self) -> None:
        parser = FrameParser()
        assert parser.parse(order_frame(version=2))[0] is FrameKind.EVENT
        assert parser.parse(order_frame(version=2)) == (FrameKind.IGNORED, None)
        assert parser.parse(order_frame(version=1)) == (FrameKind.IGNORED, None)
        assert parser.parse(order_frame(version=3))[0] is FrameKind.EVENT

    def test_versions_are_tracked_per_order(self) -> None:
        parser = FrameParser()
        assert parser.parse(order_frame(version=5))[0] is FrameKind.EVENT
        assert parser.parse(order_frame(version=1, orderId="other"))[0] is FrameKind.EVENT

    def test_deduplicate_off_delivers_everything(self) -> None:
        parser = FrameParser(deduplicate=False)
        assert parser.parse(order_frame(version=2))[0] is FrameKind.EVENT
        assert parser.parse(order_frame(version=1))[0] is FrameKind.EVENT

    def test_is_final(self) -> None:
        _, new = FrameParser().parse(order_frame(status="PARTIALLY_FILLED"))
        _, filled = FrameParser().parse(order_frame(status="FILLED"))
        assert isinstance(new, OrderUpdateEvent) and not new.order.is_final
        assert isinstance(filled, OrderUpdateEvent) and filled.order.is_final


class TestFrameParserTrades:
    def test_parses_trade(self) -> None:
        kind, event = FrameParser().parse(trade_frame())
        assert kind is FrameKind.EVENT
        assert isinstance(event, TradeEvent)
        trade = event.trade
        assert trade.trade_id == "T-1"
        assert trade.status is TradeStatus.NEW
        assert trade.quantity == Decimal("1")
        assert trade.price == Decimal("170.00")
        assert trade.market_identification_code == "XNAS"

    def test_trade_without_order_and_tiny_decimal(self) -> None:
        _, event = FrameParser().parse(
            trade_frame(orderId=None, quantity="0.00001", instrument={"symbol": "BTC", "type": "CRYPTO"})
        )
        assert isinstance(event, TradeEvent)
        assert event.trade.order_id is None
        assert event.trade.quantity == Decimal("0.00001")

    def test_cancel_follows_new_and_repeats_are_dropped(self) -> None:
        parser = FrameParser()
        assert parser.parse(trade_frame(status="NEW"))[0] is FrameKind.EVENT
        assert parser.parse(trade_frame(status="NEW"))[0] is FrameKind.IGNORED
        _, cancelled = parser.parse(trade_frame(status="CANCELLED"))
        assert isinstance(cancelled, TradeEvent)
        assert cancelled.trade.status is TradeStatus.CANCELLED
        assert parser.parse(trade_frame(status="CANCELLED"))[0] is FrameKind.IGNORED

    def test_unknown_trade_status(self) -> None:
        _, event = FrameParser().parse(trade_frame(status="CORRECTED"))
        assert isinstance(event, TradeEvent)
        assert event.trade.status is TradeStatus.UNKNOWN


class TestFrameParserOtherFrames:
    @pytest.mark.parametrize(
        "raw",
        [
            "not json",
            "[1, 2]",
            json.dumps({"channel": "position", "type": "POSITION_UPDATE", "payload": {}}),
            json.dumps({"channel": "order", "type": "ORDER_DELETED", "payload": {}}),
            # a known type whose payload is broken is logged and skipped
            json.dumps({"channel": "order", "type": "ORDER_UPDATE", "payload": {"order": {}}}),
            json.dumps({"channel": "trade", "type": "TRADE", "payload": None}),
        ],
    )
    def test_ignored(self, raw: str) -> None:
        assert FrameParser().parse(raw) == (FrameKind.IGNORED, None)

    def test_pong(self) -> None:
        assert FrameParser().parse('{"type":"PONG"}') == (FrameKind.PONG, None)

    def test_bytes_frame(self) -> None:
        assert FrameParser().parse(order_frame().encode())[0] is FrameKind.EVENT


# --------------------------------------------------------------------------- #
# Reconnect policy and errors                                                  #
# --------------------------------------------------------------------------- #


class TestReconnectPolicy:
    def test_exponential_backoff_capped(self) -> None:
        policy = ReconnectPolicy(1.0, 30.0, rand=lambda: 1.0)
        assert [policy.next_delay() for _ in range(7)] == [1, 2, 4, 8, 16, 30, 30]

    def test_jitter_is_between_half_and_full(self) -> None:
        policy = ReconnectPolicy(1.0, 30.0, rand=lambda: 0.0)
        assert policy.next_delay() == 0.5

    def test_max_attempts(self) -> None:
        policy = ReconnectPolicy(1.0, 30.0, max_attempts=2)
        assert policy.next_delay() is not None
        assert policy.next_delay() is not None
        assert policy.next_delay() is None

    def test_stable_connection_resets_backoff(self) -> None:
        policy = ReconnectPolicy(1.0, 30.0, rand=lambda: 1.0)
        policy.next_delay()
        policy.next_delay()
        policy.connection_ended(STABLE_CONNECTION_SECONDS - 1)
        assert policy.next_delay() == 4
        policy.connection_ended(STABLE_CONNECTION_SECONDS)
        assert policy.next_delay() == 1

    @pytest.mark.parametrize("status", [400, 403])
    def test_fatal_statuses(self, status: int) -> None:
        error = StreamHandshakeError("x", status_code=status)
        assert ReconnectPolicy().rejected(error) is error

    @pytest.mark.parametrize("status", [429, 500, 503])
    def test_retryable_statuses(self, status: int) -> None:
        error = StreamHandshakeError("x", status_code=status)
        assert ReconnectPolicy().rejected(error) is None
        assert error.retryable

    def test_401_is_retried_once_with_a_fresh_token(self) -> None:
        policy = ReconnectPolicy()
        error = StreamHandshakeError("x", status_code=401)
        assert not policy.force_token_refresh
        assert policy.rejected(error) is None
        assert policy.force_token_refresh
        assert policy.rejected(error) is error

    def test_successful_connect_clears_401_count(self) -> None:
        policy = ReconnectPolicy()
        error = StreamHandshakeError("x", status_code=401)
        policy.rejected(error)
        policy.connected()
        assert not policy.force_token_refresh
        assert policy.rejected(error) is None

    def test_invalid_arguments(self) -> None:
        with pytest.raises(ValueError):
            ReconnectPolicy(5.0, 1.0)
        with pytest.raises(ValueError):
            ReconnectPolicy(max_attempts=-1)


def test_handshake_error_uses_body_text() -> None:
    error = handshake_error(403, b"Forbidden\n")
    assert error.status_code == 403
    assert error.message == "Forbidden"
    assert not error.retryable
    assert "403" in str(error)


def test_handshake_error_without_body() -> None:
    assert "HTTP 503" in handshake_error(503, b"").message


def test_stream_order_accepts_snake_case_names() -> None:
    order = StreamOrder(
        order_id="o",
        account_number="5RE12345",
        version=1,
        instrument={"symbol": "AAPL", "type": "EQUITY"},  # type: ignore[arg-type]
        type="MARKET",
        side="SELL",
        status=OrderStatus.NEW,
    )
    assert order.type is OrderType.MARKET
    assert order.side is OrderSide.SELL
