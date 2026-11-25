# Changelog

All notable changes to `publicdotcom-py` are documented here.

## 0.2.2 — 2026-11-25

### Fixed
- Orders with type `TRAILING_STOP` or `TRAILING_STOP_LIMIT` (the trailing
  stop-loss leg of a BRACKET or OTO order), and any future order type, no
  longer break `get_portfolio`, `get_order` and `search_orders`. One such
  order used to fail the whole call with a `ValidationError` on `Order.type`.
- Response models are lenient, as the stream's already were: on `Order` /
  `OrderV2` (type, side, instrument type, time in force, open/close indicator),
  their legs, `Trade`, and `Portfolio` (account type, equity asset type,
  position instrument type), a value the SDK does not know yet is kept as its
  raw string instead of failing validation. Known values are still enum
  members. Request models stay strict.

### Added
- `OrderType.TRAILING_STOP` and `OrderType.TRAILING_STOP_LIMIT`. They are
  response-only: `OrderRequest`, `PreflightRequest`, `CancelAndReplaceRequest`
  and multi-leg requests reject them (`TRAILING_STOP_ORDER_TYPES`).
- `trailing_stop` (`TrailingStop`: `type` `AMOUNT` / `PERCENTAGE`, `value`,
  `limit_offset`) and `high_watermark` on `Order`. A `PERCENTAGE` value is a
  fraction: 0.05 is 5%. `StreamTrailingStop` is now the same model, with
  `type` as a `TrailingStopType`.
- `OrderResponseInstrument` and `LegResponseInstrument`: the lenient
  instrument models used by responses (subclasses of `OrderInstrument` and
  `LegInstrument`).

### Upgrading
- No code changes needed. Order enum fields in responses may now be a raw
  string for values the SDK doesn't know yet: compare with `==` rather than
  calling `.value` on them.
- For type checkers, `Order.instrument` is now `OrderResponseInstrument`.
  Building an `Order` by hand from an `OrderInstrument` still works at
  runtime, but a type checker may flag it.

## 0.2.1 — 2026-11-19

### Fixed
- The order & trade stream delivers events again. On 2026-11-15 the API moved
  the order or trade in each stream frame from `payload` to a top-level `data`
  field; 0.2.0 stayed connected but logged a parse warning and dropped every
  `ORDER_UPDATE` and `TRADE` event. The parser now reads `data`, and still
  reads the older `payload` format.

### Added
- `fees`, `commission` and `rebate` (`Optional[Decimal]`) on `StreamOrder` and
  `StreamTrade`.

### Upgrading
- No code changes needed: events still expose `event.order` and `event.trade`.

## 0.2.0

### Added
- Order & trade WebSocket stream: `client.stream()` (sync, background thread)
  and `AsyncPublicApiClient.stream()` (asyncio task, async iterator of events).
