# Changelog

All notable changes to `publicdotcom-py` are documented here.

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
