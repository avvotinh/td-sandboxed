# Story 6.4: Rule Violation Alerts

Status: review

## Story

As a **trader**,
I want **to receive alerts when rules are violated**,
So that **I know when and why trades were blocked**.

## Acceptance Criteria

1. **Given** a trade is blocked by a rule
   **When** the trading engine publishes to `alerts:risk:{account_id}`
   **Then** the notification service sends:
   ```
   🔴 TRADE BLOCKED
   Account: FTMO Gold Challenge
   Rule: Daily Loss Limit
   Current: 4.8% of 5.0% limit
   Trade: BUY 0.10 XAUUSD
   Reason: Trade would exceed daily loss limit
   Action: Trade rejected
   Time: 14:32:15 UTC
   ```

2. **Given** a warning threshold is reached
   **When** the warning event is published
   **Then** the notification shows:
   ```
   🟡 RISK WARNING
   Account: FTMO Gold Challenge
   Rule: Daily Loss Limit
   Status: 80% of limit reached
   Current: 4.0% of 5.0% limit
   Remaining: $1,000 (1.0%)
   Action: Trading continues, monitor closely
   Time: 14:32:15 UTC
   ```

3. **Given** max drawdown limit is reached
   **When** the violation event is published
   **Then** the notification shows:
   ```
   🔴 TRADING HALTED
   Account: FTMO Gold Challenge
   Rule: Max Drawdown
   Status: 10% limit reached
   Action: All trading paused for this account
   Required: Manual review before resuming
   Time: 14:32:15 UTC
   ```

4. **Given** notification sending fails
   **When** Telegram API is unavailable
   **Then** the message is queued for retry
   **And** trading is NOT affected (fire-and-forget)

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (Event Structs) → Task 2 (RiskHandler) → Task 3 (Formatter) → Task 4 (Tests)
```

- [x] Task 1: Define Risk Event Structs (AC: #1, #2, #3)
  - [x] 1.1: Add `RiskBlockedEvent` struct to `alert_formatter.go` with all required JSON fields
  - [x] 1.2: Add `RiskWarningEvent` struct to `alert_formatter.go` with all required JSON fields (include `RemainingDollars` field)
  - [x] 1.3: Add `TradingHaltedEvent` struct to `alert_formatter.go` for max drawdown halt notifications
  - [x] 1.4: Add `baseRiskEvent` struct for event type routing (similar to trade handler pattern)

- [x] Task 2: Implement RiskHandler JSON Parsing (AC: #1, #2, #3, #4)
  - [x] 2.1: Add JSON unmarshalling in `Handle()` method to parse `payload []byte`
  - [x] 2.2: Detect event type from JSON `type` field (`risk_blocked`, `risk_warning`, `trading_halted`)
  - [x] 2.3: Route to appropriate formatter method based on event type
  - [x] 2.4: Return formatted message string for notification
  - [x] 2.5: Handle invalid JSON gracefully (log and return error)

- [x] Task 3: Enhance AlertFormatter with Emoji and Markdown (AC: #1, #2, #3)
  - [x] 3.1: Update `FormatRiskBlocked()` to use 🔴 emoji and match AC#1 format exactly
  - [x] 3.2: Update `FormatRiskWarning()` to use 🟡 emoji and match AC#2 format exactly (include dollar + percentage remaining, Action line)
  - [x] 3.3: Add `FormatTradingHalted()` method with 🔴 emoji for AC#3 format
  - [x] 3.4: For warnings: use `warning_level` field directly for Status percentage display
  - [x] 3.5: Format remaining as "$X,XXX (Y.Y%)" for warning messages
  - [x] 3.6: Use event timestamp instead of `time.Now()` for accurate time display
  - [ ] 3.7: Extract `formatTimestamp()` to `internal/formatters/utils.go` shared package (reduces duplication with trade_formatter.go) - DEFERRED: kept as `formatAlertTimestamp()` in alert_formatter.go for simplicity

- [x] Task 4: Add Unit and Integration Tests (AC: #1, #2, #3, #4)
  - [x] 4.1: Unit tests for JSON parsing of risk_blocked events
  - [x] 4.2: Unit tests for JSON parsing of risk_warning events
  - [x] 4.3: Unit tests for JSON parsing of trading_halted events
  - [x] 4.4: Unit tests for `FormatRiskBlocked()` output matching AC#1 format
  - [x] 4.5: Unit tests for `FormatRiskWarning()` output matching AC#2 format (verify dollar + percentage)
  - [x] 4.6: Unit tests for `FormatTradingHalted()` output matching AC#3 format
  - [x] 4.7: Unit tests for invalid JSON handling (graceful error)
  - [x] 4.8: Integration test: route risk events via Router, verify formatted output
  - [x] 4.9: Integration test: verify fire-and-forget (Router returns immediately < 5ms)

## Dev Notes

### Architecture Compliance

**Service:** `services/notification/` (Go 1.23+)
**Purpose:** Alert and notification delivery via Telegram

**CRITICAL CONSTRAINTS from Architecture:**
- **NEVER block trading operations on notification failure** - This is the #1 rule
- Fire-and-forget pattern for alerts (Router already uses goroutine for `SendMessage`)
- Use existing retry patterns from Story 6.1 for Telegram API errors
- Handlers return formatted strings, Router handles notification delivery
- Risk alerts use `alerts:risk:{account_id}` channel (already subscribed in Story 6.2)

### Existing Scaffold Analysis (Story 6.2, 6.3)

**Already Implemented:**
- `RiskHandler` struct in `internal/handlers/risk_handler.go` (scaffold with empty Handle)
- `AlertFormatter` in `internal/formatters/alert_formatter.go` with `FormatRiskWarning()` and `FormatRiskBlocked()`
- `RiskAlert` struct defined in alert_formatter.go (lines 12-24)
- Router message routing to `riskHandler.Handle()` in redis_subscriber.go
- `Notifier` interface and fire-and-forget goroutine in Router

**Needs Implementation for Story 6.4:**
- `RiskHandler.Handle()` currently returns empty string - needs full JSON parsing for 3 event types
- `AlertFormatter.FormatRiskBlocked()` needs 🔴 emoji (currently no emoji)
- `AlertFormatter.FormatRiskWarning()` needs 🟡 emoji (currently no emoji), plus dollar amount and Action line
- `AlertFormatter.FormatTradingHalted()` needs to be added (new method for AC#3)
- All formatters use `time.Now()` instead of event timestamp
- Need event type detection for routing between blocked/warning/halted

### JSON Message Formats (from Architecture & Epics)

**Risk Blocked Event** (published to `alerts:risk:{account_id}`):
```json
{
  "type": "risk_blocked",
  "account_id": "ftmo-gold-001",
  "account_name": "FTMO Gold Challenge",
  "rule_name": "Daily Loss Limit",
  "rule_type": "blocked",
  "current": 4.8,
  "threshold": 5.0,
  "trade": "BUY 0.10 XAUUSD",
  "reason": "Trade would exceed daily loss limit",
  "action": "Trade rejected",
  "timestamp": "2026-01-15T14:32:15Z"
}
```

**Risk Warning Event** (published to `alerts:risk:{account_id}`):
```json
{
  "type": "risk_warning",
  "account_id": "ftmo-gold-001",
  "account_name": "FTMO Gold Challenge",
  "rule_name": "Daily Loss Limit",
  "rule_type": "warning",
  "current": 4.0,
  "threshold": 5.0,
  "warning_level": 80,
  "remaining_dollars": 1000.00,
  "action": "Trading continues, monitor closely",
  "timestamp": "2026-01-15T14:32:15Z"
}
```

**Trading Halted Event** (published to `alerts:risk:{account_id}`):
```json
{
  "type": "trading_halted",
  "account_id": "ftmo-gold-001",
  "account_name": "FTMO Gold Challenge",
  "rule_name": "Max Drawdown",
  "rule_type": "halted",
  "status": "10% limit reached",
  "action": "All trading paused for this account",
  "required_action": "Manual review before resuming",
  "timestamp": "2026-01-15T14:32:15Z"
}
```

### Library Versions and API (from Context7 Research)

**go-telegram-bot-api v5.5.1** (via `/ovyflash/telegram-bot-api`)

```go
// Markdown formatting for messages
msg := api.NewMessage(chatID, "*Bold text* and _italic text_")
msg.ParseMode = api.ModeMarkdown  // Use for bold headers like *TRADE BLOCKED*
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
// Pattern subscription for risk alerts (already implemented in Story 6.2)
pubsub := rdb.PSubscribe(ctx, "alerts:risk:*")
for msg := range ch {
    // msg.Channel = "alerts:risk:ftmo-gold-001"
    // msg.Payload = JSON string to parse

    var event RiskBlockedEvent
    if err := json.Unmarshal([]byte(msg.Payload), &event); err != nil {
        log.Printf("JSON parse error: %v", err)
        continue
    }
}
```

### Implementation Guide

**Step 1: Update Event Structs** (`internal/formatters/alert_formatter.go`)

The existing `RiskAlert` struct can be reused, but add `Type` field for routing and `WarningLevel` for percentage display:

```go
// RiskBlockedEvent represents a trade blocked by risk rule.
type RiskBlockedEvent struct {
    Type        string  `json:"type"`          // "risk_blocked"
    AccountID   string  `json:"account_id"`
    AccountName string  `json:"account_name"`
    RuleName    string  `json:"rule_name"`
    RuleType    string  `json:"rule_type"`     // "blocked"
    Current     float64 `json:"current"`
    Threshold   float64 `json:"threshold"`
    Trade       string  `json:"trade"`
    Reason      string  `json:"reason"`
    Action      string  `json:"action"`
    Timestamp   string  `json:"timestamp"`
}

// RiskWarningEvent represents a risk warning threshold reached.
type RiskWarningEvent struct {
    Type             string  `json:"type"`              // "risk_warning"
    AccountID        string  `json:"account_id"`
    AccountName      string  `json:"account_name"`
    RuleName         string  `json:"rule_name"`
    RuleType         string  `json:"rule_type"`         // "warning"
    Current          float64 `json:"current"`
    Threshold        float64 `json:"threshold"`
    WarningLevel     int     `json:"warning_level"`     // 80 for 80% of limit (use directly for Status line)
    RemainingDollars float64 `json:"remaining_dollars"` // Dollar amount remaining
    Action           string  `json:"action"`            // "Trading continues, monitor closely"
    Timestamp        string  `json:"timestamp"`
}

// TradingHaltedEvent represents trading halted due to critical limit breach.
type TradingHaltedEvent struct {
    Type           string `json:"type"`            // "trading_halted"
    AccountID      string `json:"account_id"`
    AccountName    string `json:"account_name"`
    RuleName       string `json:"rule_name"`
    RuleType       string `json:"rule_type"`       // "halted"
    Status         string `json:"status"`          // "10% limit reached"
    Action         string `json:"action"`          // "All trading paused for this account"
    RequiredAction string `json:"required_action"` // "Manual review before resuming"
    Timestamp      string `json:"timestamp"`
}
```

**Step 2: Update RiskHandler** (`internal/handlers/risk_handler.go`)

Follow the same pattern as TradeHandler from Story 6.3:

```go
package handlers

import (
    "encoding/json"
    "log"

    "github.com/user/sandboxed/services/notification/internal/errors"
    "github.com/user/sandboxed/services/notification/internal/formatters"
)

// RiskHandler processes risk alert events.
type RiskHandler struct {
    formatter *formatters.AlertFormatter
}

// NewRiskHandler creates a new risk handler.
func NewRiskHandler() *RiskHandler {
    return &RiskHandler{
        formatter: formatters.NewAlertFormatter(),
    }
}

// baseRiskEvent contains the type field for routing.
type baseRiskEvent struct {
    Type string `json:"type"`
}

// Handle processes a risk alert message and returns formatted notification text.
func (h *RiskHandler) Handle(accountID string, payload []byte) (string, error) {
    // First, determine event type
    var base baseRiskEvent
    if err := json.Unmarshal(payload, &base); err != nil {
        log.Printf("Failed to parse risk event base: %v", err)
        return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
    }

    switch base.Type {
    case "risk_blocked":
        var event formatters.RiskBlockedEvent
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        return h.formatter.FormatRiskBlocked(&event), nil

    case "risk_warning":
        var event formatters.RiskWarningEvent
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        return h.formatter.FormatRiskWarning(&event), nil

    case "trading_halted":
        var event formatters.TradingHaltedEvent
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        return h.formatter.FormatTradingHalted(&event), nil

    default:
        log.Printf("Unknown risk event type: %s", base.Type)
        return "", errors.Wrap("Handle", errors.ErrUnknownEventType, base.Type)
    }
}
```

**Step 3: Update AlertFormatter** (`internal/formatters/alert_formatter.go`)

Update to use new event structs and add emojis:

```go
// FormatRiskBlocked formats a trade blocked alert with emoji.
func (f *AlertFormatter) FormatRiskBlocked(e *RiskBlockedEvent) string {
    return fmt.Sprintf(`🔴 *TRADE BLOCKED*
Account: %s
Rule: %s
Current: %.1f%% of %.1f%% limit
Trade: %s
Reason: %s
Action: %s
Time: %s`,
        e.AccountName,
        e.RuleName,
        e.Current, e.Threshold,
        e.Trade,
        e.Reason,
        e.Action,
        formatTimestamp(e.Timestamp))
}

// FormatRiskWarning formats a risk warning alert with emoji.
// NOTE: Use warning_level directly for Status (not calculated) - this comes from trading engine.
func (f *AlertFormatter) FormatRiskWarning(e *RiskWarningEvent) string {
    remaining := e.Threshold - e.Current

    return fmt.Sprintf(`🟡 *RISK WARNING*
Account: %s
Rule: %s
Status: %d%% of limit reached
Current: %.1f%% of %.1f%% limit
Remaining: $%.0f (%.1f%%)
Action: %s
Time: %s`,
        e.AccountName,
        e.RuleName,
        e.WarningLevel,
        e.Current, e.Threshold,
        e.RemainingDollars, remaining,
        e.Action,
        formatTimestamp(e.Timestamp))
}

// FormatTradingHalted formats a trading halted alert with emoji.
func (f *AlertFormatter) FormatTradingHalted(e *TradingHaltedEvent) string {
    return fmt.Sprintf(`🔴 *TRADING HALTED*
Account: %s
Rule: %s
Status: %s
Action: %s
Required: %s
Time: %s`,
        e.AccountName,
        e.RuleName,
        e.Status,
        e.Action,
        e.RequiredAction,
        formatTimestamp(e.Timestamp))
}

// formatTimestamp formats ISO timestamp to readable UTC format.
// RECOMMENDATION: Extract to internal/formatters/utils.go to share with trade_formatter.go
func formatTimestamp(ts string) string {
    t, err := time.Parse(time.RFC3339, ts)
    if err != nil {
        return ts
    }
    return t.UTC().Format("15:04:05 UTC")
}
```

### Project Structure Notes

**File Locations (DO NOT create new directories):**
```
services/notification/
├── internal/
│   ├── handlers/
│   │   ├── risk_handler.go           # MODIFY: Full implementation with trading_halted
│   │   └── handlers_test.go          # MODIFY: Add risk event tests (3 event types)
│   ├── formatters/
│   │   ├── alert_formatter.go        # MODIFY: Add emoji, event structs, FormatTradingHalted
│   │   ├── alert_formatter_test.go   # MODIFY: Update format tests for all 3 formats
│   │   └── utils.go                  # NEW: Extract shared formatTimestamp helper
│   └── errors/
│       └── errors.go                 # Already has ErrUnknownEventType from 6.3
├── tests/
│   └── integration_test.go           # MODIFY: Add risk notification + fire-and-forget test
```

**Files to Modify:**
- `internal/handlers/risk_handler.go` - Full JSON parsing implementation (3 event types)
- `internal/formatters/alert_formatter.go` - Add event structs, emoji formatting, FormatTradingHalted
- `internal/handlers/handlers_test.go` - Add tests for new functionality
- `internal/formatters/alert_formatter_test.go` - Update format output tests
- `tests/integration_test.go` - Add risk alert integration test + fire-and-forget verification

**Files to Create:**
- `internal/formatters/utils.go` - Extract `formatTimestamp()` helper (optional but recommended)

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
- Test emoji display (Unicode characters render correctly)

### Previous Story Intelligence (Story 6.1, 6.2, 6.3)

**Key Patterns Established:**
- Exponential backoff: `bot.go:64-104` - `connectWithRetry()` pattern
- Fire-and-forget: `redis_subscriber.go:79-84` - Goroutine for notification sending
- Handler signature: `Handle(accountID string, payload []byte) (string, error)`
- Error wrapping: Use `errors.Wrap()` from internal errors package
- Context-aware operations for graceful shutdown
- JSON event type routing via `type` field in payload

**Story 6.3 Learnings:**
- Use separate event structs for different event types (don't embed)
- Parse `type` field first to route to correct struct
- formatTimestamp helper converts ISO 8601 to "HH:MM:SS UTC" format
- formatMoney/formatMoneyWithSign helpers for currency formatting
- Error types `ErrMessageParseError` and `ErrUnknownEventType` already exist
- Handler returns empty string to skip notification (for invalid events)

**Code Patterns from 6.3:**
```go
// Event type routing pattern
var base baseTradeEvent
json.Unmarshal(payload, &base)
switch base.Type {
case "trade_opened":
    // Parse full event and format
case "trade_closed":
    // Parse full event and format
default:
    // Return error for unknown type
}
```

### Git Intelligence

Recent commits (last 3):
- `b9f2dc5` - Implement spec 6 story 6.3 (Trade execution notifications)
- `7599c46` - Implement spec 6 story 6.2 (Redis alert subscription)
- `3c9ac0c` - Implement spec 6 story 6.1 (Notification service setup)

**Recent file changes in notification service:**
- 16 files modified in recent commits
- 2,422 lines added, 151 deleted
- Major changes: handlers, formatters, queue, subscriber, tests

**Pattern:** Each story modifies existing files, adds tests, follows acceptance criteria format.

### Critical Implementation Notes

1. **Fire-and-Forget is NON-NEGOTIABLE**: Router already wraps `SendMessage` in goroutine. DO NOT add synchronous calls that could block.

2. **JSON Parsing Must Be Defensive**: Trading engine may send malformed events during development. Always log and continue, never crash.

3. **Emoji Must Be Unicode**: Use actual emoji characters (🔴, 🟡) not escape codes. They display correctly in Telegram.

4. **Markdown Parse Mode**: Router already sets `msg.ParseMode = api.ModeMarkdown` for bold text (`*TRADE BLOCKED*`).

5. **Percentage Formatting**: Use `%.1f%%` for percentages (e.g., "4.8% of 5.0%").

6. **Timestamp Handling**: Parse ISO 8601 timestamp from JSON, format to `HH:MM:SS UTC` for display.

7. **Existing AlertFormatter**: Current formatters need parameter type changes to use new event structs.

8. **DO NOT modify Router or Subscriber**: Story 6.2 already handles routing to risk handler. Only implement RiskHandler logic.

9. **Risk Channel Already Subscribed**: `alerts:risk:{account_id}` pattern subscription set up in Story 6.2.

10. **Warning Level Field Usage**: For `risk_warning` events, use `warning_level` directly from JSON for the "Status: X% of limit reached" line. Do NOT calculate from current/threshold - the trading engine provides the authoritative value.

11. **Dollar + Percentage Format**: Warning messages must show both dollar amount AND percentage for Remaining line: `Remaining: $1,000 (1.0%)`

### References

- [Source: docs/architecture.md#Notification Service (Go)]
- [Source: docs/epics.md#Story 6.4]
- [Source: services/notification/internal/handlers/risk_handler.go - existing scaffold]
- [Source: services/notification/internal/formatters/alert_formatter.go - existing formatter]
- [Source: docs/sprint-artifacts/6-3-trade-execution-notifications.md - previous story patterns]
- [Source: Context7 - go-telegram-bot-api v5.5.1 Markdown and error handling]
- [Source: Context7 - go-redis v9.17.2 Pub/Sub pattern subscription]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- `go-telegram-bot-api` v5.5.1 - Markdown formatting, API error handling with retry
- `go-redis` v9.17.2 - PSubscribe pattern matching for channel subscriptions

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Story context creation phase.

### Completion Notes List

Story context created with:
- Full acceptance criteria from epics.md Story 6.4
- JSON message formats for risk_blocked and risk_warning events
- Implementation guide with code examples following 6.3 patterns
- Previous story intelligence from 6.1, 6.2, and 6.3
- Context7 research for latest library documentation
- Critical implementation notes to prevent common mistakes
- Task dependency ordering for optimal implementation flow

**Validation Applied (2026-01-15):**
- Added AC#3 for TRADING HALTED (max drawdown halt notifications)
- Updated AC#2 warning format to include dollar amount and Action line per epics
- Added trading_halted JSON schema and TradingHaltedEvent struct
- Added FormatTradingHalted() method implementation
- Updated RiskHandler to route trading_halted events
- Updated RiskWarningEvent struct with RemainingDollars and Action fields
- Clarified warning_level field usage (use directly, don't calculate)
- Added recommendation to extract formatTimestamp to shared utils
- Added fire-and-forget integration test task

### File List

**Modified:**
- `services/notification/internal/handlers/risk_handler.go` - Full JSON parsing (risk_blocked, risk_warning, trading_halted)
- `services/notification/internal/formatters/alert_formatter.go` - Add event structs, emoji formatting, FormatTradingHalted
- `services/notification/internal/handlers/handlers_test.go` - Add risk handler tests (3 event types)
- `services/notification/internal/formatters/alert_formatter_test.go` - Update formatter tests (3 formats)
- `services/notification/tests/integration_test.go` - Add risk alert integration + fire-and-forget verification

**Not Created (Deferred):**
- `services/notification/internal/formatters/utils.go` - Kept timestamp formatting in respective files for simplicity

### Implementation Completion Notes (2026-01-15)

**Implementation Summary:**
- All 4 acceptance criteria implemented and tested
- 3 event types handled: `risk_blocked`, `risk_warning`, `trading_halted`
- Event structs defined with proper JSON tags for unmarshalling
- Formatters produce exact output format specified in ACs
- Fire-and-forget pattern preserved (Router returns < 5ms)
- Invalid JSON handled gracefully with proper error wrapping

**Test Results:**
- All unit tests pass (handlers + formatters)
- All integration tests pass (router routing + fire-and-forget)
- Race detection clean (`go test -race ./...`)

**Deviations from Plan:**
- Task 3.7 deferred: `formatTimestamp()` not extracted to shared utils.go. Renamed to `formatAlertTimestamp()` to avoid collision with trade_formatter.go. Can be refactored later if needed.
