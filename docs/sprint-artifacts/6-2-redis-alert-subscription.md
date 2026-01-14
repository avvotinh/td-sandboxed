# Story 6.2: Redis Alert Subscription

Status: Done

## Story

As a **developer**,
I want **the notification service to subscribe to alert channels**,
So that **it receives events to notify about**.

## Acceptance Criteria

1. **Given** the notification service starts
   **When** it connects to Redis
   **Then** it subscribes to these channels:
   - `alerts:trade:*` (trade executions per account)
   - `alerts:risk:*` (rule warnings/violations per account)
   - `alerts:system` (system-wide alerts)
   - `emergency:stop` (emergency stop commands)

2. **Given** a message is published to `alerts:trade:ftmo-gold-001`
   **When** the subscriber receives it
   **Then** the message is parsed and routed to trade handler

3. **Given** Redis connection is lost
   **When** the subscriber detects disconnection
   **Then** it reconnects and re-subscribes to all channels

## Tasks / Subtasks

- [x] Task 1: Implement Redis Connection with Retry Logic (AC: #1, #3)
  - [x] 1.1: Add `Connect(ctx context.Context) error` method with exponential backoff
  - [x] 1.2: Implement connection health check via `PING` command
  - [x] 1.3: Add connection state tracking via `atomic.Bool` (same pattern as Bot)
  - [x] 1.4: Add `IsConnected() bool` method for health checks (used by /status)
  - [x] 1.5: Log connection status changes with appropriate severity

- [x] Task 2: Implement Pattern Subscription Logic (AC: #1)
  - [x] 2.1: Use single `PSubscribe` call for ALL channels (patterns and exact work together)
  - [x] 2.2: Wait for subscription confirmation before returning success
  - [x] 2.3: Log all subscribed channels on startup

- [x] Task 3: Implement Message Routing (AC: #2)
  - [x] 3.1: Add `Notifier` interface and `Router` struct in `redis_subscriber.go`
  - [x] 3.2: Router receives `Notifier` (bot) at construction for sending messages
  - [x] 3.3: Route `alerts:trade:{account_id}` messages to `TradeHandler`
  - [x] 3.4: Route `alerts:risk:{account_id}` messages to `RiskHandler`
  - [x] 3.5: Route `alerts:system` messages to `SystemHandler`
  - [x] 3.6: Route `emergency:stop` messages to `EmergencyHandler`
  - [x] 3.7: Extract account_id from channel name for per-account handlers

- [x] Task 4: Implement Reconnection Handler (AC: #3)
  - [x] 4.1: Detect disconnection via channel closure or error
  - [x] 4.2: Implement exponential backoff reconnection (reuse config from Story 6.1)
  - [x] 4.3: Re-subscribe to all channels after successful reconnection
  - [x] 4.4: Log reconnection attempts and status
  - [x] 4.5: Continue processing from where left off (no message replay needed)

- [x] Task 5: Integrate with Main Bot (AC: #1)
  - [x] 5.1: Update `cmd/bot/main.go` to create subscriber with bot as Notifier
  - [x] 5.2: Start subscriber in goroutine with context
  - [x] 5.3: Update `/status` command to call `subscriber.IsConnected()`
  - [x] 5.4: Implement graceful shutdown with context cancellation

- [x] Task 6: Add Error Types
  - [x] 6.1: Add `ErrSubscriptionFailed` to `errors.go`
  - [x] 6.2: Add `ErrMessageParseError` to `errors.go`
  - [x] 6.3: Note: `ErrRedisConnection` already exists

- [x] Task 7: Add Unit and Integration Tests
  - [x] 7.1: Unit tests for `Connect()` with mock Redis
  - [x] 7.2: Unit tests for message routing to correct handlers
  - [x] 7.3: Unit tests for `IsConnected()` state tracking
  - [x] 7.4: Unit tests for reconnection logic
  - [x] 7.5: Integration test with real Redis (skip if REDIS_URL not set)
  - [x] 7.6: Test pattern matching for `alerts:trade:*` channels

## Dev Notes

### Architecture Compliance

**Service:** `services/notification/` (Go 1.23+)
**Purpose:** Alert and notification delivery via Telegram

**CRITICAL CONSTRAINTS from Architecture:**
- Never block trading operations on notification failure
- Fire-and-forget pattern for alerts
- Implement reconnection with exponential backoff (same pattern as Telegram in Story 6.1)
- Use pattern subscription for per-account channels

### Notifier Interface Pattern (CRITICAL)

Handlers need to send Telegram notifications but MUST NOT import the telegram package (circular dependency). Solution: Define `Notifier` interface in subscriber package, inject bot at construction.

```go
// In internal/subscriber/redis_subscriber.go

// Notifier sends messages to users. Bot implements this.
type Notifier interface {
    SendMessage(text string) error
}

// Handler processes messages and returns formatted text for notification.
// Handlers format messages, Router sends via Notifier.
type Handler interface {
    Handle(accountID string, payload []byte) (string, error) // Returns formatted message
}

// Router routes messages to handlers and sends via Notifier.
// Lives in redis_subscriber.go alongside Subscriber.
type Router struct {
    notifier         Notifier
    tradeHandler     Handler
    riskHandler      Handler
    systemHandler    Handler
    emergencyHandler Handler
}

func NewRouter(notifier Notifier) *Router {
    return &Router{
        notifier:         notifier,
        tradeHandler:     handlers.NewTradeHandler(),
        riskHandler:      handlers.NewRiskHandler(),
        systemHandler:    handlers.NewSystemHandler(),
        emergencyHandler: handlers.NewEmergencyHandler(),
    }
}

func (r *Router) Route(channel, payload string) {
    var msg string
    var err error

    switch {
    case strings.HasPrefix(channel, "alerts:trade:"):
        accountID := extractAccountID(channel)
        msg, err = r.tradeHandler.Handle(accountID, []byte(payload))
    case strings.HasPrefix(channel, "alerts:risk:"):
        accountID := extractAccountID(channel)
        msg, err = r.riskHandler.Handle(accountID, []byte(payload))
    case channel == "alerts:system":
        msg, err = r.systemHandler.Handle("", []byte(payload))
    case channel == "emergency:stop":
        msg, err = r.emergencyHandler.Handle("", []byte(payload))
    default:
        log.Printf("Unknown channel: %s", channel)
        return
    }

    if err != nil {
        log.Printf("Handler error for %s: %v", channel, err)
        return
    }

    // Fire-and-forget: don't block on send errors
    go func() {
        if err := r.notifier.SendMessage(msg); err != nil {
            log.Printf("Failed to send notification: %v", err)
        }
    }()
}
```

### Existing Scaffold Analysis

**Already Implemented (from Story 6.1):**
- Bot initialization with exponential backoff in `internal/telegram/bot.go`
- `SendMessage(text string) error` method on Bot - implements Notifier interface
- Command handling in `internal/telegram/commands.go`
- Config with retry settings in `internal/config/config.go`
- Graceful shutdown in `cmd/bot/main.go`

**Existing Files:**
- `internal/subscriber/redis_subscriber.go` - Scaffold, needs full implementation
- `internal/handlers/trade_handler.go` - Scaffold (full impl in Story 6.3)
- `internal/handlers/risk_handler.go` - Scaffold (full impl in Story 6.4)
- `internal/handlers/health_handler.go` - Exists, unrelated to this story
- `internal/errors/errors.go` - Has `ErrRedisConnection`, needs new errors

### go-redis v9.17.2 API Reference

```go
import "github.com/redis/go-redis/v9"

// Connection
rdb := redis.NewClient(&redis.Options{
    Addr:     cfg.RedisURL,      // e.g., "redis:6379"
    Password: cfg.RedisPassword, // empty for no password
})
ctx := context.Background()
_, err := rdb.Ping(ctx).Result() // Health check

// Subscribe to ALL channels with single PSubscribe call
// Both wildcards and exact channels work with PSubscribe
pubsub := rdb.PSubscribe(ctx,
    "alerts:trade:*",   // Pattern - matches alerts:trade:ftmo-gold-001
    "alerts:risk:*",    // Pattern - matches alerts:risk:ftmo-gold-001
    "alerts:system",    // Exact - no wildcard
    "emergency:stop",   // Exact - no wildcard
)

// Wait for subscription confirmation
_, err := pubsub.Receive(ctx)
if err != nil {
    return errors.Wrap("Subscribe", ErrSubscriptionFailed, err.Error())
}

// Message loop with reconnection handling
ch := pubsub.Channel()
for {
    select {
    case <-ctx.Done():
        return ctx.Err()
    case msg, ok := <-ch:
        if !ok {
            // Channel closed - reconnect with backoff
            pubsub.Close()
            // Re-create subscription...
            continue
        }
        // msg.Channel = actual channel (e.g., "alerts:trade:ftmo-gold-001")
        // msg.Pattern = pattern that matched (e.g., "alerts:trade:*"), empty for exact
        // msg.Payload = JSON message content
        router.Route(msg.Channel, msg.Payload)
    }
}

// Extract account ID from channel
func extractAccountID(channel string) string {
    parts := strings.SplitN(channel, ":", 3)
    if len(parts) >= 3 {
        return parts[2]
    }
    return ""
}
```

### Message Formats (JSON)

| Channel | Type Field | Key Fields |
|---------|-----------|------------|
| `alerts:trade:*` | `trade_executed` | account_id, symbol, action, lots, entry_price, sl, tp, reason |
| `alerts:risk:*` | `risk_warning` or `risk_violation` | account_id, rule, severity, current_value, limit_value |
| `alerts:system` | `system_alert` | severity, service, message |
| `emergency:stop` | `emergency_stop` | source, user_id |

All messages include `timestamp` field in ISO 8601 format.

### Files to Create

- `internal/handlers/system_handler.go` - Handle `alerts:system` messages (scaffold for now)
- `internal/handlers/emergency_handler.go` - Handle `emergency:stop` messages (scaffold for now)
- `internal/subscriber/redis_subscriber_test.go` - Unit tests

### Files to Modify

- `internal/subscriber/redis_subscriber.go` - Full implementation with Router, Notifier interface
- `internal/errors/errors.go` - Add `ErrSubscriptionFailed`, `ErrMessageParseError`
- `internal/telegram/commands.go:112-136` - Update `/status` to show Redis status
- `cmd/bot/main.go` - Create subscriber with bot as Notifier, start in goroutine

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `REDIS_URL` | No | `redis:6379` | Redis server address |
| `REDIS_PASSWORD` | No | empty | Redis password |
| `TELEGRAM_BOT_TOKEN` | Yes | - | Bot token from @BotFather |
| `TELEGRAM_CHAT_ID` | No | - | Target chat for alerts |

### Previous Story Intelligence (Story 6.1)

**Key Patterns to Reuse:**
- Exponential backoff: `bot.go:64-104` - `connectWithRetry()` with context
- Config fields: `config.go:21-24` - `MaxRetries`, `RetryBaseDelay`, `MaxRetryDelay`
- Health check: `bot.go:159-177` - `IsHealthy()` with cached status (30s TTL)
- State tracking: `atomic.Bool` for thread-safe connected state
- `/status` command: `commands.go:112-136` - pattern to extend for Redis status

**Code Review Fixes from 6.1:**
- Context parameter for graceful shutdown during retry
- Cached health check with TTL instead of API call every time

### Critical Implementation Notes

1. **Router and Notifier live in `redis_subscriber.go`** - No separate router package
2. **Handlers return formatted strings** - Router calls `notifier.SendMessage()`
3. **DO NOT block on message processing** - Use goroutines for handler execution
4. **DO NOT lose messages** - Log and continue on handler errors
5. **DO NOT create circular deps** - Handlers don't import telegram or subscriber
6. **Reuse retry config** from Story 6.1 (`MaxRetries`, `RetryBaseDelay`, `MaxRetryDelay`)
7. **Add IsConnected() to Subscriber** - Called by `/status` command

### Testing Standards

- Unit tests: `*_test.go` files alongside source
- Integration tests: `tests/integration_test.go`
- Run: `cd services/notification && go test ./...`
- Race detection: `go test -race ./...`
- Skip integration tests without Redis: Check `REDIS_URL` env var

### References

- [Source: docs/architecture.md#Notification Service (Go)]
- [Source: docs/epics.md#Story 6.2]
- [Source: services/notification/internal/telegram/bot.go - Story 6.1 patterns]
- [Source: Context7 - go-redis v9.17.2 Pub/Sub documentation]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- `go-redis` v9.17.2 - Redis Pub/Sub with pattern subscription
- `go-telegram-bot-api` v5.5.1 - Referenced for message sending (Story 6.1)

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

No debug issues encountered.

### Completion Notes List

- Implemented full Redis Pub/Sub subscription with exponential backoff retry (matching Story 6.1 patterns)
- Added Notifier interface and Router struct to enable decoupled message handling without circular dependencies
- Created system_handler.go and emergency_handler.go scaffolds for future stories
- Updated handlers to return (string, error) for proper message flow through Router
- Integrated subscriber with main.go - bot serves as Notifier, subscriber runs in goroutine
- Updated /status command to show Redis connection status and subscribed channels
- Added RedisStatusChecker interface to commands.go to avoid circular imports
- All tests pass including race detection tests
- Handler implementations are scaffolds returning empty strings (full impl in Stories 6.3-6.5)

### Code Review Fixes Applied (2026-01-15)

1. **H1 - Missing Redis status tests**: Added `TestHandleStatus_RedisConnected`, `TestHandleStatus_RedisDisconnected`, `TestHandleStatus_RedisNotInitialized` to commands_test.go
2. **H2 - Race condition on global subscriber**: Added `sync.RWMutex` protection with `SetSubscriber()`/`getSubscriber()` functions in commands.go
3. **L1 - Inconsistent error wrapping**: Changed `reconnect()` to use `errors.Wrap()` instead of `fmt.Errorf()` for consistency
4. **M4 - Missing error path tests**: Added `TestRouterRoute_HandlerError` and `TestRouterRoute_NotifierError` to redis_subscriber_test.go
5. **M1 - Incomplete File List**: Updated to include all changed files including sprint-status.yaml and story documentation

### Change Log

- 2026-01-15: Implemented Redis alert subscription (Story 6.2)
- 2026-01-15: Code review fixes applied (H1, H2, L1, M1, M4)

### File List

**New Files:**
- services/notification/internal/handlers/system_handler.go
- services/notification/internal/handlers/emergency_handler.go
- services/notification/internal/subscriber/redis_subscriber_test.go
- docs/sprint-artifacts/6-2-redis-alert-subscription.md (this story file)
- docs/sprint-artifacts/validation-report-6-2-20260115.md (validation report)

**Modified Files:**
- services/notification/internal/subscriber/redis_subscriber.go (full implementation)
- services/notification/internal/errors/errors.go (added ErrSubscriptionFailed, ErrMessageParseError)
- services/notification/internal/handlers/trade_handler.go (updated Handle signature)
- services/notification/internal/handlers/risk_handler.go (updated Handle signature)
- services/notification/internal/handlers/handlers_test.go (updated for new signatures)
- services/notification/internal/telegram/commands.go (added Redis status to /status, thread-safe subscriber access)
- services/notification/internal/telegram/commands_test.go (added Redis status tests)
- services/notification/cmd/bot/main.go (integrated subscriber with bot)
- services/notification/tests/integration_test.go (updated for new subscriber API)
- docs/sprint-artifacts/sprint-status.yaml (updated story status)
