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
| TELEGRAM_CHAT_ID | No* | - | Chat ID for outbound notifications |
| REDIS_URL | No | redis:6379 | Redis connection URL |
| NOTIFICATION_LOG_LEVEL | No | info | Log level |
| NOTIFICATION_DEBUG | No | false | Enable debug mode |

*Note: TELEGRAM_CHAT_ID is optional for scaffold mode. Without it, the bot can still receive commands but cannot send proactive notifications. Use `/start` command to get your chat ID.

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
├── errors/        Custom error types
├── telegram/      Bot client and commands
├── handlers/      Message handlers
├── formatters/    Message formatters
└── subscriber/    Redis Pub/Sub subscriber
tests/             Integration tests
```

## Dependencies

- go-telegram-bot-api/v5 - Telegram Bot API
- redis/go-redis/v9 - Redis client
- spf13/viper - Configuration

## Testing

```bash
# Run all tests
go test ./...

# Run with verbose output
go test -v ./...
```

## Next Stories

- Story 6.1: Full Telegram connection with health checks
- Story 6.2: Redis subscription implementation
- Story 6.3: Trade execution notifications
- Story 6.4: Rule violation alerts
- Story 6.5: Emergency stop command
- Story 6.6: Resume trading command
