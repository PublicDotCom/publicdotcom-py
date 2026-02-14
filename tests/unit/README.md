# Test Suite Summary

This directory contains comprehensive tests for the publicdotcom-py SDK.

## Test Organization

```
tests/
├── conftest.py                      # Shared fixtures
├── unit/
│   ├── test_order_validation.py     # Model validation tests
│   ├── test_api_client_errors.py    # HTTP error handling tests
│   ├── test_auth_providers_extended.py  # Auth provider tests
│   ├── test_subscription_stress.py  # Concurrency/stress tests
│   ├── test_new_order_lifecycle.py  # Order lifecycle tests
│   └── test_public_api_client_integration.py  # Integration tests
├── test_auth.py                     # Original auth tests
├── test_new_order.py                # Original order tests
├── test_subscription.py             # Original subscription tests
└── ...
```

## Running Tests

```bash
# Run all tests
pytest tests/

# Run specific test file
pytest tests/unit/test_order_validation.py

# Run with coverage
pytest tests/ --cov=public_api_sdk --cov-report=term-missing

# Run stress tests (may take longer)
pytest tests/unit/test_subscription_stress.py -v
```

## New Test Coverage

### test_order_validation.py
- Order expiration validation (DAY vs GTD)
- Quantity and amount validation
- Limit price validation for order types
- Stop price validation
- Multi-leg order validation
- Edge cases

### test_api_client_errors.py
- HTTP status code handling (400, 401, 404, 429, 500+)
- Rate limit retry-after handling
- Malformed JSON responses
- Network timeout handling
- URL construction
- Header management

### test_auth_providers_extended.py
- API key validity bounds (5-1440 minutes)
- Token expiry calculation with safety buffer
- Token refresh timing
- PKCE code verifier generation
- OAuth state CSRF protection
- Token refresh flow
- Manual token setting

### test_subscription_stress.py
- Multiple subscriptions to same instrument
- Concurrent subscribe/unsubscribe
- Callback exception handling
- Memory leak detection
- Pause/resume functionality
- Polling frequency bounds
- Thread cleanup

### test_new_order_lifecycle.py
- wait_for_status with timeout
- wait_for_fill success and timeout
- wait_for_terminal_status for all terminal states
- Cancel workflow
- Subscription lifecycle
- OrderUpdate model validation
- OrderSubscriptionConfig bounds

### test_public_api_client_integration.py
- Full order lifecycle flow
- Account operations
- Portfolio retrieval
- Quote fetching
- History pagination
- Instrument details
- Preflight calculations
- Option chain and Greeks
- API endpoint management

## Dependencies Added

```toml
[project.optional-dependencies]
dev = [
    ...
    "responses>=0.23.0",  # HTTP mocking
    "freezegun>=1.2.0",   # Time-based tests
]
```
