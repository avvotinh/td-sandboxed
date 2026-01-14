# Story 6.3: Trade Execution Notifications

Status: In Progress

## Story

As a **trader**,
I want **to receive Telegram notifications when trades execute**,
So that **I know what my accounts are doing**.

## Acceptance Criteria

1. **Given** a trade is executed on an account
   **When** the trading engine publishes to `alerts:trade:{account_id}`
   **Then** the notification service formats and sends:
   ```
   🔵 TRADE EXECUTED
   Account: FTMO Gold Challenge
   Symbol: XAUUSD
   Action: BUY 0.10 lots
   Entry: $1,850.25
   SL: $1,845.00 | TP: $1,860.00
   Reason: MA crossover (20/50 SMA)
   Daily P&L: -$350.00 (-0.35%)
   Time: 14:32:15 UTC
   ```

2. **Given** a trade is closed
   **When** the close event is published
   **Then** the notification includes P&L result:
   ```
   🟢 TRADE CLOSED - PROFIT
   Account: FTMO Gold Challenge
   Symbol: XAUUSD
   Action: SELL 0.10 lots (close)
   Entry: $1,850.25 → Exit: $1,858.50
   P&L: +$82.50
   Daily P&L: -$267.50 (-0.27%)
   ```
   **Or** for a loss:
   ```
   🔴 TRADE CLOSED - LOSS
   Account: FTMO Gold Challenge
   Symbol: XAUUSD
   Action: SELL 0.10 lots (close)
   Entry: $1,850.25 → Exit: $1,842.00
   P&L: -$82.50
   Daily P&L: -$432.50 (-0.43%)
   ```

3. **Given** notification sending fails
   **When** Telegram API is unavailable
   **Then** the message is queued for retry
   **And** trading is NOT affected (fire-and-forget)

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 4 (Errors) → Task 1 (Handler) → Task 2 (Formatter) → Task 3 (Queue) → Task 5 (Tests)
```

- [x] Task 1: Implement JSON Parsing in TradeHandler (AC: #1, #2)
  - **PREREQUISITE:** Complete Task 4 first (error types required for compilation)
  - [x] 1.1: Define `TradeOpenEvent` struct for incoming JSON payloads in `trade_handler.go`
  - [x] 1.2: Define `TradeCloseEvent` struct for close event JSON payloads
  - [x] 1.3: Add JSON unmarshalling logic in `Handle()` method to parse `payload []byte`
  - [x] 1.4: Detect event type from JSON `type` field (e.g., `trade_opened`, `trade_closed`)
  - [x] 1.5: Route to appropriate formatter method based on event type

- [x] Task 2: Enhance TradeFormatter with Emoji and Markdown (AC: #1, #2)
  - [x] 2.1: Update `FormatOpen()` to use 🔵 emoji and proper markdown formatting
  - [x] 2.2: Update `FormatClose()` to use 🟢 (PROFIT) or 🔴 (LOSS) emoji
  - [x] 2.3: Add entry → exit price display format for close events
  - [x] 2.4: Format money values with proper currency symbols and signs
  - [x] 2.5: Add timestamp formatting in UTC
  - [x] 2.6: Use Markdown parse mode for bold text (*TRADE EXECUTED*, *TRADE CLOSED*)

- [x] Task 3: Implement Fire-and-Forget with Retry Queue (AC: #3) **[OPTIONAL - Router already has fire-and-forget]**
  - **NOTE:** Router already wraps `SendMessage` in goroutine (fire-and-forget). This task adds *persistent* retry for API outages. Skip for MVP if time-constrained.
  - [x] 3.1: Create `MessageQueue` struct in new file `internal/queue/message_queue.go`
  - [x] 3.2: Implement background goroutine for queue processing
  - [x] 3.3: Add retry logic with max 3 attempts and exponential backoff
  - [x] 3.4: Log failed messages but NEVER block trading operations
  - [ ] 3.5: Update Router to use queue for message delivery (Router retains existing fire-and-forget goroutine; queue available for future integration)

- [x] Task 4: Add Error Types for Handler Errors **[DO FIRST]**
  - [x] 4.1: Add `ErrInvalidTradeEvent` to `errors.go`
  - [x] 4.2: Add `ErrUnknownEventType` to `errors.go`

- [x] Task 5: Add Unit and Integration Tests
  - [x] 5.1: Unit tests for JSON parsing of trade open events
  - [x] 5.2: Unit tests for JSON parsing of trade close events
  - [x] 5.3: Unit tests for `FormatOpen()` output matching AC format
  - [x] 5.4: Unit tests for `FormatClose()` with PROFIT and LOSS scenarios
  - [x] 5.5: Unit tests for invalid JSON handling (graceful error)
  - [x] 5.6: Integration test: publish trade event to Redis, verify Telegram output
  - [x] 5.7: Test fire-and-forget behavior: ensure handler returns immediately

### Review Follow-ups (AI)

- [ ] [AI-Review][HIGH] Complete Task 3.5: Integrate MessageQueue into Router for AC#3 compliance. Queue exists but is unused dead code. Router still logs and drops failed messages. [redis_subscriber.go:79-84]
- [ ] [AI-Review][MEDIUM] Add integration test verifying queue retry behavior once Task 3.5 complete [tests/integration_test.go]

## Dev Notes

### Architecture Compliance

**Service:** `services/notification/` (Go 1.23+)
**Purpose:** Alert and notification delivery via Telegram

**CRITICAL CONSTRAINTS from Architecture:**
- **NEVER block trading operations on notification failure** - This is the #1 rule
- Fire-and-forget pattern for alerts (Router already uses goroutine for `SendMessage`)
- Use existing retry patterns from Story 6.1 for Telegram API errors
- Handlers return formatted strings, Router handles notification delivery

### Existing Scaffold Analysis (Story 6.2)

**Already Implemented:**
- `TradeHandler` struct in `internal/handlers/trade_handler.go` (lines 12-31)
- `TradeFormatter` in `internal/formatters/trade_formatter.go` with `FormatOpen()` and `FormatClose()`
- `TradeEvent` and `TradeCloseEvent` structs defined in formatter (lines 11-34)
- Router message routing to `tradeHandler.Handle()` (lines 50-57 in redis_subscriber.go)
- `Notifier` interface and fire-and-forget goroutine in Router (lines 79-84)

**Needs Implementation for Story 6.3:**
- `TradeHandler.Handle()` currently returns empty string (scaffold) - needs JSON parsing
- `TradeFormatter.FormatOpen()` missing emoji (🔵) and proper money formatting
- `TradeFormatter.FormatClose()` has hardcoded timestamp instead of event timestamp
- No retry queue for failed Telegram sends (currently silently logs errors)

### JSON Message Formats (from Architecture & Story 6.2)

**Trade Open Event** (published to `alerts:trade:{account_id}`):
```json
{
  "type": "trade_opened",
  "account_id": "ftmo-gold-001",
  "account_name": "FTMO Gold Challenge",
  "symbol": "XAUUSD",
  "action": "BUY",
  "volume": 0.10,
  "price": 1850.25,
  "sl": 1845.00,
  "tp": 1860.00,
  "reason": "MA crossover (20/50 SMA)",
  "daily_pnl": -350.00,
  "daily_pnl_pct": -0.35,
  "timestamp": "2026-01-15T14:32:15Z"
}
```

**Trade Close Event** (published to `alerts:trade:{account_id}`):
```json
{
  "type": "trade_closed",
  "account_id": "ftmo-gold-001",
  "account_name": "FTMO Gold Challenge",
  "symbol": "XAUUSD",
  "action": "SELL",
  "volume": 0.10,
  "entry_price": 1850.25,
  "exit_price": 1858.50,
  "pnl": 82.50,
  "pnl_pct": 0.45,
  "result": "PROFIT",
  "duration": "2h 15m",
  "daily_pnl": -267.50,
  "daily_pnl_pct": -0.27,
  "timestamp": "2026-01-15T16:47:30Z"
}
```

### Library Versions and API (from Context7 Research)

**go-telegram-bot-api v5.5.1** (via `/ovyflash/telegram-bot-api`)

```go
// Markdown formatting for messages
msg := api.NewMessage(chatID, "*Bold text* and _italic text_")
msg.ParseMode = api.ModeMarkdown  // Use for bold headers like *TRADE EXECUTED*
bot.Send(msg)

// API error handling with retry
_, err = bot.Send(msg)
if err != nil {
    if apiErr, ok := err.(*api.Error); ok {
        log.Printf("API Error Code: %d", apiErr.Code)
        if apiErr.RetryAfter != 0 {
            time.Sleep(time.Duration(apiErr.RetryAfter) * time.Second)
            // Retry the send
        }
    }
}
```

**go-redis v9.17.2** (via `/redis/go-redis`)

```go
// Pub/Sub message contains JSON payload
for msg := range ch {
    // msg.Channel = "alerts:trade:ftmo-gold-001"
    // msg.Payload = JSON string to parse

    var event TradeOpenEvent
    if err := json.Unmarshal([]byte(msg.Payload), &event); err != nil {
        log.Printf("JSON parse error: %v", err)
        continue
    }
}
```

### Implementation Guide

**Step 0: Add Error Types FIRST** (`internal/errors/errors.go`)

Add these error types before implementing TradeHandler (required for compilation):

```go
// Add to sentinel errors section in errors.go:

// ErrInvalidTradeEvent indicates the trade event payload is malformed.
ErrInvalidTradeEvent = errors.New("invalid trade event payload")

// ErrUnknownEventType indicates an unrecognized event type in the payload.
ErrUnknownEventType = errors.New("unknown event type")
```

**Step 1: Update TradeHandler** (`internal/handlers/trade_handler.go`)

```go
package handlers

import (
    "encoding/json"
    "log"

    "github.com/user/sandboxed/services/notification/internal/errors"
    "github.com/user/sandboxed/services/notification/internal/formatters"
)

// TradeHandler processes trade execution events.
type TradeHandler struct {
    formatter *formatters.TradeFormatter
}

// NewTradeHandler creates a new trade handler.
func NewTradeHandler() *TradeHandler {
    return &TradeHandler{
        formatter: formatters.NewTradeFormatter(),
    }
}

// baseTradeEvent contains the type field for routing
type baseTradeEvent struct {
    Type string `json:"type"`
}

// Handle processes a trade event message and returns formatted notification text.
func (h *TradeHandler) Handle(accountID string, payload []byte) (string, error) {
    // First, determine event type
    var base baseTradeEvent
    if err := json.Unmarshal(payload, &base); err != nil {
        log.Printf("Failed to parse trade event base: %v", err)
        return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
    }

    switch base.Type {
    case "trade_opened":
        var event formatters.TradeEvent
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        return h.formatter.FormatOpen(&event), nil

    case "trade_closed":
        var event formatters.TradeCloseEvent
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        return h.formatter.FormatClose(&event), nil

    default:
        log.Printf("Unknown trade event type: %s", base.Type)
        return "", errors.Wrap("Handle", errors.ErrUnknownEventType, base.Type)
    }
}
```

**Step 2: Update TradeFormatter** (`internal/formatters/trade_formatter.go`)

```go
// FormatOpen formats a trade open notification with emoji.
func (f *TradeFormatter) FormatOpen(e *TradeEvent) string {
    return fmt.Sprintf(`🔵 *TRADE EXECUTED*
Account: %s
Symbol: %s
Action: %s %.2f lots
Entry: $%.2f
SL: $%.2f | TP: $%.2f
Reason: %s
Daily P&L: %s (%.2f%%)
Time: %s`,
        e.AccountName,
        e.Symbol,
        e.Action, e.Volume,
        e.Price,
        e.SL, e.TP,
        e.Reason,
        formatMoney(e.DailyPnL), e.DailyPnLPct,
        formatTimestamp(e.Timestamp))
}

// FormatClose formats a trade close notification with result emoji.
func (f *TradeFormatter) FormatClose(e *TradeCloseEvent) string {
    emoji := "🔴"
    if e.Result == "PROFIT" {
        emoji = "🟢"
    }

    return fmt.Sprintf(`%s *TRADE CLOSED - %s*
Account: %s
Symbol: %s
Action: %s %.2f lots (close)
Entry: $%.2f → Exit: $%.2f
P&L: %s
Daily P&L: %s (%.2f%%)`,
        emoji, e.Result,
        e.AccountName,
        e.Symbol,
        e.Action, e.Volume,
        e.EntryPrice, e.ExitPrice,
        formatMoneyWithSign(e.PnL),
        formatMoney(e.DailyPnL), e.DailyPnLPct)
}

// formatMoney formats a money value with dollar sign and proper negative handling
func formatMoney(value float64) string {
    if value < 0 {
        return fmt.Sprintf("-$%.2f", -value)
    }
    return fmt.Sprintf("$%.2f", value)
}

// formatMoneyWithSign formats money with explicit + or - sign
func formatMoneyWithSign(value float64) string {
    if value >= 0 {
        return fmt.Sprintf("+$%.2f", value)
    }
    return fmt.Sprintf("-$%.2f", -value)
}

// formatTimestamp formats ISO timestamp to readable UTC format
func formatTimestamp(ts string) string {
    t, err := time.Parse(time.RFC3339, ts)
    if err != nil {
        return ts // Return original if parse fails
    }
    return t.UTC().Format("15:04:05 UTC")
}
```

**Step 3: Update Event Structs** (`internal/formatters/trade_formatter.go`)

The existing code uses embedding (`TradeCloseEvent` embeds `TradeEvent`). You have two options:

**Option A (Recommended): Update existing embedded structs**
```go
// TradeEvent - ADD Type field to existing struct
type TradeEvent struct {
    Type        string  `json:"type"`         // NEW: for event type routing
    AccountID   string  `json:"account_id"`
    AccountName string  `json:"account_name"`
    Symbol      string  `json:"symbol"`
    Action      string  `json:"action"`
    Volume      float64 `json:"volume"`
    Price       float64 `json:"price"`
    SL          float64 `json:"sl,omitempty"`
    TP          float64 `json:"tp,omitempty"`
    Reason      string  `json:"reason"`
    DailyPnL    float64 `json:"daily_pnl"`
    DailyPnLPct float64 `json:"daily_pnl_pct"`
    Timestamp   string  `json:"timestamp"`
}

// TradeCloseEvent - REPLACE embedded struct with flat struct for close-specific fields
type TradeCloseEvent struct {
    Type        string  `json:"type"`
    AccountID   string  `json:"account_id"`
    AccountName string  `json:"account_name"`
    Symbol      string  `json:"symbol"`
    Action      string  `json:"action"`
    Volume      float64 `json:"volume"`
    EntryPrice  float64 `json:"entry_price"`  // Different from TradeEvent.Price
    ExitPrice   float64 `json:"exit_price"`   // Close-specific
    PnL         float64 `json:"pnl"`
    PnLPct      float64 `json:"pnl_pct"`
    Result      string  `json:"result"`       // "PROFIT" or "LOSS"
    Duration    string  `json:"duration"`
    DailyPnL    float64 `json:"daily_pnl"`
    DailyPnLPct float64 `json:"daily_pnl_pct"`
    Timestamp   string  `json:"timestamp"`
}
```

**Why flat struct for TradeCloseEvent:** The close event has `entry_price`/`exit_price` instead of single `price`, so embedding doesn't fit cleanly. Flat struct is cleaner.

### Project Structure Notes

**File Locations (DO NOT create new directories):**
```
services/notification/
├── internal/
│   ├── handlers/
│   │   ├── trade_handler.go         # MODIFY: Full implementation
│   │   └── handlers_test.go         # MODIFY: Add trade event tests
│   ├── formatters/
│   │   ├── trade_formatter.go       # MODIFY: Add emoji, money formatting
│   │   └── trade_formatter_test.go  # MODIFY: Update format tests
│   ├── errors/
│   │   └── errors.go                # MODIFY: Add new error types
│   └── queue/
│       └── message_queue.go         # NEW: Optional retry queue
├── tests/
│   └── integration_test.go          # MODIFY: Add trade notification test
```

**Files to Modify (NOT create):**
- `internal/handlers/trade_handler.go` - Full JSON parsing implementation
- `internal/formatters/trade_formatter.go` - Emoji and money formatting
- `internal/handlers/handlers_test.go` - Add tests for new functionality
- `internal/formatters/trade_formatter_test.go` - Update format output tests
- `internal/errors/errors.go` - Add `ErrInvalidTradeEvent`, `ErrUnknownEventType`

### Environment Variables (from config.go)

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | No | - | Target chat for alerts |
| `REDIS_URL` | No | `redis:6379` | Redis server address |

### Testing Standards

- Unit tests: `*_test.go` files alongside source
- Integration tests: `tests/integration_test.go`
- Run: `cd services/notification && go test ./...`
- Race detection: `go test -race ./...`
- Test JSON parsing edge cases (missing fields, null values, invalid types)

### Previous Story Intelligence (Story 6.1, 6.2)

**Key Patterns Established:**
- Exponential backoff: `bot.go:64-104` - `connectWithRetry()` pattern
- Fire-and-forget: `redis_subscriber.go:79-84` - Goroutine for notification sending
- Handler signature: `Handle(accountID string, payload []byte) (string, error)`
- Error wrapping: Use `errors.Wrap()` from internal errors package
- Context-aware operations for graceful shutdown

**Story 6.1 Learnings:**
- Cached health checks with 30s TTL instead of API call every time
- Context parameter for graceful shutdown during retry loops
- Test coverage for both unit and integration scenarios

**Story 6.2 Learnings:**
- Router routes to handlers and uses goroutine for SendMessage (fire-and-forget)
- Handlers return empty string to skip notification (current scaffold behavior)
- Pattern matching extracts account ID from channel name
- Thread-safe subscriber access via mutex

### Git Intelligence

Recent commits (last 2):
- `7599c46` - Implement spec 6 story 6.2 (Redis alert subscription)
- `3c9ac0c` - Implement spec 6 story 6.1 (Notification service setup)

**Pattern:** Each story modifies existing files, adds tests, follows acceptance criteria format.

### Critical Implementation Notes

1. **Fire-and-Forget is NON-NEGOTIABLE**: Router already wraps `SendMessage` in goroutine. DO NOT add synchronous calls that could block.

2. **JSON Parsing Must Be Defensive**: Trading engine may send malformed events during development. Always log and continue, never crash.

3. **Emoji Must Be Unicode**: Use actual emoji characters (🔵, 🟢, 🔴) not escape codes. They display correctly in Telegram.

4. **Markdown Parse Mode**: Set `msg.ParseMode = api.ModeMarkdown` for bold text (`*TRADE EXECUTED*`).

5. **Money Formatting**: Negative values should show as `-$350.00` not `$-350.00`.

6. **Timestamp Handling**: Parse ISO 8601 timestamp from JSON, format to `HH:MM:SS UTC` for display.

7. **DO NOT modify Router or Subscriber**: Story 6.2 already handles routing. Only implement TradeHandler logic.

### References

- [Source: docs/architecture.md#Notification Service (Go)]
- [Source: docs/epics.md#Story 6.3]
- [Source: services/notification/internal/handlers/trade_handler.go - existing scaffold]
- [Source: services/notification/internal/formatters/trade_formatter.go - existing formatter]
- [Source: docs/sprint-artifacts/6-2-redis-alert-subscription.md - previous story patterns]
- [Source: Context7 - go-telegram-bot-api v5.5.1 Markdown and error handling]
- [Source: Context7 - go-redis v9.17.2 Pub/Sub message handling]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- `go-telegram-bot-api` v5.5.1 - Markdown formatting, API error handling with retry
- `go-redis` v9.17.2 - Pub/Sub message handling and JSON payload parsing

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - No debug issues encountered during implementation.

### Completion Notes List

Story context created with:
- Full acceptance criteria from epics.md
- JSON message formats for trade events
- Implementation guide with code examples
- Previous story intelligence from 6.1 and 6.2
- Context7 research for latest library documentation
- Critical implementation notes to prevent common mistakes

**Validation Applied (2026-01-15):**
- Added task dependency graph and ordering notes
- Added error type definitions to Implementation Guide (Step 0)
- Added `Type` field to TradeEvent struct
- Clarified TradeCloseEvent struct pattern (flat vs embedded)
- Marked Task 3 (Retry Queue) as OPTIONAL
- Marked Task 4 (Error Types) as DO FIRST prerequisite

**Implementation Completed (2026-01-15):**
- Implemented full JSON parsing for trade_opened and trade_closed events
- Added emoji formatting (🔵 for open, 🟢/🔴 for profit/loss)
- Implemented proper money formatting (-$350.00, +$82.50)
- Added ISO 8601 timestamp parsing to HH:MM:SS UTC format
- Created MessageQueue with retry logic (exponential backoff, max 3 attempts)
- All 60+ tests passing including unit and integration tests
- Fire-and-forget behavior verified (Router returns immediately)
- AC#1, AC#2 satisfied
- AC#3 PARTIAL: MessageQueue built but NOT integrated into Router (Task 3.5 incomplete)

**Code Review Fixes (2026-01-15):**
- Removed duplicate TradeOpenEvent/TradeCloseEvent structs from trade_handler.go (DRY violation fix)
- Added missing Time field to FormatClose() output for consistency with FormatOpen()
- Handler now uses formatter types directly, eliminating 50+ lines of conversion code

### File List

**Modified:**
- `services/notification/internal/handlers/trade_handler.go` - Full JSON parsing implementation
- `services/notification/internal/formatters/trade_formatter.go` - Emoji, money formatting, timestamp parsing
- `services/notification/internal/handlers/handlers_test.go` - 15 new trade handler tests
- `services/notification/internal/formatters/trade_formatter_test.go` - 12 formatter tests with AC validation
- `services/notification/internal/errors/errors.go` - Added ErrInvalidTradeEvent, ErrUnknownEventType
- `services/notification/tests/integration_test.go` - Router integration tests for trade notifications

**New:**
- `services/notification/internal/queue/message_queue.go` - Retry queue with exponential backoff
- `services/notification/internal/queue/message_queue_test.go` - 8 queue tests

### Change Log

- **2026-01-15**: Implemented Story 6.3 Trade Execution Notifications
  - JSON parsing for trade open/close events
  - Emoji and markdown formatting for Telegram
  - Money formatting with proper signs
  - MessageQueue with retry for failed sends
  - Comprehensive test coverage (60+ tests passing)
