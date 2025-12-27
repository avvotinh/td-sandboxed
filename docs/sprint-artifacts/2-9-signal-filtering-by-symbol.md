# Story 2.9: Signal Filtering by Symbol

Status: Done

## Story

As a **trader**,
I want **signals filtered based on my account's allowed symbols**,
So that **I only trade the symbols I've configured**.

## Acceptance Criteria

1. **AC1**: Given an account is configured with `signal_filter: { symbols: ["XAUUSD"] }`, when a bar for XAUUSD arrives, then the strategy processes it

2. **AC2**: Given an account is configured with `signal_filter: { symbols: ["XAUUSD"] }`, when a bar for BTCUSD arrives, then the strategy ignores it (not in allowed symbols)

3. **AC3**: Given an account allows multiple symbols `signal_filter: { symbols: ["XAUUSD", "EURUSD", "GBPUSD"] }`, when bars for any of these symbols arrive, then the strategy processes them

4. **AC4**: Given a signal is generated for a symbol not in the filter, when the engine processes the signal, then the signal is dropped with a DEBUG log

5. **AC5**: Symbol matching is case-insensitive (e.g., "xauusd" matches "XAUUSD")

6. **AC6**: When an account has an empty symbols filter, all symbols are allowed

7. **AC7**: Unit tests cover all filtering scenarios with >90% coverage

## Tasks / Subtasks

### Task 1: Verify Existing Signal Filtering Implementation (AC: 1, 2, 3, 5, 6)
- [x] Review existing `StrategyDataRouter` class in `src/strategies/data_router.py`
- [x] Confirm symbol filtering logic is implemented correctly
- [x] Verify case-insensitive matching is working
- [x] Confirm empty filter allows all symbols
- [x] Verify `id` attribute is available on account objects passed to StrategyDataRouter

**Note**: This functionality is **already implemented** in `data_router.py` (Story 2.6). Checkmarks indicate verified existing code, not new implementation:
- `_should_route_to_account()` method handles symbol filtering
- Case-insensitive matching via `.upper()` normalization
- Empty filter returns `True` (allow all)
- `HasStrategy` protocol updated to include `id: str` attribute
- `BoundAccount` dataclass provides `id` property from wrapped `AccountConfig`

### Task 2: Enhance DEBUG Logging for Filtered Signals (AC: 4)
- [x] Add DEBUG logging when a bar/tick is filtered out
- [x] Log format: `DEBUG: Filtered data for {symbol} - not in account {account_id} filter (allowed: {symbols})`
- [x] Ensure logging doesn't impact performance (DEBUG level only)

### Task 3: Create SignalFilter Integration Module (OPTIONAL - Epic 3 Preparation)
> **Note:** This task is optional for Story 2.9. The existing `StrategyDataRouter` already satisfies AC 1-6. This task prepares for Epic 3 multi-account expansion.

- [ ] Create `src/accounts/signal_router.py` (or enhance existing data_router.py)
- [ ] Implement `SignalRouter` class as per architecture (Epic 3 preparation)
- [ ] Add `should_process(account_id: str, symbol: str) -> bool` method
- [ ] Build symbol->accounts mapping for O(1) routing lookup

**Status**: Deferred to Epic 3 - not required for Story 2.9 acceptance criteria

### Task 4: Write Additional Unit Tests (AC: 7)
- [x] Existing: `tests/unit/test_data_router.py` now has 22 tests covering:
  - Routes bar to active account with matching symbol
  - Skips inactive account
  - Skips unallowed symbol
  - Routes when no symbol filter (empty = allow all)
  - Routes when signal_filter is None
  - Routes to multiple accounts
  - Handles strategy error gracefully
  - Symbol matching case-insensitive
  - Skips account without strategy_instance
  - DEBUG logging when symbol filtered (NEW)
  - DEBUG logging with unknown account id (NEW)
  - Tick routing tests (expanded)
  - Async routing tests
  - Callback getter tests (expanded)
- [x] Add test for DEBUG logging when signal is filtered
- [x] Add integration test with real AccountConfig model (`tests/integration/test_signal_filtering_integration.py`)
- [x] Verify coverage meets >90% threshold: **100% coverage achieved on data_router.py**

### Task 5: Integration with Redis Adapter (AC: 1-4)
- [x] Verify `RedisAdapter.set_bar_callback()` integration point exists
- [x] `redis_adapter.py:330-344` provides callback support for signal routing
- [x] Document integration pattern in module docstring
- [x] Add integration test demonstrating bar callback usage (`tests/integration/test_signal_filtering_integration.py`)

## Dev Notes

### Quick Reference

**Key Implementation Points:**
- Signal filtering is **already implemented** in `StrategyDataRouter` class
- Primary file: `src/strategies/data_router.py`
- 14 unit tests already passing in `tests/unit/test_data_router.py`
- Integration point: `RedisAdapter.set_bar_callback()` for routing bars

**Existing Implementation Pattern (from data_router.py):**
```python
def _should_route_to_account(self, account: HasStrategy, symbol: str) -> bool:
    """Check if data should be routed to an account."""
    # Skip inactive accounts
    if account.status != "active":
        return False

    # Get signal filter
    signal_filter = getattr(account, 'signal_filter', None)
    if signal_filter is None:
        return True  # No filter = allow all

    # Check symbol filter
    allowed_symbols = getattr(signal_filter, 'symbols', [])
    if not allowed_symbols:
        return True  # Empty = allow all

    # Normalize and compare (case-insensitive)
    symbol_upper = symbol.upper()
    allowed_upper = [s.upper() for s in allowed_symbols]
    return symbol_upper in allowed_upper
```

**DEBUG Logging Enhancement (IMPLEMENTED):**
```python
def _should_route_to_account(self, account: HasStrategy, symbol: str) -> bool:
    # ... existing logic ...

    # Case-insensitive check with DEBUG logging
    symbol_upper = symbol.upper()
    allowed_upper = [s.upper() for s in allowed_symbols]

    if symbol_upper not in allowed_upper:
        logger.debug(
            "Filtered data for %s - not in account %s filter (allowed: %s)",
            symbol,
            getattr(account, 'id', 'unknown'),
            allowed_symbols,
        )
        return False

    return True
```

### Architecture Patterns and Constraints

**From Architecture Document (docs/architecture.md):**
```
services/trading-engine/
├── src/
│   ├── accounts/
│   │   ├── signal_router.py     # Signal routing (Epic 3 expansion)
│   ├── strategies/
│   │   ├── data_router.py       # Current location of routing logic
```

**Technology Stack:**
| Component | Technology | Version |
|-----------|------------|---------|
| Trading Framework | NautilusTrader | 1.x (1.200+) |
| Package Manager | uv | Latest |
| Python | Python | 3.11+ |
| Redis Client | redis-py | 5.0+ |

### Technical Requirements from Context7 NautilusTrader Research (2025-12-28)

> **Note:** This section is informational context. Signal filtering for this story is implemented in `data_router.py`, NOT via NautilusTrader MessageBusConfig. These patterns are provided for future reference when integrating with NautilusTrader's native filtering.

**Signal Filtering Pattern (NautilusTrader Message Bus):**
```python
# NautilusTrader supports type filtering via MessageBusConfig
from nautilus_trader.config import MessageBusConfig

message_bus = MessageBusConfig(
    types_filter=[QuoteTick, TradeTick]  # Filter specific types
)
```

**Instrument Filtering Pattern:**
```python
# Get filtered instruments by venue or underlying
venue_instruments = self.cache.instruments(venue=venue)
instruments_by_underlying = self.cache.instruments(underlying="ES")
```

**Signal Subscription Pattern:**
```python
# Subscribe to specific signals
self.subscribe_signal("signal_name")

# Handler receives matching signals
def on_signal(self, signal):
    match signal.value:
        case "signal_name":
            # Handle signal
            pass
```

### Existing Codebase Integration

**SignalFilter Model (src/accounts/models.py) - Story 2.1 COMPLETE:**
```python
class SignalFilter(BaseModel):
    """Signal filtering configuration."""
    symbols: list[str] = Field(default_factory=list, description="Allowed symbols")
    sessions: list[str] = Field(default_factory=list, description="Allowed sessions")
    max_spread_pips: Optional[float] = Field(default=None, ge=0)
```

**StrategyDataRouter (src/strategies/data_router.py) - Story 2.6 COMPLETE:**
- Provides `route_bar()` and `route_tick()` methods
- Uses `_should_route_to_account()` for filtering
- Supports both sync and async callbacks
- Has `HasStrategy` protocol for type safety

**RedisAdapter Integration (src/adapters/redis_adapter.py) - Story 2.6 COMPLETE:**
```python
# Set callback for bar routing
redis_adapter.set_bar_callback(router.route_bar)

# Or async callback
redis_adapter.set_bar_callback(router.route_bar_async)
```

### File Structure Requirements

```
services/trading-engine/
├── src/
│   ├── strategies/
│   │   ├── data_router.py         # MODIFY: Add DEBUG logging for filtered signals
│   ├── accounts/
│   │   ├── signal_router.py       # NEW: Optional - SignalRouter class for Epic 3 prep
├── tests/
│   ├── unit/
│   │   ├── test_data_router.py    # MODIFY: Add DEBUG logging test
│   ├── integration/
│   │   ├── test_signal_filtering_integration.py  # NEW: Integration test
```

### Testing Requirements

**Existing Unit Tests (tests/unit/test_data_router.py) - 14 tests:**
- `TestStrategyDataRouterBarRouting`: 8 tests
  - `test_routes_bar_to_active_account`
  - `test_skips_inactive_account`
  - `test_skips_unallowed_symbol`
  - `test_routes_when_no_symbol_filter`
  - `test_routes_to_multiple_accounts`
  - `test_handles_strategy_error_gracefully`
  - `test_symbol_matching_case_insensitive`
  - `test_skips_account_without_strategy_instance`
- `TestStrategyDataRouterTickRouting`: 2 tests
- `TestStrategyDataRouterCallbacks`: 2 tests
- `TestStrategyDataRouterAsync`: 2 tests

**Additional Tests Needed:**
```python
def test_logs_debug_when_symbol_filtered(self, caplog):
    """Should log DEBUG when symbol is filtered."""
    import logging
    caplog.set_level(logging.DEBUG)

    mock_account = Mock()
    mock_account.status = "active"
    mock_account.id = "test-account"
    mock_account.strategy_instance = Mock()
    mock_account.signal_filter.symbols = ["EURUSD"]

    router = StrategyDataRouter([mock_account])

    mock_bar = Mock()
    mock_bar.symbol = "XAUUSD"

    router.route_bar(mock_bar)

    assert "Filtered" in caplog.text
    assert "XAUUSD" in caplog.text
```

**Test Execution:**
```bash
# From services/trading-engine directory
cd services/trading-engine

# Run signal filtering tests
uv run pytest tests/unit/test_data_router.py -v

# Run with coverage
uv run pytest tests/unit/test_data_router.py -v --cov=src/strategies/data_router

# Check code quality
uv run ruff check src/strategies/data_router.py
```

### Previous Story Learnings (Story 2.8)

From Story 2.8 MA Crossover Strategy implementation:

**Key Patterns Established:**
- Import NautilusTrader components from `nautilus_trader.*`
- Use msgspec `__post_init__` for validation (not Pydantic `@field_validator`)
- Tests use standalone logic validation due to NautilusTrader Rust-based limitations
- Mock objects extensively for unit tests

**Implementation Patterns from Story 2.8:**
```python
# Position reversal with immediate re-entry
def _execute_signal(self, signal: SignalType) -> None:
    if signal == SignalType.BUY and self.is_short:
        self._close_position()
        self._go_long()  # Immediate entry
```

### Git Intelligence (Recent Commits)

From commit `e8f291f` (Story 2.8):
- Implemented MA Crossover Strategy
- Added position reversal with immediate re-entry
- 31 unit tests for strategy, 524+ total tests passing

**Pattern Continuity:**
- Signal filtering uses same logging pattern as strategies
- Unit tests follow same Mock-based approach
- Code style follows existing ruff configuration

### Environment Variables Required

```bash
# Trading Engine (already configured from previous stories)
REDIS_URL=redis://localhost:6379
LOG_LEVEL=DEBUG  # Set to DEBUG to see filtered signals
```

### Dependencies (pyproject.toml - Already Configured)

```toml
dependencies = [
    "nautilus_trader>=1.200",
    "redis>=5.0",
    "pyzmq>=25.0",
    "pydantic>=2.0",
    "pydantic-settings>=2.0",
]
```

### Project Structure Notes

- Primarily modifying existing `data_router.py` to add DEBUG logging
- Optionally create `signal_router.py` in accounts/ for Epic 3 preparation
- All tests follow existing patterns in `tests/unit/`
- Minimal new code needed - most functionality already exists

### References

- [Source: docs/architecture.md#Trading-Engine-Service] - Signal routing architecture
- [Source: docs/epic-2-context.md#Story-2.9] - Signal filtering technical context
- [Source: docs/epics.md#Story-2.9] - Original story definition and acceptance criteria
- [Source: docs/sprint-artifacts/2-8-ma-crossover-strategy-implementation.md] - Previous story patterns
- [Source: Context7 NautilusTrader 2025-12-28] - Latest signal filtering and message bus patterns
- [Source: services/trading-engine/src/strategies/data_router.py] - Existing implementation (COMPLETE)
- [Source: services/trading-engine/tests/unit/test_data_router.py] - Existing tests (14 tests)

## Dev Agent Record

### Context Reference

- Epic 2 Context: `docs/epic-2-context.md`
- Architecture: `docs/architecture.md`
- Epics: `docs/epics.md`
- Previous Story: `docs/sprint-artifacts/2-8-ma-crossover-strategy-implementation.md`

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A

### Completion Notes List

- Story created with comprehensive analysis of existing codebase
- **KEY FINDING**: Signal filtering is already 90% implemented in `data_router.py`
- Context7 MCP research: NautilusTrader signal/message filtering patterns (2025-12-28)
- 14 unit tests already exist and pass for data routing functionality
- Main remaining work: Add DEBUG logging for filtered signals
- Optionally prepare `signal_router.py` for Epic 3 multi-account expansion
- **IMPLEMENTATION COMPLETE (2025-12-28)**:
  - Added `id: str` to `HasStrategy` protocol for type-safe account identification
  - Enhanced `_should_route_to_account()` with DEBUG logging for filtered signals
  - Added comprehensive module docstring documenting integration pattern with RedisAdapter
  - Added 8 new unit tests (14 → 22 total) achieving 100% code coverage
  - Created 9 integration tests using real `AccountConfig` and `BoundAccount` models
  - All 546 unit tests pass (9 Redis integration tests skipped without Redis), 31 signal filtering tests pass

### File List

**Files Modified:**
- `services/trading-engine/src/strategies/data_router.py` - Added DEBUG logging, updated HasStrategy protocol with `id`, enhanced module docstring
- `services/trading-engine/tests/unit/test_data_router.py` - Added 8 new tests for DEBUG logging, tick routing, and callback getters
- `services/trading-engine/pyproject.toml` - Added pytest-cov for coverage testing
- `services/trading-engine/uv.lock` - Updated lockfile with pytest-cov dependency
- `docs/sprint-artifacts/sprint-status.yaml` - Updated sprint status tracking

**Files Created:**
- `services/trading-engine/tests/integration/test_signal_filtering_integration.py` - 9 integration tests with real models
- `docs/sprint-artifacts/2-9-signal-filtering-by-symbol.md` - This story file

**Tests Summary:**
- Unit tests: 22 tests in `test_data_router.py`
- Integration tests: 9 tests in `test_signal_filtering_integration.py`
- Total: 31 signal filtering tests, all passing
- Coverage: 100% on `data_router.py`

---

## Verification Checklist

### Manual Test Steps

```bash
# 1. Ensure you're in the trading-engine directory
cd services/trading-engine

# 2. Install dependencies
uv sync

# 3. Run existing data router tests (should all pass)
uv run pytest tests/unit/test_data_router.py -v

# 4. Check code quality
uv run ruff check src/strategies/data_router.py

# 5. Run all tests to verify no regressions
uv run pytest -v
```

### Acceptance Criteria Verification

- [x] **AC1**: Bar for allowed symbol (XAUUSD) is processed - verified by `test_account_config_with_symbol_filter_routes_matching_bar`
- [x] **AC2**: Bar for non-allowed symbol (BTCUSD) is ignored - verified by `test_account_config_with_symbol_filter_ignores_non_matching_bar`
- [x] **AC3**: Multiple allowed symbols all work - verified by `test_account_config_with_multiple_symbols`
- [x] **AC4**: Filtered signals log at DEBUG level - verified by `test_logs_debug_when_symbol_filtered` and `test_filtered_signal_logs_debug`
- [x] **AC5**: Case-insensitive matching works - verified by `test_case_insensitive_symbol_matching` and `test_symbol_matching_case_insensitive`
- [x] **AC6**: Empty filter allows all symbols - verified by `test_empty_symbol_filter_allows_all` and `test_default_signal_filter_allows_all`
- [x] **AC7**: Unit tests have >90% coverage - **100% coverage achieved**

---

## Definition of Done

- [x] `data_router.py` logs DEBUG when signals are filtered out
- [x] All 22 unit tests pass (expanded from original 14)
- [x] New tests for DEBUG logging added (2 unit tests + 9 integration tests)
- [x] Code quality passes: `uv run ruff check src/strategies/` - All checks passed!
- [x] Story status updated to `done` after code review

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-28 | Story created by create-story workflow using Context7 MCP for NautilusTrader research |
| 2025-12-28 | Analyzed existing codebase - found signal filtering already 90% implemented |
| 2025-12-28 | Documented existing `StrategyDataRouter` implementation and 14 unit tests |
| 2025-12-28 | Identified remaining work: DEBUG logging enhancement |
| 2025-12-28 | **Story Validation (validate-create-story)**: Fixed test count (24→14), clarified verification vs implementation marks, added account.id verification task, added integration test paths, clarified Task 3 as optional Epic 3 prep, added NautilusTrader section clarification |
| 2025-12-28 | **Implementation Complete**: Added DEBUG logging to `_should_route_to_account()`, updated `HasStrategy` protocol with `id` attribute, enhanced module docstring with integration pattern documentation |
| 2025-12-28 | **Tests Complete**: Added 8 new unit tests (22 total), created 9 integration tests, achieved 100% code coverage |
| 2025-12-28 | **Story marked Ready for Review**: All ACs verified, Definition of Done satisfied (pending code review) |
| 2025-12-28 | **Code Review Complete**: Fixed log message "bar"→"data" for tick/bar consistency, updated test count 535→546, added missing files to File List (uv.lock, sprint-status.yaml), status updated to Done |
