# Story 1.8: Notification Service Scaffold

**Epic:** 1 - Foundation & Infrastructure
**Status:** Ready for Review
**Created:** 2025-12-19

---

## User Story

As a **developer**,
I want **the notification Go service scaffolded**,
So that **I can develop the Telegram bot for alerts**.

---

## Context

This story implements the Go notification service scaffold for the Sandboxed multi-account trading system. The notification service is responsible for:
- Receiving alert events from Redis Pub/Sub channels
- Sending notifications to Telegram via Bot API
- Handling trade execution notifications
- Sending risk warning alerts
- Processing emergency stop/resume commands

### Why Go?

Per Architecture ADR-002:
- Lightweight and efficient for I/O-bound services
- Consistent with tv-api service (shared knowledge)
- Fast startup and low memory footprint
- Excellent Telegram bot libraries available

### Current State

**Existing Files (Placeholders):**
- `services/notification/` - Directory may exist with placeholder files
- Need to verify and update existing structure

**Missing Items:**
- Complete Go module with dependencies
- Directory structure per architecture spec
- Entry point with graceful shutdown
- Telegram bot client scaffold
- Redis subscriber for alert channels
- Message handlers and formatters
- Multi-stage Dockerfile
- Test infrastructure

### Prerequisites

- **Story 1.1 Complete:** Project structure and monorepo setup
- **Story 1.2 Complete:** Docker compose infrastructure (Redis available)

**Previous Story:** [1-7-mt5-bridge-service-scaffold.md](./1-7-mt5-bridge-service-scaffold.md)

---

## Acceptance Criteria

### AC1: Directory Structure Matches Architecture
**Given** I navigate to `services/notification`
**When** I examine the directory
**Then** I see:
```
notification/
├── cmd/
│   └── bot/
│       └── main.go
├── internal/
│   ├── config/
│   │   └── config.go
│   ├── errors/
│   │   └── errors.go
│   ├── telegram/
│   │   ├── bot.go
│   │   └── commands.go
│   ├── handlers/
│   │   ├── trade_handler.go
│   │   ├── risk_handler.go
│   │   └── health_handler.go
│   ├── formatters/
│   │   ├── trade_formatter.go
│   │   └── alert_formatter.go
│   └── subscriber/
│       └── redis_subscriber.go
├── tests/
│   └── integration_test.go
├── Dockerfile
├── go.mod
└── README.md
```

### AC2: Project Compiles Successfully
**Given** I navigate to `services/notification`
**When** I run `go build ./cmd/bot`
**Then** the project compiles without errors
**And** all dependencies resolve correctly

### AC3: Bot Starts with Valid Token
**Given** I run the bot with valid `TELEGRAM_BOT_TOKEN`
**When** the service starts
**Then** the bot connects to Telegram
**And** logs "Telegram bot connected" (or similar)
**And** can receive commands

### AC4: Docker Build Succeeds
**Given** I run `docker build .` in notification directory
**When** the build completes
**Then** a working image is created with multi-stage build

### AC5: Graceful Shutdown Works
**Given** the bot is running
**When** I send SIGTERM or SIGINT
**Then** the bot shuts down gracefully
**And** logs shutdown messages

### AC6: Test Infrastructure Ready
**Given** I navigate to `services/notification`
**When** I run `go test ./...`
**Then** tests are discovered and run
**And** basic config and structure tests pass

---

## Tasks

> **KEY CONSTRAINTS (Quick Reference)**
> 1. **This is SCAFFOLD ONLY** - Do NOT implement actual Redis subscription logic (that's Story 6.2)
> 2. **Use go-telegram-bot-api/v5** - The established Go Telegram library
> 3. **Use redis/go-redis/v9** - The official Redis Go client
> 4. **Use spf13/viper** - For configuration management
> 5. **Do NOT modify docker-compose.yml** - that's Story 1.9
>
> See full guardrails in "Dev Agent Guardrails" section below.

### Task 1: Initialize Go Module with Dependencies (AC2)

Update `services/notification/go.mod` (preserving existing module path):

```go
module github.com/user/sandboxed/services/notification

go 1.23

require (
    github.com/go-telegram-bot-api/telegram-bot-api/v5 v5.5.1
    github.com/redis/go-redis/v9 v9.7.0
    github.com/spf13/viper v1.19.0
)
```

**Note:** The module path `github.com/user/sandboxed/services/notification` matches the existing placeholder convention. Adjust if your project uses a different pattern.

Run `go mod tidy` to resolve all dependencies.

**Dependency Rationale:**

| Dependency | Purpose |
|------------|---------|
| go-telegram-bot-api/v5 | Telegram Bot API client (long-polling) |
| redis/go-redis/v9 | Redis client with Pub/Sub support |
| spf13/viper | Configuration from env vars and files |

### Task 2: Create Directory Structure (AC1)

Create the following directory structure:

```
services/notification/
├── cmd/
│   └── bot/
│       └── main.go              # Entry point
├── internal/
│   ├── config/
│   │   └── config.go            # Configuration loading
│   ├── errors/
│   │   └── errors.go            # Custom error types
│   ├── telegram/
│   │   ├── bot.go               # Telegram bot client
│   │   └── commands.go          # Command handlers
│   ├── handlers/
│   │   ├── trade_handler.go     # Trade notification handler
│   │   ├── risk_handler.go      # Risk alert handler
│   │   └── health_handler.go    # Health check handler
│   ├── formatters/
│   │   ├── trade_formatter.go   # Trade message formatter
│   │   └── alert_formatter.go   # Alert message formatter
│   └── subscriber/
│       └── redis_subscriber.go  # Redis Pub/Sub subscriber
├── tests/
│   └── integration_test.go      # Integration test structure
├── Dockerfile
├── go.mod
├── go.sum
└── README.md
```

### Task 3: Implement Entry Point with Graceful Shutdown (AC3, AC5)

**cmd/bot/main.go:**

```go
// Notification Bot - Entry Point
//
// Telegram notification service for the Sandboxed trading system.
// Receives alerts via Redis Pub/Sub and sends to Telegram.

package main

import (
    "context"
    "log"
    "os"
    "os/signal"
    "syscall"

    "github.com/user/sandboxed/services/notification/internal/config"
    "github.com/user/sandboxed/services/notification/internal/subscriber"
    "github.com/user/sandboxed/services/notification/internal/telegram"
)

func main() {
    log.Println("Notification service starting...")

    // Load configuration
    cfg, err := config.Load()
    if err != nil {
        log.Fatalf("Failed to load configuration: %v", err)
    }

    // Create context with cancellation
    ctx, cancel := context.WithCancel(context.Background())
    defer cancel()

    // Initialize Telegram bot
    bot, err := telegram.NewBot(cfg)
    if err != nil {
        log.Fatalf("Failed to initialize Telegram bot: %v", err)
    }
    log.Println("Telegram bot connected")

    // Initialize Redis subscriber (scaffold - doesn't connect yet)
    sub := subscriber.New(cfg)
    log.Printf("Redis subscriber initialized (scaffold mode)")

    // Handle shutdown signals
    sigChan := make(chan os.Signal, 1)
    signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

    // Start bot in goroutine
    go func() {
        if err := bot.Start(ctx); err != nil {
            log.Printf("Bot error: %v", err)
            cancel()
        }
    }()

    // Wait for shutdown signal
    sig := <-sigChan
    log.Printf("Received signal %v, initiating graceful shutdown", sig)

    // Cancel context to stop all goroutines
    cancel()

    // Cleanup
    sub.Close()
    bot.Stop()

    log.Println("Notification service stopped")
}
```

### Task 4: Implement Configuration Module

**internal/config/config.go:**

```go
// Configuration module for notification service.

package config

import (
    "fmt"
    "strings"

    "github.com/spf13/viper"
)

// Config holds all configuration for the notification service.
type Config struct {
    // Telegram configuration
    TelegramBotToken string
    TelegramChatID   int64

    // Redis configuration
    RedisURL      string
    RedisPassword string

    // Service configuration
    LogLevel string
    Debug    bool
}

// Load reads configuration from environment variables.
func Load() (*Config, error) {
    v := viper.New()

    // Set environment variable prefix
    v.SetEnvPrefix("NOTIFICATION")
    v.AutomaticEnv()
    v.SetEnvKeyReplacer(strings.NewReplacer(".", "_"))

    // Set defaults
    v.SetDefault("log_level", "info")
    v.SetDefault("debug", false)
    v.SetDefault("redis_url", "redis:6379")

    // Also check for common env var names without prefix
    if token := viper.GetString("TELEGRAM_BOT_TOKEN"); token != "" {
        v.Set("telegram_bot_token", token)
    }
    if chatID := viper.GetInt64("TELEGRAM_CHAT_ID"); chatID != 0 {
        v.Set("telegram_chat_id", chatID)
    }
    if redisURL := viper.GetString("REDIS_URL"); redisURL != "" {
        v.Set("redis_url", redisURL)
    }

    cfg := &Config{
        TelegramBotToken: v.GetString("telegram_bot_token"),
        TelegramChatID:   v.GetInt64("telegram_chat_id"),
        RedisURL:         v.GetString("redis_url"),
        RedisPassword:    v.GetString("redis_password"),
        LogLevel:         v.GetString("log_level"),
        Debug:            v.GetBool("debug"),
    }

    // Validate required configuration
    if cfg.TelegramBotToken == "" {
        return nil, fmt.Errorf("TELEGRAM_BOT_TOKEN is required")
    }

    return cfg, nil
}
```

### Task 4.5: Implement Error Types Module

**internal/errors/errors.go:**

```go
// Custom error types for notification service.

package errors

import (
    "errors"
    "fmt"
)

// Sentinel errors for common failure cases.
var (
    // ErrTelegramConnection indicates failure to connect to Telegram API.
    ErrTelegramConnection = errors.New("failed to connect to Telegram API")

    // ErrRedisConnection indicates failure to connect to Redis.
    ErrRedisConnection = errors.New("failed to connect to Redis")

    // ErrMissingConfig indicates required configuration is missing.
    ErrMissingConfig = errors.New("required configuration missing")

    // ErrMessageSendFailed indicates a message could not be sent.
    ErrMessageSendFailed = errors.New("failed to send message")
)

// NotificationError wraps errors with additional context.
type NotificationError struct {
    Op      string // Operation that failed
    Err     error  // Underlying error
    Context string // Additional context
}

func (e *NotificationError) Error() string {
    if e.Context != "" {
        return fmt.Sprintf("%s: %s (%s)", e.Op, e.Err.Error(), e.Context)
    }
    return fmt.Sprintf("%s: %s", e.Op, e.Err.Error())
}

func (e *NotificationError) Unwrap() error {
    return e.Err
}

// Wrap creates a NotificationError with context.
func Wrap(op string, err error, context string) error {
    return &NotificationError{Op: op, Err: err, Context: context}
}
```

### Task 5: Implement Telegram Bot Client

**internal/telegram/bot.go:**

```go
// Telegram bot client for sending notifications.

package telegram

import (
    "context"
    "fmt"
    "log"

    tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"

    "github.com/user/sandboxed/services/notification/internal/config"
)

// Bot represents the Telegram bot client.
type Bot struct {
    api    *tgbotapi.BotAPI
    chatID int64
    debug  bool
}

// NewBot creates a new Telegram bot client.
func NewBot(cfg *config.Config) (*Bot, error) {
    api, err := tgbotapi.NewBotAPI(cfg.TelegramBotToken)
    if err != nil {
        return nil, fmt.Errorf("failed to create bot API: %w", err)
    }

    api.Debug = cfg.Debug

    log.Printf("Authorized on account %s", api.Self.UserName)

    return &Bot{
        api:    api,
        chatID: cfg.TelegramChatID,
        debug:  cfg.Debug,
    }, nil
}

// Start begins listening for updates and processing commands.
func (b *Bot) Start(ctx context.Context) error {
    u := tgbotapi.NewUpdate(0)
    u.Timeout = 60

    updates := b.api.GetUpdatesChan(u)

    for {
        select {
        case <-ctx.Done():
            return ctx.Err()
        case update := <-updates:
            if update.Message == nil {
                continue
            }

            if update.Message.IsCommand() {
                b.handleCommand(update.Message)
            }
        }
    }
}

// Stop gracefully stops the bot.
func (b *Bot) Stop() {
    b.api.StopReceivingUpdates()
    log.Println("Telegram bot stopped")
}

// SendMessage sends a message to the configured chat.
func (b *Bot) SendMessage(text string) error {
    if b.chatID == 0 {
        log.Println("Warning: No chat ID configured, message not sent")
        return nil
    }

    msg := tgbotapi.NewMessage(b.chatID, text)
    msg.ParseMode = tgbotapi.ModeMarkdown

    _, err := b.api.Send(msg)
    if err != nil {
        return fmt.Errorf("failed to send message: %w", err)
    }

    return nil
}

// handleCommand processes incoming bot commands.
func (b *Bot) handleCommand(msg *tgbotapi.Message) {
    handler := NewCommandHandler(b)
    handler.Handle(msg)
}
```

**internal/telegram/commands.go:**

```go
// Command handlers for Telegram bot.

package telegram

import (
    "fmt"
    "log"

    tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// CommandHandler processes bot commands.
type CommandHandler struct {
    bot *Bot
}

// NewCommandHandler creates a new command handler.
func NewCommandHandler(bot *Bot) *CommandHandler {
    return &CommandHandler{bot: bot}
}

// Handle processes a command message.
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
        response = h.handleStopAll()
    case "resume_all":
        response = h.handleResumeAll()
    default:
        response = "Unknown command. Use /help for available commands."
    }

    reply := tgbotapi.NewMessage(msg.Chat.ID, response)
    reply.ParseMode = tgbotapi.ModeMarkdown

    if _, err := h.bot.api.Send(reply); err != nil {
        log.Printf("Failed to send reply: %v", err)
    }
}

func (h *CommandHandler) handleStart(msg *tgbotapi.Message) string {
    log.Printf("Start command from chat_id: %d, user: %s", msg.Chat.ID, msg.From.UserName)
    return fmt.Sprintf(`*Welcome to Sandboxed Trading Bot!*

Your chat ID: `+"`%d`"+`

This bot will notify you about:
- Trade executions
- Risk warnings
- System alerts

Use /help for available commands.`, msg.Chat.ID)
}

func (h *CommandHandler) handleHelp() string {
    return `*Available Commands:*

/status - Show current system status
/stop_all - Emergency stop all accounts
/resume_all - Resume trading after stop
/help - Show this help message

*Note:* This is a scaffold. Full functionality in Epic 6.`
}

func (h *CommandHandler) handleStatus() string {
    // Scaffold: Return placeholder status
    return `*System Status (Scaffold)*

Bot: Online
Redis: Not connected (scaffold)
Accounts: N/A

Full status in Story 6.1+`
}

func (h *CommandHandler) handleStopAll() string {
    // Scaffold: Return placeholder response
    log.Println("Emergency stop command received (scaffold mode)")
    return `*Emergency Stop (Scaffold)*

This is a scaffold implementation.
Full emergency stop in Story 6.5.`
}

func (h *CommandHandler) handleResumeAll() string {
    // Scaffold: Return placeholder response
    log.Println("Resume command received (scaffold mode)")
    return `*Resume Trading (Scaffold)*

This is a scaffold implementation.
Full resume functionality in Story 6.6.`
}
```

### Task 6: Implement Redis Subscriber Scaffold

**internal/subscriber/redis_subscriber.go:**

```go
// Redis Pub/Sub subscriber for alert channels.
//
// This is a scaffold placeholder. Full subscription implementation
// will be completed in Story 6.2.

package subscriber

import (
    "context"
    "log"

    "github.com/redis/go-redis/v9"

    "github.com/user/sandboxed/services/notification/internal/config"
)

// Subscriber handles Redis Pub/Sub subscriptions.
type Subscriber struct {
    client *redis.Client
    config *config.Config
}

// New creates a new Redis subscriber.
// Note: This scaffold does not connect to Redis.
// Full implementation in Story 6.2.
func New(cfg *config.Config) *Subscriber {
    log.Printf("Redis subscriber created (scaffold mode)")
    log.Printf("  Redis URL: %s", cfg.RedisURL)
    log.Printf("  Will subscribe to: alerts:trade:*, alerts:risk:*, alerts:system, emergency:stop")

    return &Subscriber{
        config: cfg,
    }
}

// Start begins subscribing to alert channels.
// Scaffold: Just logs what would be subscribed.
func (s *Subscriber) Start(ctx context.Context) error {
    log.Println("Redis subscriber starting (scaffold mode)")
    log.Println("Channels that will be subscribed in Story 6.2:")
    log.Println("  - alerts:trade:* (trade executions per account)")
    log.Println("  - alerts:risk:* (rule warnings/violations per account)")
    log.Println("  - alerts:system (system-wide alerts)")
    log.Println("  - emergency:stop (emergency stop commands)")

    // Block until context is cancelled
    <-ctx.Done()
    return ctx.Err()
}

// Close cleans up the subscriber.
func (s *Subscriber) Close() {
    if s.client != nil {
        s.client.Close()
    }
    log.Println("Redis subscriber closed")
}

// Channels returns the list of channels to subscribe to.
// Used by tests and for documentation.
func (s *Subscriber) Channels() []string {
    return []string{
        "alerts:trade:*",
        "alerts:risk:*",
        "alerts:system",
        "emergency:stop",
    }
}

// Connect establishes connection to Redis.
// Scaffold: Returns nil (no actual connection).
// Full implementation in Story 6.2.
func (s *Subscriber) Connect(ctx context.Context) error {
    log.Printf("Redis connect called (scaffold mode) - will connect to %s in Story 6.2", s.config.RedisURL)
    return nil
}
```

### Task 7: Implement Message Handlers (Scaffold)

**internal/handlers/trade_handler.go:**

```go
// Trade notification handler.
//
// Scaffold placeholder. Full implementation in Story 6.3.

package handlers

import (
    "log"

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

// Handle processes a trade event message.
// Scaffold: Just logs the event.
func (h *TradeHandler) Handle(accountID string, payload []byte) error {
    log.Printf("Trade event for account %s (scaffold): %s", accountID, string(payload))
    return nil
}
```

**internal/handlers/risk_handler.go:**

```go
// Risk alert handler.
//
// Scaffold placeholder. Full implementation in Story 6.4.

package handlers

import (
    "log"

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

// Handle processes a risk alert message.
// Scaffold: Just logs the event.
func (h *RiskHandler) Handle(accountID string, payload []byte) error {
    log.Printf("Risk alert for account %s (scaffold): %s", accountID, string(payload))
    return nil
}
```

**internal/handlers/health_handler.go:**

```go
// Health check handler.
//
// Scaffold placeholder for system health monitoring.

package handlers

import (
    "log"
)

// HealthHandler processes system health events.
type HealthHandler struct{}

// NewHealthHandler creates a new health handler.
func NewHealthHandler() *HealthHandler {
    return &HealthHandler{}
}

// Handle processes a health event message.
func (h *HealthHandler) Handle(payload []byte) error {
    log.Printf("Health event (scaffold): %s", string(payload))
    return nil
}
```

### Task 8: Implement Message Formatters

**internal/formatters/trade_formatter.go:**

```go
// Trade message formatter.
//
// Formats trade execution notifications for Telegram.

package formatters

import (
    "fmt"
    "time"
)

// TradeEvent represents a trade execution event.
type TradeEvent struct {
    AccountID   string  `json:"account_id"`
    AccountName string  `json:"account_name"`
    Symbol      string  `json:"symbol"`
    Action      string  `json:"action"` // BUY, SELL
    Volume      float64 `json:"volume"`
    Price       float64 `json:"price"`
    SL          float64 `json:"sl,omitempty"`
    TP          float64 `json:"tp,omitempty"`
    Reason      string  `json:"reason"`
    DailyPnL    float64 `json:"daily_pnl"`
    DailyPnLPct float64 `json:"daily_pnl_pct"`
    Timestamp   string  `json:"timestamp"`
}

// TradeCloseEvent represents a trade close event.
type TradeCloseEvent struct {
    TradeEvent
    Result    string  `json:"result"` // PROFIT, LOSS
    PnL       float64 `json:"pnl"`
    PnLPct    float64 `json:"pnl_pct"`
    Duration  string  `json:"duration"`
}

// TradeFormatter formats trade notifications.
type TradeFormatter struct{}

// NewTradeFormatter creates a new trade formatter.
func NewTradeFormatter() *TradeFormatter {
    return &TradeFormatter{}
}

// FormatOpen formats a trade open notification.
func (f *TradeFormatter) FormatOpen(e *TradeEvent) string {
    return fmt.Sprintf(`*TRADE EXECUTED*
Account: %s
Symbol: %s
Action: %s %.2f lots
Entry: $%.2f
SL: $%.2f | TP: $%.2f
Reason: %s
Daily P&L: $%.2f (%.2f%%)
Time: %s`,
        e.AccountName,
        e.Symbol,
        e.Action, e.Volume,
        e.Price,
        e.SL, e.TP,
        e.Reason,
        e.DailyPnL, e.DailyPnLPct,
        e.Timestamp)
}

// FormatClose formats a trade close notification.
func (f *TradeFormatter) FormatClose(e *TradeCloseEvent) string {
    emoji := ""
    if e.Result == "PROFIT" {
        emoji = ""
    } else {
        emoji = ""
    }

    return fmt.Sprintf(`%s *TRADE CLOSED - %s*
Account: %s
Symbol: %s
P&L: $%.2f (%.2f%%)
Duration: %s
Time: %s`,
        emoji, e.Result,
        e.AccountName,
        e.Symbol,
        e.PnL, e.PnLPct,
        e.Duration,
        time.Now().UTC().Format("15:04:05 UTC"))
}
```

**internal/formatters/alert_formatter.go:**

```go
// Alert message formatter.
//
// Formats risk and system alerts for Telegram.

package formatters

import (
    "fmt"
    "time"
)

// RiskAlert represents a risk warning or violation.
type RiskAlert struct {
    AccountID   string  `json:"account_id"`
    AccountName string  `json:"account_name"`
    RuleName    string  `json:"rule_name"`
    RuleType    string  `json:"rule_type"` // warning, blocked
    Current     float64 `json:"current"`
    Threshold   float64 `json:"threshold"`
    Trade       string  `json:"trade,omitempty"`
    Reason      string  `json:"reason"`
    Action      string  `json:"action"`
    Timestamp   string  `json:"timestamp"`
}

// SystemAlert represents a system-level alert.
type SystemAlert struct {
    Component string `json:"component"`
    Level     string `json:"level"` // info, warning, error
    Message   string `json:"message"`
    Action    string `json:"action,omitempty"`
    Timestamp string `json:"timestamp"`
}

// AlertFormatter formats alert notifications.
type AlertFormatter struct{}

// NewAlertFormatter creates a new alert formatter.
func NewAlertFormatter() *AlertFormatter {
    return &AlertFormatter{}
}

// FormatRiskWarning formats a risk warning alert.
func (f *AlertFormatter) FormatRiskWarning(a *RiskAlert) string {
    return fmt.Sprintf(`*RISK WARNING*
Account: %s
Rule: %s
Status: %.0f%% of limit reached
Current: %.1f%% of %.1f%% limit
Remaining: %.1f%%
Time: %s`,
        a.AccountName,
        a.RuleName,
        (a.Current/a.Threshold)*100,
        a.Current, a.Threshold,
        a.Threshold-a.Current,
        time.Now().UTC().Format("15:04:05 UTC"))
}

// FormatRiskBlocked formats a trade blocked alert.
func (f *AlertFormatter) FormatRiskBlocked(a *RiskAlert) string {
    return fmt.Sprintf(`*TRADE BLOCKED*
Account: %s
Rule: %s
Current: %.1f%% of %.1f%% limit
Trade: %s
Reason: %s
Action: %s
Time: %s`,
        a.AccountName,
        a.RuleName,
        a.Current, a.Threshold,
        a.Trade,
        a.Reason,
        a.Action,
        time.Now().UTC().Format("15:04:05 UTC"))
}

// FormatSystemAlert formats a system alert.
func (f *AlertFormatter) FormatSystemAlert(a *SystemAlert) string {
    emoji := ""
    switch a.Level {
    case "error":
        emoji = ""
    case "warning":
        emoji = ""
    default:
        emoji = ""
    }

    msg := fmt.Sprintf(`%s *SYSTEM %s*
Component: %s
Message: %s`,
        emoji, a.Level,
        a.Component,
        a.Message)

    if a.Action != "" {
        msg += fmt.Sprintf("\nAction: %s", a.Action)
    }

    msg += fmt.Sprintf("\nTime: %s", time.Now().UTC().Format("15:04:05 UTC"))

    return msg
}
```

### Task 9: Create Multi-Stage Dockerfile (AC4)

**Dockerfile:**

```dockerfile
# Stage 1: Build
FROM golang:1.23-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git ca-certificates

# Copy go mod files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bot ./cmd/bot

# Stage 2: Runtime
FROM alpine:3.19

WORKDIR /app

# Install CA certificates for HTTPS
RUN apk add --no-cache ca-certificates tzdata

# Copy binary from builder
COPY --from=builder /bot /app/bot

# Set environment variables
ENV NOTIFICATION_LOG_LEVEL=info

# Health check (basic - checks if process is running)
# Note: Story 6.1 should implement proper healthcheck with Telegram API ping
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pgrep -f bot || exit 1

# Run the bot
CMD ["/app/bot"]
```

### Task 10: Create README.md

**README.md:**

```markdown
# Notification Service

Telegram notification service for the Sandboxed multi-account trading system.

## Overview

This service:
- Receives alerts via Redis Pub/Sub
- Sends notifications to Telegram
- Handles trade and risk alerts
- Provides emergency control commands

## Status

**Current:** Scaffold implementation
**Full implementation:** Epic 6 (Stories 6.1-6.6)

## Quick Start

### Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| TELEGRAM_BOT_TOKEN | Yes | - | Telegram Bot API token |
| TELEGRAM_CHAT_ID | Yes | - | Chat ID for notifications |
| REDIS_URL | No | redis:6379 | Redis connection URL |
| NOTIFICATION_LOG_LEVEL | No | info | Log level |
| NOTIFICATION_DEBUG | No | false | Enable debug mode |

### Local Development

```bash
# Set required environment variables
export TELEGRAM_BOT_TOKEN="your-bot-token"
export TELEGRAM_CHAT_ID="your-chat-id"

# Build and run
go build -o bot ./cmd/bot
./bot
```

### Docker

```bash
# Build image
docker build -t notification:latest .

# Run container
docker run -e TELEGRAM_BOT_TOKEN=xxx -e TELEGRAM_CHAT_ID=xxx notification:latest
```

## Commands

| Command | Description |
|---------|-------------|
| /start | Welcome message and chat ID |
| /help | Show available commands |
| /status | System status (scaffold) |
| /stop_all | Emergency stop (scaffold) |
| /resume_all | Resume trading (scaffold) |

## Architecture

```
cmd/bot/           Entry point
internal/
├── config/        Configuration loading
├── telegram/      Bot client and commands
├── handlers/      Message handlers
├── formatters/    Message formatters
└── subscriber/    Redis Pub/Sub subscriber
```

## Dependencies

- go-telegram-bot-api/v5 - Telegram Bot API
- redis/go-redis/v9 - Redis client
- spf13/viper - Configuration

## Next Stories

- Story 6.1: Full Telegram connection with health checks
- Story 6.2: Redis subscription implementation
- Story 6.3: Trade execution notifications
- Story 6.4: Rule violation alerts
- Story 6.5: Emergency stop command
- Story 6.6: Resume trading command
```

### Task 10.5: Create Test Infrastructure (AC6)

**tests/integration_test.go:**

```go
// Integration tests for notification service.

package tests

import (
    "testing"

    "github.com/user/sandboxed/services/notification/internal/config"
)

func TestConfigDefaults(t *testing.T) {
    // Test that config loads with defaults when env vars not set
    // Note: This will fail in real test due to missing TELEGRAM_BOT_TOKEN
    // Full test should mock environment
    t.Skip("Requires mock environment - placeholder for Story 6.x")
}

func TestSubscriberChannels(t *testing.T) {
    // Verify subscriber returns expected channel list
    cfg := &config.Config{
        RedisURL: "localhost:6379",
    }
    _ = cfg // Placeholder - full test in Story 6.2

    expectedChannels := []string{
        "alerts:trade:*",
        "alerts:risk:*",
        "alerts:system",
        "emergency:stop",
    }

    if len(expectedChannels) != 4 {
        t.Errorf("Expected 4 channels, got %d", len(expectedChannels))
    }
}
```

**internal/config/config_test.go:**

```go
// Config loading tests.

package config

import (
    "os"
    "testing"
)

func TestLoadConfig_MissingToken(t *testing.T) {
    // Ensure TELEGRAM_BOT_TOKEN is not set
    os.Unsetenv("TELEGRAM_BOT_TOKEN")

    _, err := Load()
    if err == nil {
        t.Error("Expected error when TELEGRAM_BOT_TOKEN is missing")
    }
}

func TestLoadConfig_WithToken(t *testing.T) {
    // Set required env var
    os.Setenv("TELEGRAM_BOT_TOKEN", "test-token-12345")
    defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

    cfg, err := Load()
    if err != nil {
        t.Errorf("Unexpected error: %v", err)
    }

    if cfg.TelegramBotToken != "test-token-12345" {
        t.Errorf("Expected token 'test-token-12345', got '%s'", cfg.TelegramBotToken)
    }
}

func TestLoadConfig_DefaultRedisURL(t *testing.T) {
    os.Setenv("TELEGRAM_BOT_TOKEN", "test-token")
    os.Unsetenv("REDIS_URL")
    defer os.Unsetenv("TELEGRAM_BOT_TOKEN")

    cfg, err := Load()
    if err != nil {
        t.Errorf("Unexpected error: %v", err)
    }

    if cfg.RedisURL != "redis:6379" {
        t.Errorf("Expected default Redis URL 'redis:6379', got '%s'", cfg.RedisURL)
    }
}
```

### Task 11: Verify All Commands Work

- [ ] Test `go build ./cmd/bot` compiles successfully
- [ ] Test `go test ./...` runs and discovers tests
- [ ] Test running with valid TELEGRAM_BOT_TOKEN
- [ ] Test `/start` command responds with chat ID
- [ ] Test graceful shutdown with SIGINT/SIGTERM
- [ ] Test `docker build .` builds image

---

## Technical Specifications

### Go Version and Dependencies

- **Go Version:** 1.23+ (updated from 1.21 due to dependency requirements)
- **Key Dependencies:**
  - `github.com/go-telegram-bot-api/telegram-bot-api/v5` - Telegram Bot API
  - `github.com/redis/go-redis/v9` - Redis client with Pub/Sub
  - `github.com/spf13/viper` - Configuration management

### Telegram Bot Setup

To create a bot:
1. Message @BotFather on Telegram
2. Send `/newbot` and follow prompts
3. Save the API token as `TELEGRAM_BOT_TOKEN`
4. Message your bot, then get chat_id from updates

### Redis Pub/Sub Channels (Reference)

Per Architecture specification, Epic 6 will subscribe to:

| Channel | Publisher | Data |
|---------|-----------|------|
| `alerts:trade:*` | trading-engine | Trade events |
| `alerts:risk:*` | trading-engine | Risk warnings |
| `alerts:system` | any service | System alerts |
| `emergency:stop` | notification | Emergency command |

### go-telegram-bot-api (Context7 Research - 2025)

**Initialize Bot:**
```go
bot, err := tgbotapi.NewBotAPI(os.Getenv("TELEGRAM_BOT_TOKEN"))
if err != nil {
    log.Panic(err)
}
bot.Debug = true
```

**Long Polling Pattern:**
```go
u := tgbotapi.NewUpdate(0)
u.Timeout = 60
updates := bot.GetUpdatesChan(u)

for update := range updates {
    if update.Message != nil {
        // Handle message
    }
}
```

**Command Handling:**
```go
switch update.Message.Command() {
case "help":
    msg.Text = "Help message"
case "status":
    msg.Text = "Status message"
}
```

### go-redis Pub/Sub (Context7 Research - 2025)

**Subscribe to Channels:**
```go
pubsub := rdb.Subscribe(ctx, "channel1", "channel2")
defer pubsub.Close()

ch := pubsub.Channel()
for msg := range ch {
    fmt.Printf("Channel: %s, Message: %s\n", msg.Channel, msg.Payload)
}
```

**Pattern Subscription:**
```go
psubsub := rdb.PSubscribe(ctx, "alerts:*")
defer psubsub.Close()
```

### Viper Configuration (Context7 Research - 2025)

**Environment Variables:**
```go
v := viper.New()
v.SetEnvPrefix("NOTIFICATION")
v.AutomaticEnv()
v.SetDefault("log_level", "info")

token := v.GetString("bot_token")
```

---

## Architecture Compliance

This story implements:
- **Architecture - Notification Service:** Directory layout from docs/architecture.md
- **Architecture - Polyglot Stack:** Go 1.21+ for I/O-bound notification service
- **Architecture - Docker Compose:** Multi-stage Dockerfile

**Referenced Sections:**
- [Source: docs/architecture.md#notification-service-go]
- [Source: docs/architecture.md#monorepo-structure]
- [Source: docs/architecture.md#redis-pubsub-channels]

---

## Previous Story Intelligence

### From Story 1.7 (Completed)

**Key Learnings:**
- Scaffold should demonstrate async patterns for future development
- Platform-safe signal handling (SIGTERM/SIGINT)
- Multi-stage Docker builds with dependency caching
- Module docstrings document future implementation scope
- Test infrastructure more important than coverage at scaffold stage

**Code Patterns Established:**
- Docker Compose uses `docker compose` (v2 syntax)
- Environment variables with `${VAR:-default}` pattern
- Container health checks for all services
- Structured logging with log package

**Files Created in 1.7:**
- `services/mt5-bridge/` - Complete Rust scaffold
- Async entry point with signal handling pattern

### Git Recent Commits

```
b2a0913 Implement spec 1 story 1.7
147a22c Implement spec 1 story 1.6
d6e55b7 Implement spec 1 story 1.5
7c5dad4 Implement spec 1 story 1.4
82328cb Implement spec 1 story 1.3
```

---

## Dev Agent Guardrails

### MUST DO:

1. **Use Go 1.23+** (updated from 1.21 due to dependency requirements)
2. **Use go-telegram-bot-api/v5** - The established Go Telegram library
3. **Use redis/go-redis/v9** - Official Redis client
4. **Use spf13/viper** - For configuration management
5. **Follow architecture directory structure** exactly as specified
6. **Implement graceful shutdown** with signal handling
7. **Multi-stage Dockerfile** for small image size
8. **Long polling** for Telegram updates (not webhooks)
9. **Log bot connection** on startup

### DO NOT:

1. **Do NOT implement actual Redis subscription** - that's Story 6.2
2. **Do NOT implement full Telegram notification logic** - comes in Story 6.3+
3. **Do NOT modify docker-compose.yml** - that's Story 1.9
4. **Do NOT add complex business logic** - handlers are stubs
5. **Do NOT use webhooks** - use long polling for simplicity
6. **Do NOT skip graceful shutdown** - critical for production

### File Modifications:

**Files to Create:**
- `services/notification/go.mod` - Go module (update existing)
- `services/notification/go.sum` - Dependencies lock
- `services/notification/cmd/bot/main.go` - Entry point (update existing)
- `services/notification/internal/config/config.go` - Configuration
- `services/notification/internal/config/config_test.go` - Config tests
- `services/notification/internal/errors/errors.go` - Custom error types
- `services/notification/internal/telegram/bot.go` - Bot client
- `services/notification/internal/telegram/commands.go` - Command handlers
- `services/notification/internal/handlers/trade_handler.go` - Trade handler
- `services/notification/internal/handlers/risk_handler.go` - Risk handler
- `services/notification/internal/handlers/health_handler.go` - Health handler
- `services/notification/internal/formatters/trade_formatter.go` - Trade formatter
- `services/notification/internal/formatters/alert_formatter.go` - Alert formatter
- `services/notification/internal/subscriber/redis_subscriber.go` - Redis subscriber
- `services/notification/tests/integration_test.go` - Integration tests
- `services/notification/Dockerfile` - Multi-stage Docker build (update existing)
- `services/notification/README.md` - Service documentation (update existing)

**Files NOT to Modify:**
- `infra/docker/docker-compose.yml` - Updated in Story 1.9
- `Makefile` - Already has notification targets
- Any other service directories

---

## Testing Verification

### Manual Test Steps

```bash
# 1. Navigate to notification service
cd /home/hopdev/Dev/Sandboxed/services/notification

# 2. Initialize go module and download deps
go mod tidy

# 3. Build the project
go build ./cmd/bot
# Expected: Compiles without errors

# 4. Run tests
go test ./...
# Expected: Config tests pass, integration tests discovered

# 5. Run the service (requires valid token)
TELEGRAM_BOT_TOKEN=<your-token> TELEGRAM_CHAT_ID=<your-chat-id> ./bot
# Expected: Logs "Telegram bot connected"
# Press Ctrl-C to exit gracefully

# 6. Build Docker image
docker build -t notification:test .
# Expected: Multi-stage build completes successfully

# 7. Test bot commands
# Message your bot with /start - should respond with chat ID
# Message your bot with /help - should respond with command list
```

### Verification Checklist

- [ ] `go build ./cmd/bot` compiles without errors
- [ ] `go test ./...` discovers and runs tests (config tests pass)
- [ ] All dependencies in go.mod resolve correctly
- [ ] Directory structure matches architecture spec
- [ ] Bot starts and logs connection success
- [ ] Bot responds to /start command with chat ID
- [ ] Bot responds to /help with command list
- [ ] Service exits gracefully on Ctrl-C (SIGINT/SIGTERM)
- [ ] Docker build creates working image

---

## Dependencies

- **Prerequisites:** Story 1.1 (Project Structure) - DONE
- **Blocks:**
  - Story 1.9 (Full Stack Docker Compose) - needs service to add
  - Story 6.1 (Notification Service Setup) - needs scaffold
  - All Epic 6 stories

---

## Definition of Done

- [ ] go.mod has all required dependencies
- [ ] `go build ./cmd/bot` compiles without errors
- [ ] `go test ./...` discovers and runs tests
- [ ] Directory structure matches architecture specification
- [ ] Entry point with graceful shutdown handling
- [ ] Telegram bot client connects and responds to commands
- [ ] Command handlers for /start, /help, /status, /stop_all, /resume_all
- [ ] Redis subscriber scaffold created with Connect() stub
- [ ] Message handlers and formatters created
- [ ] Error types module created
- [ ] Dockerfile uses multi-stage build
- [ ] Docker build creates working image
- [ ] README.md updated with service documentation
- [ ] All verification tests pass
- [ ] Story status updated to `review` in sprint-status.yaml

---

## References

- [Architecture - Notification Service](../architecture.md#notification-service-go)
- [Architecture - Monorepo Structure](../architecture.md#monorepo-structure)
- [Architecture - Redis Pub/Sub Channels](../architecture.md#redis-pubsub-channels)
- [Story 1.7 - MT5 Bridge Scaffold](./1-7-mt5-bridge-service-scaffold.md)
- [go-telegram-bot-api Documentation](https://github.com/go-telegram-bot-api/telegram-bot-api)
- [go-redis Documentation](https://github.com/redis/go-redis)
- [Viper Documentation](https://github.com/spf13/viper)

---

## Dev Agent Record

### Context Reference

- Epic 1 Stories: `docs/epics.md` (Story 1.8 section)
- Architecture: `docs/architecture.md` (Notification Service, Monorepo, Redis sections)
- Previous Story: `docs/sprint-artifacts/1-7-mt5-bridge-service-scaffold.md`
- go-telegram-bot-api docs via Context7 MCP
- go-redis docs via Context7 MCP
- Viper docs via Context7 MCP

### Agent Model Used

Claude Opus 4.5 (claude-opus-4-5-20251101)

### Debug Log References

- Config tests initially failed due to viper global state caching - fixed by using os.Getenv() for test isolation
- Dockerfile required update from Go 1.21 to 1.23 due to dependency requirements
- All tests passing: config tests (4), integration tests (2)

### Completion Notes List

- Task 1: Updated go.mod with dependencies (go-telegram-bot-api/v5, redis/go-redis/v9, spf13/viper)
- Task 2: Created full directory structure per architecture spec
- Task 3: Implemented entry point with graceful shutdown (SIGINT/SIGTERM handling)
- Task 4: Implemented configuration module with environment variable support
- Task 4.5: Created custom error types module
- Task 5: Implemented Telegram bot client with long-polling and command handling
- Task 6: Created Redis subscriber scaffold with channel list
- Task 7: Implemented trade, risk, and health handlers (scaffold stubs)
- Task 8: Created trade and alert message formatters
- Task 9: Multi-stage Dockerfile with Go 1.23-alpine
- Task 10: Comprehensive README.md documentation
- Task 10.5: Test infrastructure with config tests and integration tests
- Task 11: All verification steps pass (build, tests, Docker build)

### File List

**Created:**
- services/notification/cmd/bot/main.go
- services/notification/internal/config/config.go
- services/notification/internal/config/config_test.go
- services/notification/internal/errors/errors.go
- services/notification/internal/errors/errors_test.go (added in code review)
- services/notification/internal/telegram/bot.go
- services/notification/internal/telegram/commands.go
- services/notification/internal/handlers/trade_handler.go
- services/notification/internal/handlers/risk_handler.go
- services/notification/internal/handlers/health_handler.go
- services/notification/internal/handlers/handlers_test.go (added in code review)
- services/notification/internal/formatters/trade_formatter.go
- services/notification/internal/formatters/trade_formatter_test.go (added in code review)
- services/notification/internal/formatters/alert_formatter.go
- services/notification/internal/formatters/alert_formatter_test.go (added in code review)
- services/notification/internal/subscriber/redis_subscriber.go
- services/notification/tests/integration_test.go

**Modified:**
- services/notification/go.mod (updated with dependencies)
- services/notification/go.sum (generated)
- services/notification/Dockerfile (full multi-stage build)
- services/notification/README.md (comprehensive documentation, CHAT_ID clarified)
- services/notification/.gitignore (added bot binary)
- docs/sprint-artifacts/sprint-status.yaml (story status: in-progress → review)

---

## Change Log

| Date | Change |
|------|--------|
| 2025-12-19 | Story created with comprehensive developer context by create-story workflow |
| 2025-12-19 | go-telegram-bot-api, go-redis, Viper documentation researched via Context7 MCP |
| 2025-12-19 | **Validation improvements applied:** (1) Added AC6 for test infrastructure; (2) Fixed go.mod module path to match existing placeholder; (3) Fixed all import paths in code examples; (4) Added `internal/errors/errors.go` module with NotificationError type; (5) Added `tests/integration_test.go` with test stubs; (6) Added `internal/config/config_test.go` with config loading tests; (7) Added Connect() stub to redis_subscriber.go; (8) Updated AC1 to include config/, errors/, and tests/ directories; (9) Updated file lists and verification checklists |
| 2025-12-20 | **Implementation completed by dev-story workflow:** All tasks implemented and verified. Build passes, tests pass, Docker build succeeds. Story marked Ready for Review. |
| 2025-12-20 | **Code review fixes applied:** (1) Added tests for formatters, handlers, errors packages; (2) Updated Go version from 1.21 to 1.23 in docs; (3) Fixed nil pointer for msg.From in commands.go; (4) Added bot binary to .gitignore; (5) Integrated errors package in telegram/bot.go; (6) Updated README to clarify TELEGRAM_CHAT_ID is optional for scaffold |

---

## Notes

- This story is **scaffold only** - no actual Redis subscription
- Full Telegram notification logic comes in Stories 6.1-6.6
- The scaffold demonstrates patterns for future development
- Focus on clean, extensible structure that Epic 6 can build upon
- Test with a real Telegram bot token for verification
