# Story 6.6: Resume Trading Command

Status: Done

## Story

As a **trader**,
I want **to resume trading after emergency stop via Telegram**,
So that **I can restart operations when the crisis is over**.

## Acceptance Criteria

1. **Given** all accounts are paused from emergency stop
   **When** I send `/resume_all`
   **Then** the bot asks for confirmation: "Are you sure you want to resume trading for all accounts? Reply /confirm_resume"

2. **Given** I send `/confirm_resume`
   **When** the bot processes the confirmation
   **Then** it publishes resume command to Redis `emergency:resume` channel
   **And** all previously active accounts resume trading

3. **Given** resume completes
   **When** the notification service receives confirmation
   **Then** it sends:
   ```
   🟢 TRADING RESUMED
   Accounts Restarted: 3
   Status: Normal operation
   Time: 14:32:20 UTC
   ```

4. **Given** I send `/resume ftmo-gold-001`
   **When** the bot processes it
   **Then** only the specified account resumes

5. **Given** trading is not stopped (no emergency stop active)
   **When** I send `/resume_all`
   **Then** the bot responds: "⚠️ Trading is already active - no emergency stop to resume from"

6. **Given** I send `/resume_all` but don't confirm
   **When** 60 seconds pass without `/confirm_resume`
   **Then** the confirmation request expires and user must restart with `/resume_all`

## Tasks / Subtasks

**Task Dependency Order:**
```
Task 1 (Resume Command) → Task 2 (Confirmation Flow) → Task 3 (Redis Publisher) → Task 4 (Confirmation Handler) → Task 5 (Single Account Resume) → Task 6 (Tests)
```

- [x] Task 1: Implement /resume_all Command Handler (AC: #1, #5)
  - [x] 1.1: Check if emergency stop is NOT active (using `h.bot.IsStopActive()`)
  - [x] 1.2: If not stopped, return "⚠️ Trading is already active - no emergency stop to resume from" (AC#5)
  - [x] 1.3: If stopped, store pending confirmation state with timestamp (pendingResume atomic struct)
  - [x] 1.4: Return confirmation prompt: "⚠️ Resume trading for all accounts?\n\nReply /confirm_resume within 60 seconds"
  - [x] 1.5: Log resume_all request with username and chat ID

- [x] Task 2: Implement /confirm_resume Command Handler (AC: #2, #6)
  - [x] 2.1: Add `confirm_resume` case to `Handle()` switch statement
  - [x] 2.2: Check if pending confirmation exists and is within 60-second timeout (AC#6)
  - [x] 2.3: If expired or no pending, return "⚠️ No pending resume request. Use /resume_all first"
  - [x] 2.4: If valid, call `PublishResumeCommand()` with username and chat ID
  - [x] 2.5: Reset stopActive state: `h.bot.SetStopActive(false)`
  - [x] 2.6: Clear pending confirmation state
  - [x] 2.7: Return "🟢 *TRADING RESUME INITIATED*\n\nCommand sent to trading engine.\nAwaiting confirmation..."

- [x] Task 3: Implement Redis Resume Publisher (AC: #2)
  - [x] 3.1: Define `ResumeCommand` JSON struct with type, command, initiator, initiated_by, chat_id, timestamp, and accounts (optional)
  - [x] 3.2: Add `PublishResumeCommand(ctx, username, chatID, accounts []string)` method to Bot struct
  - [x] 3.3: Publish to `emergency:resume` channel (separate from stop channel for clarity)
  - [x] 3.4: Log resume command with timing (similar to PublishEmergencyStop)

- [x] Task 4: Implement Resume Confirmation Handler (AC: #3)
  - [x] 4.1: Add `ResumeConfirmation` JSON struct to formatters/alert_formatter.go
  - [x] 4.2: Add `FormatResumeConfirmation()` method to AlertFormatter
  - [x] 4.3: Update EmergencyHandler to route `resume_confirmation` type
  - [x] 4.4: Format with 🟢 emoji, "Accounts Restarted:", "Status:", "Time:" fields
  - [x] 4.5: Handle self-echo of `resume_command` type (ignore, return empty)

- [x] Task 5: Implement /resume Single Account Command (AC: #4)
  - [x] 5.1: Add `resume` case to Handle() switch for `/resume <account_id>` format
  - [x] 5.2: Parse account_id from message arguments
  - [x] 5.3: Validate account_id is not empty
  - [x] 5.4: Call PublishResumeCommand with specific account in accounts array
  - [x] 5.5: Return confirmation: "🟢 Resume initiated for account: {account_id}"

- [x] Task 6: Add Unit and Integration Tests (AC: #1-6)
  - [x] 6.1: Unit test: `handleResumeAll()` returns already-active message when not stopped (AC#5)
  - [x] 6.2: Unit test: `handleResumeAll()` returns confirmation prompt when stopped (AC#1)
  - [x] 6.3: Unit test: `handleConfirmResume()` publishes to Redis and resets stopActive (AC#2)
  - [x] 6.4: Unit test: `handleConfirmResume()` rejects expired confirmation (AC#6)
  - [x] 6.5: Unit test: `ResumeCommand` JSON marshalling matches expected format
  - [x] 6.6: Unit test: `FormatResumeConfirmation()` output matches AC#3 format with emoji
  - [x] 6.7: Unit test: `handleResume()` publishes for single account (AC#4)
  - [x] 6.8: Integration test: Full flow from /resume_all → /confirm_resume → Redis → confirmation
  - [x] 6.9: Integration test: Confirmation timeout expires after 60 seconds

## Dev Notes

### ⚠️ CRITICAL: Read Before Implementation

**These items MUST be completed or the feature will not work:**

1. **⚠️ CONFIRMATION REQUIRED**: Unlike `/stop_all` (immediate), `/resume_all` MUST require `/confirm_resume`. This is a safety feature - do NOT skip.

2. **⚠️ 60-SECOND TIMEOUT**: Confirmation must happen within 60 seconds. Use mutex-protected state with timestamp.

3. **⚠️ ADD `emergency:resume` CHANNEL**: The subscriber currently only listens to `emergency:stop`. You MUST add `"emergency:resume"` to the channels slice in `redis_subscriber.go:112-118`.

4. **⚠️ ADD ROUTER CASE**: The Router in `redis_subscriber.go:54-68` needs a new case for `emergency:resume` channel routing.

5. **⚠️ ADD `sync` IMPORT**: bot.go needs `"sync"` added to imports for `sync.Mutex` in pendingConfirmation struct.

6. **⚠️ SIGNATURE CHANGE**: Change `handleResumeAll()` to `handleResumeAll(msg *tgbotapi.Message)` AND update the caller in Handle() switch.

---

### Quick Reference: What to Add

| Component | What to Add | Location |
|-----------|-------------|----------|
| **Bot struct** | `pendingResume pendingConfirmation` | bot.go |
| **Bot methods** | `SetPendingResume()`, `GetPendingResume()`, `ClearPendingResume()`, `PublishResumeCommand()` | bot.go |
| **Structs** | `ResumeCommand`, `ResumeConfirmation` | bot.go, alert_formatter.go |
| **Command handlers** | `handleResumeAll(msg)`, `handleConfirmResume(msg)`, `handleResume(msg)` | commands.go |
| **Handle() switch** | 3 new cases: `resume_all`, `confirm_resume`, `resume` | commands.go |
| **EmergencyHandler** | 2 new cases: `resume_command`, `resume_confirmation` | emergency_handler.go |
| **Subscriber channels** | `"emergency:resume"` | redis_subscriber.go:112-118 |
| **Router.Route()** | `case channel == "emergency:resume":` | redis_subscriber.go:63 |
| **Help text** | `/confirm_resume`, `/resume <id>` | commands.go handleHelp() |

---

### Architecture Compliance

**Service:** `services/notification/` (Go 1.23+)
**Purpose:** Alert and notification delivery via Telegram + emergency command publishing

**CRITICAL CONSTRAINTS from Architecture:**
- Resume command REQUIRES confirmation prompt (unlike immediate /stop_all)
- Confirmation timeout: 60 seconds from /resume_all to /confirm_resume
- Track which accounts were active before stop (trading engine responsibility)
- Support individual account resume via `/resume <account_id>`
- Fire-and-forget for notifications (don't block on Telegram failures)

### Context from Previous Story (6.5: Emergency Stop Command)

**Key Patterns Established:**
| Pattern | Implementation | Location |
|---------|----------------|----------|
| Stop state tracking | `stopActive atomic.Bool` | bot.go:41 |
| State accessors | `IsStopActive()`, `SetStopActive()` | bot.go:243-250 |
| Redis publishing | `PublishEmergencyStop(ctx, username, chatID)` | bot.go:252-287 |
| JSON struct format | `EmergencyStopCommand` with type, command, initiator fields | bot.go:22-30 |
| Handler routing | Parse `type` field, switch on event type | emergency_handler.go:28-58 |
| Confirmation format | `FormatEmergencyStopConfirmation()` with emoji | alert_formatter.go:159-176 |

**Critical Learning from 6.5:**
1. `handleStopAll()` accepts `msg *tgbotapi.Message` parameter to access user info
2. Publisher initialization uses `cfg.RedisURL` and `cfg.RedisPassword` from existing config
3. Self-echo handling: Ignore messages with `type: "resume_command"` (our own publish)

**🎯 STARTING POINT - Existing TODO in commands.go:219-230:**
```go
func (h *CommandHandler) handleResumeAll() string {
    // Scaffold: Return placeholder response
    // TODO(Story 6.6): Implement full resume logic including:
    // - Call h.bot.SetStopActive(false) to reset emergency stop state
    // - Publish resume command to Redis
    // - Handle already-resumed case similar to already-stopped in handleStopAll
    log.Println("Resume command received (scaffold mode)")
    return `*Resume Trading (Scaffold)*...`
}
```
**Replace this entire function with the new implementation in Step 3.**

**Files Modified in 6.5 (reference for patterns):**
- `internal/telegram/bot.go` - EmergencyStopCommand, PublishEmergencyStop, IsStopActive, SetStopActive
- `internal/telegram/commands.go` - handleStopAll with msg parameter
- `internal/handlers/emergency_handler.go` - Handle with type routing
- `internal/formatters/alert_formatter.go` - EmergencyStopConfirmation, FormatEmergencyStopConfirmation

### JSON Message Formats

**ResumeCommand (published by notification service to `emergency:resume`):**
```json
{
  "type": "resume_command",
  "command": "resume_all",
  "initiator": "telegram",
  "initiated_by": "@username",
  "chat_id": 123456789,
  "accounts": [],
  "timestamp": "2026-01-20T14:32:20Z"
}
```

**ResumeCommand for single account:**
```json
{
  "type": "resume_command",
  "command": "resume",
  "initiator": "telegram",
  "initiated_by": "@username",
  "chat_id": 123456789,
  "accounts": ["ftmo-gold-001"],
  "timestamp": "2026-01-20T14:32:20Z"
}
```

**ResumeConfirmation (published by trading engine to `emergency:resume`):**
```json
{
  "type": "resume_confirmation",
  "status": "completed",
  "accounts_restarted": 3,
  "timestamp": "2026-01-20T14:32:20Z"
}
```

### Library Versions and API (from Context7 Research)

**go-telegram-bot-api v5 (via `/ovyflash/telegram-bot-api`):**

```go
// Command handling pattern (already in commands.go)
switch msg.Command() {
case "resume_all":
    response = h.handleResumeAll(msg)
case "confirm_resume":
    response = h.handleConfirmResume(msg)
case "resume":
    response = h.handleResume(msg)  // Parse args for account_id
}

// Command arguments extraction
args := msg.CommandArguments()  // Returns string after command
```

**go-redis v9 (via `/redis/go-redis`):**

```go
// Publish to channel (same pattern as emergency stop)
err := rdb.Publish(ctx, "emergency:resume", jsonPayload).Err()
if err != nil {
    log.Printf("Failed to publish resume command: %v", err)
}
```

### Implementation Guide

**Step 1: Add Pending Confirmation State** (`internal/telegram/bot.go`)

**⚠️ IMPORTANT: Add `"sync"` to the import block at the top of bot.go:**
```go
import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync"           // ← ADD THIS for sync.Mutex
	"sync/atomic"
	"time"
	// ... rest of imports
)
```

**Then add to Bot struct:**
type pendingConfirmation struct {
    mu        sync.Mutex
    timestamp time.Time
    username  string
    chatID    int64
    active    bool
}

type Bot struct {
    // ... existing fields ...
    pendingResume pendingConfirmation  // Track pending /resume_all confirmation
}

// Methods for pending confirmation
func (b *Bot) SetPendingResume(username string, chatID int64) {
    b.pendingResume.mu.Lock()
    defer b.pendingResume.mu.Unlock()
    b.pendingResume.timestamp = time.Now()
    b.pendingResume.username = username
    b.pendingResume.chatID = chatID
    b.pendingResume.active = true
}

func (b *Bot) GetPendingResume() (username string, chatID int64, valid bool) {
    b.pendingResume.mu.Lock()
    defer b.pendingResume.mu.Unlock()
    if !b.pendingResume.active {
        return "", 0, false
    }
    // Check 60-second timeout
    if time.Since(b.pendingResume.timestamp) > 60*time.Second {
        b.pendingResume.active = false
        return "", 0, false
    }
    return b.pendingResume.username, b.pendingResume.chatID, true
}

func (b *Bot) ClearPendingResume() {
    b.pendingResume.mu.Lock()
    defer b.pendingResume.mu.Unlock()
    b.pendingResume.active = false
}
```

**Step 2: Add ResumeCommand and PublishResumeCommand** (`internal/telegram/bot.go`)

```go
// ResumeCommand represents a resume command sent to the trading engine.
type ResumeCommand struct {
    Type        string   `json:"type"`
    Command     string   `json:"command"`
    Initiator   string   `json:"initiator"`
    InitiatedBy string   `json:"initiated_by"`
    ChatID      int64    `json:"chat_id"`
    Accounts    []string `json:"accounts,omitempty"`  // Empty = all accounts
    Timestamp   string   `json:"timestamp"`
}

func (b *Bot) PublishResumeCommand(ctx context.Context, username string, chatID int64, accounts []string) error {
    if b.publisher == nil {
        return fmt.Errorf("Redis publisher not initialized")
    }

    command := "resume_all"
    if len(accounts) > 0 {
        command = "resume"
    }

    cmd := ResumeCommand{
        Type:        "resume_command",
        Command:     command,
        Initiator:   "telegram",
        InitiatedBy: "@" + username,
        ChatID:      chatID,
        Accounts:    accounts,
        Timestamp:   time.Now().UTC().Format(time.RFC3339),
    }

    payload, err := json.Marshal(cmd)
    if err != nil {
        return fmt.Errorf("failed to marshal resume command: %w", err)
    }

    start := time.Now()
    err = b.publisher.Publish(ctx, "emergency:resume", payload).Err()
    elapsed := time.Since(start)

    if err != nil {
        return fmt.Errorf("failed to publish resume command: %w", err)
    }

    log.Printf("Resume command published in %v (accounts: %v)", elapsed, accounts)
    return nil
}
```

**Step 3: Update handleResumeAll** (`internal/telegram/commands.go`)

```go
// Change signature to accept msg parameter
func (h *CommandHandler) handleResumeAll(msg *tgbotapi.Message) string {
    // AC#5: Check if stop is NOT active
    if !h.bot.IsStopActive() {
        return "⚠️ Trading is already active - no emergency stop to resume from"
    }

    // Extract user information
    username := "unknown"
    if msg.From != nil {
        username = msg.From.UserName
        if username == "" {
            username = fmt.Sprintf("user_%d", msg.From.ID)
        }
    }

    log.Printf("RESUME ALL requested by @%s (chat: %d) - awaiting confirmation", username, msg.Chat.ID)

    // Store pending confirmation with 60-second timeout
    h.bot.SetPendingResume(username, msg.Chat.ID)

    return "⚠️ *Resume trading for all accounts?*\n\nReply /confirm_resume within 60 seconds to proceed.\n\n_This will restart all previously active accounts._"
}
```

**Step 4: Add handleConfirmResume** (`internal/telegram/commands.go`)

```go
func (h *CommandHandler) handleConfirmResume(msg *tgbotapi.Message) string {
    // Check pending confirmation
    username, chatID, valid := h.bot.GetPendingResume()
    if !valid {
        return "⚠️ No pending resume request.\n\nUse /resume_all first, then /confirm_resume within 60 seconds."
    }

    log.Printf("RESUME CONFIRMED by @%s (chat: %d)", username, chatID)

    // Create context with timeout
    ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
    defer cancel()

    // Publish resume command
    if err := h.bot.PublishResumeCommand(ctx, username, chatID, nil); err != nil {
        log.Printf("CRITICAL: Resume command publish failed: %v", err)
        return fmt.Sprintf("*RESUME FAILED*\n\nFailed to send resume command.\nError: %s", err.Error())
    }

    // Reset stop state
    h.bot.SetStopActive(false)

    // Clear pending confirmation
    h.bot.ClearPendingResume()

    return "🟢 *TRADING RESUME INITIATED*\n\nCommand sent to trading engine.\nAwaiting confirmation..."
}
```

**Step 5: Add handleResume for single account** (`internal/telegram/commands.go`)

```go
func (h *CommandHandler) handleResume(msg *tgbotapi.Message) string {
    // Parse account_id from arguments
    accountID := strings.TrimSpace(msg.CommandArguments())
    if accountID == "" {
        return "⚠️ Please specify an account ID.\n\nUsage: /resume <account_id>\nExample: /resume ftmo-gold-001"
    }

    // Extract user information
    username := "unknown"
    if msg.From != nil {
        username = msg.From.UserName
        if username == "" {
            username = fmt.Sprintf("user_%d", msg.From.ID)
        }
    }

    log.Printf("RESUME SINGLE ACCOUNT requested by @%s for %s", username, accountID)

    // Create context with timeout
    ctx, cancel := context.WithTimeout(context.Background(), 500*time.Millisecond)
    defer cancel()

    // Publish resume command for single account
    if err := h.bot.PublishResumeCommand(ctx, username, msg.Chat.ID, []string{accountID}); err != nil {
        log.Printf("CRITICAL: Resume command publish failed: %v", err)
        return fmt.Sprintf("*RESUME FAILED*\n\nFailed to send resume command.\nError: %s", err.Error())
    }

    return fmt.Sprintf("🟢 *RESUME INITIATED*\n\nAccount: %s\nCommand sent to trading engine.", accountID)
}
```

**Step 6: Update Handle() switch** (`internal/telegram/commands.go`)

**⚠️ SIGNATURE CHANGE: Current code calls `h.handleResumeAll()` - change to `h.handleResumeAll(msg)`**

```go
func (h *CommandHandler) Handle(msg *tgbotapi.Message) {
    var response string

    switch msg.Command() {
    case "start":
        response = h.handleStart(msg)
    case "help":
        response = h.handleHelp()
    case "status":
        response = h.handleStatus()
    case "stop_all":
        response = h.handleStopAll(msg)
    case "resume_all":
        response = h.handleResumeAll(msg)  // ← CHANGE: was handleResumeAll() with no args
    case "confirm_resume":
        response = h.handleConfirmResume(msg)  // ← ADD
    case "resume":
        response = h.handleResume(msg)         // ← ADD
    default:
        response = "Unknown command. Use /help for available commands."
    }
    // ... rest of method unchanged
}
```

**Step 6b: Update handleHelp()** (`internal/telegram/commands.go`)

Add the new commands to the help text:

```go
func (h *CommandHandler) handleHelp() string {
    return `*Available Commands:*

/status - Show current system status
/stop_all - Emergency stop all accounts
/resume_all - Resume trading after stop (requires confirmation)
/confirm_resume - Confirm resume after /resume_all
/resume <id> - Resume single account (e.g., /resume ftmo-gold-001)
/help - Show this help message`
}
```

**Step 7: Add ResumeConfirmation and Formatter** (`internal/formatters/alert_formatter.go`)

```go
// ResumeConfirmation represents confirmation from the trading engine.
type ResumeConfirmation struct {
    Type              string `json:"type"`               // "resume_confirmation"
    Status            string `json:"status"`             // "completed"
    AccountsRestarted int    `json:"accounts_restarted"`
    Timestamp         string `json:"timestamp"`
}

// FormatResumeConfirmation formats a resume confirmation alert.
func (f *AlertFormatter) FormatResumeConfirmation(e *ResumeConfirmation) string {
    return fmt.Sprintf(`🟢 *TRADING RESUMED*
Accounts Restarted: %d
Status: Normal operation
Time: %s`,
        e.AccountsRestarted,
        formatAlertTimestamp(e.Timestamp))
}
```

**Step 8: Update EmergencyHandler** (`internal/handlers/emergency_handler.go`)

```go
func (h *EmergencyHandler) Handle(accountID string, payload []byte) (string, error) {
    // Parse base type to determine message kind
    var base struct {
        Type string `json:"type"`
    }
    if err := json.Unmarshal(payload, &base); err != nil {
        return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
    }

    log.Printf("Emergency handler processing type: %s", base.Type)

    switch base.Type {
    case "emergency_stop":
        // Self-echo of our command, ignore
        log.Printf("Ignoring self-echo of emergency_stop command")
        return "", nil

    case "emergency_stop_confirmation":
        var event formatters.EmergencyStopConfirmation
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        log.Printf("Emergency stop confirmed: %d accounts paused", event.AccountsPaused)
        return h.formatter.FormatEmergencyStopConfirmation(&event), nil

    case "resume_command":
        // Self-echo of our command, ignore
        log.Printf("Ignoring self-echo of resume_command")
        return "", nil

    case "resume_confirmation":
        var event formatters.ResumeConfirmation
        if err := json.Unmarshal(payload, &event); err != nil {
            return "", errors.Wrap("Handle", errors.ErrMessageParseError, err.Error())
        }
        log.Printf("Resume confirmed: %d accounts restarted", event.AccountsRestarted)
        return h.formatter.FormatResumeConfirmation(&event), nil

    default:
        log.Printf("Unknown emergency event type: %s", base.Type)
        return "", nil
    }
}
```

**Step 9: Update Redis Subscriber** (`internal/subscriber/redis_subscriber.go`)

**⚠️ TWO CHANGES REQUIRED in redis_subscriber.go:**

**9a. Add channel to subscription list (line ~112-118 in New() function):**
```go
// In New() function, update channels slice:
channels: []string{
    "alerts:trade:*",
    "alerts:risk:*",
    "alerts:system",
    "emergency:stop",
    "emergency:resume",  // ← ADD THIS LINE
},
```

**9b. Add Router case (line ~54-68 in Route() method):**
```go
// In Router.Route() method, add case AFTER emergency:stop case:
case channel == "emergency:stop":
    msg, err = r.emergencyHandler.Handle("", []byte(payload))
case channel == "emergency:resume":                              // ← ADD THIS CASE
    msg, err = r.emergencyHandler.Handle("", []byte(payload))    // Same handler, different channel
```

### Project Structure Notes

**File Locations (DO NOT create new directories):**
```
services/notification/
├── internal/
│   ├── telegram/
│   │   ├── bot.go                    # MODIFY: Add pendingResume, ResumeCommand, PublishResumeCommand
│   │   ├── bot_test.go               # MODIFY: Add resume publisher tests, pending state tests
│   │   ├── commands.go               # MODIFY: Update handleResumeAll, add handleConfirmResume, handleResume
│   │   └── commands_test.go          # MODIFY: Add resume command tests
│   ├── handlers/
│   │   ├── emergency_handler.go      # MODIFY: Add resume_command and resume_confirmation routing
│   │   └── handlers_test.go          # MODIFY: Add resume handler tests
│   ├── formatters/
│   │   ├── alert_formatter.go        # MODIFY: Add ResumeConfirmation struct and formatter
│   │   └── alert_formatter_test.go   # MODIFY: Add resume format tests
│   └── subscriber/
│       └── redis_subscriber.go       # VERIFY: Ensure emergency:resume channel subscribed
├── tests/
│   └── integration_test.go           # MODIFY: Add resume flow integration tests
```

**Files to Modify:**
- `internal/telegram/bot.go` - Add `"sync"` import, pendingConfirmation struct, ResumeCommand struct, PublishResumeCommand method, pending state methods (SetPendingResume, GetPendingResume, ClearPendingResume)
- `internal/telegram/commands.go` - Change handleResumeAll signature to accept msg, add handleConfirmResume, handleResume, update Handle() switch with 3 new cases, update handleHelp() text
- `internal/handlers/emergency_handler.go` - Add resume_command and resume_confirmation cases to Handle() switch
- `internal/formatters/alert_formatter.go` - Add ResumeConfirmation struct and FormatResumeConfirmation method
- `internal/subscriber/redis_subscriber.go` - **⚠️ ADD** `"emergency:resume"` to channels slice AND add Router.Route() case for channel
- Test files for all modified source files

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
- **Test confirmation timeout**: Mock time or use short timeout for tests
- **Test already-active case**: Ensure proper response when stopActive is false

### Patterns from Previous Stories

**Handler Pattern** (from 6.3/6.4/6.5):
- Signature: `Handle(accountID string, payload []byte) (string, error)`
- Parse `type` field first, then route to specific struct
- Return empty string to skip notification (self-echo)
- Use `errors.Wrap()` with `ErrMessageParseError`

**Command Handler Pattern** (from 6.5):
- Functions accept `msg *tgbotapi.Message` parameter for user context
- Extract username with fallback: `username := msg.From.UserName` or `fmt.Sprintf("user_%d", msg.From.ID)`
- Log command with username and chat ID

**Timestamp Format**: Use `formatAlertTimestamp()` (converts ISO 8601 → "HH:MM:SS UTC")

**Recent Commits**: `f4cc95c` (6.5), `ff70783` (6.4), `b9f2dc5` (6.3), `7599c46` (6.2), `3c9ac0c` (6.1)

### Additional Implementation Notes

> **Note:** Critical items (confirmation, timeout, channels, imports, signature) are documented at the top of Dev Notes section.

1. **Reset stopActive**: Call `h.bot.SetStopActive(false)` in handleConfirmResume AFTER successful publish.

2. **Single Account Resume**: `/resume <account_id>` does NOT require confirmation (less dangerous than resume_all). Consider logging when called without active stop.

3. **Self-Echo Handling**: Handler ignores `type: "resume_command"` (our command), only processes `type: "resume_confirmation"`.

4. **Channel Separation**: Use `emergency:resume` channel (separate from `emergency:stop`) for clarity in trading engine.

5. **Already-Active Check (AC#5)**: Return friendly message when `IsStopActive()` returns false.

6. **Task Parallelization**: Tasks 1-3 (bot.go, commands.go) and Tasks 4 (handler, formatter) can be worked on in parallel since they're in different files. Task 5 (redis_subscriber.go) is independent.

### References

- [Source: docs/architecture.md#Notification Service (Go)]
- [Source: docs/architecture.md#Redis Pub/Sub Channels]
- [Source: docs/architecture.md#Emergency Stop Flow]
- [Source: docs/epics.md#Story 6.6]
- [Source: docs/sprint-artifacts/6-5-emergency-stop-command.md - previous story patterns]
- [Source: services/notification/internal/telegram/commands.go:219-230 - TODO for 6.6]
- [Source: services/notification/internal/telegram/bot.go - EmergencyStopCommand pattern]
- [Source: Context7 - go-telegram-bot-api v5 command handling with arguments]
- [Source: Context7 - go-redis v9 Publish/Subscribe patterns]

## Dev Agent Record

### Context Reference

Context7 MCP was used to retrieve latest documentation for:
- `go-telegram-bot-api` v5 - Command handling, message arguments extraction, callback patterns
- `go-redis` v9 - Publish/Subscribe for emergency channel communication

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

N/A - Implementation completed without debug issues.

### Completion Notes List

**Implementation completed (2026-01-20):**
- ✅ Added `pendingConfirmation` struct with mutex protection and 60-second timeout to `bot.go`
- ✅ Added `ResumeCommand` struct with JSON marshalling (omits accounts when nil)
- ✅ Added `PublishResumeCommand()` method to Bot struct publishing to `emergency:resume` channel
- ✅ Added `SetPendingResume()`, `GetPendingResume()`, `ClearPendingResume()` methods
- ✅ Updated `handleResumeAll()` to require confirmation when stop is active (AC#1)
- ✅ Added already-active check returning friendly message (AC#5)
- ✅ Implemented `handleConfirmResume()` with 60-second timeout validation (AC#2, AC#6)
- ✅ Implemented `handleResume()` for single account resume via `/resume <account_id>` (AC#4)
- ✅ Added `ResumeConfirmation` struct and `FormatResumeConfirmation()` formatter (AC#3)
- ✅ Updated EmergencyHandler to route `resume_command` (self-echo) and `resume_confirmation`
- ✅ Added `emergency:resume` to subscriber channels and Router.Route() case
- ✅ Updated handleHelp() with new commands
- ✅ All unit tests pass (17 new tests for resume functionality)
- ✅ All integration tests pass
- ✅ go vet passes

### File List

**Modified:**
- `services/notification/internal/telegram/bot.go` - Added sync import, pendingConfirmation struct, ResumeCommand struct, PublishResumeCommand, SetPendingResume, GetPendingResume, ClearPendingResume
- `services/notification/internal/telegram/commands.go` - Updated Handle() switch, changed handleResumeAll signature, added handleConfirmResume, handleResume, updated handleHelp, added stop state logging to handleResume
- `services/notification/internal/telegram/commands_test.go` - Added 15 new tests for resume commands including timeout expiration tests
- `services/notification/internal/handlers/emergency_handler.go` - Added resume_command and resume_confirmation routing
- `services/notification/internal/handlers/handlers_test.go` - Added 2 new tests for resume handler
- `services/notification/internal/formatters/alert_formatter.go` - Added ResumeConfirmation struct and FormatResumeConfirmation method
- `services/notification/internal/formatters/alert_formatter_test.go` - Added 2 new tests for resume formatter
- `services/notification/internal/subscriber/redis_subscriber.go` - Added emergency:resume to channels, added Router.Route() case
- `services/notification/internal/subscriber/redis_subscriber_test.go` - Updated expected channels list, added TestRouterRoute_EmergencyResumeChannel, fixed channel count in integration test
- `services/notification/tests/integration_test.go` - Added TestRouter_ResumeConfirmation, TestRouter_ResumeCommandSelfEcho integration tests
- `docs/sprint-artifacts/sprint-status.yaml` - Updated story 6-6 status to review

## Change Log

| Date | Change | Author |
|------|--------|--------|
| 2026-01-20 | Story context created with comprehensive developer guide. | Claude Opus 4.5 |
| 2026-01-20 | **Validation Applied:** Added critical section at top with 6 must-fix items. Added Quick Reference table. Fixed missing `emergency:resume` channel subscription (C1) and Router case (C2). Added explicit `sync` import instruction (C3). Added help text content (E1). Added signature change emphasis (E3). Added existing TODO reference (O1). Added task parallelization note (L1). Restructured critical notes with emojis (L2). | Claude Opus 4.5 (SM Validation) |
| 2026-01-20 | **Implementation complete.** All 6 tasks implemented: /resume_all with confirmation flow, /confirm_resume with 60s timeout, PublishResumeCommand to emergency:resume channel, ResumeConfirmation handler and formatter, /resume <account_id> for single account. All tests pass. | Claude Opus 4.5 |
| 2026-01-21 | **Code Review Fixes Applied:** (1) Added TestRouter_ResumeConfirmation and TestRouter_ResumeCommandSelfEcho integration tests. (2) Added TestBot_PendingResume_TimeoutExpiration and TestBot_PendingResume_TimeoutBoundary tests for 60s timeout verification. (3) Added stop state logging to handleResume() for single account. (4) Fixed channel count from 4 to 5 in redis_subscriber_test.go integration test. (5) Added TestRouterRoute_EmergencyResumeChannel router test. (6) Added sprint-status.yaml to File List. All tests pass. | Claude Opus 4.5 (SM Review) |
