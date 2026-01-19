// Package telegram provides the Telegram bot client for sending notifications.
package telegram

import (
	"context"
	"encoding/json"
	"fmt"
	"log"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"
	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/errors"
)

// healthCheckTTL defines how long a health check result is cached.
const healthCheckTTL = 30 * time.Second

// EmergencyStopCommand represents a stop command sent to the trading engine.
type EmergencyStopCommand struct {
	Type        string `json:"type"`
	Command     string `json:"command"`
	Initiator   string `json:"initiator"`
	InitiatedBy string `json:"initiated_by"`
	ChatID      int64  `json:"chat_id"`
	Timestamp   string `json:"timestamp"`
}

// Bot represents the Telegram bot client.
type Bot struct {
	api             *tgbotapi.BotAPI
	chatID          int64
	debug           bool
	username        string
	healthy         atomic.Bool
	lastHealthCheck atomic.Int64 // Unix timestamp of last health check
	publisher       *redis.Client // Redis client for publishing commands
	stopActive      atomic.Bool   // Track if emergency stop is active
}

// NewBot creates a new Telegram bot client with exponential backoff retry.
func NewBot(cfg *config.Config) (*Bot, error) {
	return NewBotWithContext(context.Background(), cfg)
}

// NewBotWithContext creates a new Telegram bot client with context for graceful shutdown.
func NewBotWithContext(ctx context.Context, cfg *config.Config) (*Bot, error) {
	api, err := connectWithRetry(ctx, cfg.TelegramBotToken, cfg.MaxRetries, cfg.RetryBaseDelay, cfg.MaxRetryDelay)
	if err != nil {
		return nil, errors.Wrap("NewBot", errors.ErrTelegramConnection, err.Error())
	}

	api.Debug = cfg.Debug

	// Perform health check via GetMe to verify connection
	user, err := api.GetMe()
	if err != nil {
		return nil, errors.Wrap("NewBot", errors.ErrTelegramConnection, fmt.Sprintf("health check failed: %v", err))
	}

	log.Printf("Telegram bot connected: @%s (ID: %d)", user.UserName, user.ID)

	// Initialize Redis publisher for emergency commands
	publisher := redis.NewClient(&redis.Options{
		Addr:     cfg.RedisURL,
		Password: cfg.RedisPassword,
	})

	// Verify Redis connection
	if err := publisher.Ping(ctx).Err(); err != nil {
		log.Printf("Warning: Redis publisher ping failed: %v (commands may fail)", err)
	} else {
		log.Printf("Redis publisher connected: %s", cfg.RedisURL)
	}

	bot := &Bot{
		api:       api,
		chatID:    cfg.TelegramChatID,
		debug:     cfg.Debug,
		username:  user.UserName,
		publisher: publisher,
	}
	bot.healthy.Store(true)
	bot.lastHealthCheck.Store(time.Now().Unix())

	return bot, nil
}

// connectWithRetry attempts to connect to Telegram with exponential backoff.
// Respects context cancellation for graceful shutdown during retry.
func connectWithRetry(ctx context.Context, token string, maxRetries int, baseDelay, maxDelay time.Duration) (*tgbotapi.BotAPI, error) {
	var lastErr error

	for attempt := 0; attempt < maxRetries; attempt++ {
		// Check context before attempting connection
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("connection cancelled: %w", ctx.Err())
		default:
		}

		api, err := tgbotapi.NewBotAPI(token)
		if err == nil {
			if attempt > 0 {
				log.Printf("Telegram connection succeeded on attempt %d", attempt+1)
			}
			return api, nil
		}

		lastErr = err
		delay := baseDelay * time.Duration(1<<attempt) // 1s, 2s, 4s, 8s...
		if delay > maxDelay {
			delay = maxDelay
		}

		log.Printf("Telegram connection attempt %d/%d failed: %v. Retrying in %v",
			attempt+1, maxRetries, err, delay)

		// Respect context cancellation during sleep
		select {
		case <-ctx.Done():
			return nil, fmt.Errorf("connection cancelled during retry: %w", ctx.Err())
		case <-time.After(delay):
			// Continue to next attempt
		}
	}

	return nil, fmt.Errorf("failed to connect after %d attempts: %w", maxRetries, lastErr)
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

// Stop gracefully stops the bot and closes all connections.
func (b *Bot) Stop() {
	b.api.StopReceivingUpdates()
	if err := b.ClosePublisher(); err != nil {
		log.Printf("Warning: failed to close Redis publisher: %v", err)
	}
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
		return errors.Wrap("SendMessage", errors.ErrMessageSendFailed, err.Error())
	}

	return nil
}

// handleCommand processes incoming bot commands.
func (b *Bot) handleCommand(msg *tgbotapi.Message) {
	handler := NewCommandHandler(b)
	handler.Handle(msg)
}

// IsHealthy returns the current health status of the bot.
// Uses cached value if within TTL, otherwise pings Telegram API via GetMe.
func (b *Bot) IsHealthy() bool {
	lastCheck := time.Unix(b.lastHealthCheck.Load(), 0)
	if time.Since(lastCheck) < healthCheckTTL {
		return b.healthy.Load()
	}

	// TTL expired, perform actual health check
	_, err := b.api.GetMe()
	if err != nil {
		b.healthy.Store(false)
		b.lastHealthCheck.Store(time.Now().Unix())
		return false
	}
	b.healthy.Store(true)
	b.lastHealthCheck.Store(time.Now().Unix())
	return true
}

// Username returns the bot's username.
func (b *Bot) Username() string {
	return b.username
}

// ValidateChatID sends a test message to the configured chat ID to verify it's reachable.
// Returns nil if no chat ID is configured (non-blocking warning).
func (b *Bot) ValidateChatID() error {
	if b.chatID == 0 {
		log.Println("Warning: TELEGRAM_CHAT_ID not configured - notifications will not be sent")
		return nil
	}

	testMsg := "✅ Sandboxed Trading Bot connected successfully.\n\nYou will receive trading alerts on this chat."
	msg := tgbotapi.NewMessage(b.chatID, testMsg)
	msg.ParseMode = tgbotapi.ModeMarkdown

	_, err := b.api.Send(msg)
	if err != nil {
		return errors.Wrap("ValidateChatID", errors.ErrMessageSendFailed,
			fmt.Sprintf("failed to send test message to chat %d: %v", b.chatID, err))
	}

	log.Printf("Chat ID %d validated - test message sent successfully", b.chatID)
	return nil
}

// ChatID returns the configured chat ID.
func (b *Bot) ChatID() int64 {
	return b.chatID
}

// IsStopActive returns whether emergency stop is currently active.
func (b *Bot) IsStopActive() bool {
	return b.stopActive.Load()
}

// SetStopActive sets the emergency stop state.
func (b *Bot) SetStopActive(active bool) {
	b.stopActive.Store(active)
}

// PublishEmergencyStop publishes an emergency stop command to Redis.
// Returns error if publish fails. Logs warning if publish exceeds 100ms SLA.
func (b *Bot) PublishEmergencyStop(ctx context.Context, username string, chatID int64) error {
	if b.publisher == nil {
		return fmt.Errorf("Redis publisher not initialized")
	}

	cmd := EmergencyStopCommand{
		Type:        "emergency_stop",
		Command:     "stop_all",
		Initiator:   "telegram",
		InitiatedBy: "@" + username,
		ChatID:      chatID,
		Timestamp:   time.Now().UTC().Format(time.RFC3339),
	}

	payload, err := json.Marshal(cmd)
	if err != nil {
		return fmt.Errorf("failed to marshal emergency stop command: %w", err)
	}

	start := time.Now()
	err = b.publisher.Publish(ctx, "emergency:stop", payload).Err()
	elapsed := time.Since(start)

	if elapsed > 100*time.Millisecond {
		log.Printf("WARNING: Emergency stop publish exceeded 100ms SLA: %v", elapsed)
	}

	if err != nil {
		return fmt.Errorf("failed to publish emergency stop: %w", err)
	}

	log.Printf("Emergency stop published in %v", elapsed)
	return nil
}

// ClosePublisher closes the Redis publisher connection.
func (b *Bot) ClosePublisher() error {
	if b.publisher != nil {
		return b.publisher.Close()
	}
	return nil
}
