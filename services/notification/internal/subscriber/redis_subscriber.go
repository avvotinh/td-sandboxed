// Package subscriber provides Redis Pub/Sub subscription for alert channels.
package subscriber

import (
	"context"
	"fmt"
	"log"
	"strings"
	"sync/atomic"
	"time"

	"github.com/redis/go-redis/v9"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/errors"
)

// Notifier sends messages to users. Bot implements this interface.
type Notifier interface {
	SendMessage(text string) error
}

// Handler processes messages and returns formatted text for notification.
// Handlers format messages, Router sends via Notifier.
type Handler interface {
	Handle(accountID string, payload []byte) (string, error)
}

// Router routes messages to handlers and sends via Notifier.
type Router struct {
	notifier         Notifier
	tradeHandler     Handler
	riskHandler      Handler
	systemHandler    Handler
	emergencyHandler Handler
}

// NewRouter creates a new message router with the given notifier.
func NewRouter(notifier Notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler Handler) *Router {
	return &Router{
		notifier:         notifier,
		tradeHandler:     tradeHandler,
		riskHandler:      riskHandler,
		systemHandler:    systemHandler,
		emergencyHandler: emergencyHandler,
	}
}

// Route routes a message to the appropriate handler and sends via notifier.
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

	if msg == "" {
		return
	}

	// Fire-and-forget: don't block on send errors
	go func() {
		if err := r.notifier.SendMessage(msg); err != nil {
			log.Printf("Failed to send notification: %v", err)
		}
	}()
}

// extractAccountID extracts the account ID from a channel name.
// e.g., "alerts:trade:ftmo-gold-001" -> "ftmo-gold-001"
func extractAccountID(channel string) string {
	parts := strings.SplitN(channel, ":", 3)
	if len(parts) >= 3 {
		return parts[2]
	}
	return ""
}

// Subscriber handles Redis Pub/Sub subscriptions for alert channels.
type Subscriber struct {
	client    *redis.Client
	pubsub    *redis.PubSub
	config    *config.Config
	router    *Router
	connected atomic.Bool
	channels  []string
}

// New creates a new Redis subscriber.
func New(cfg *config.Config, router *Router) *Subscriber {
	return &Subscriber{
		config: cfg,
		router: router,
		channels: []string{
			"alerts:trade:*",
			"alerts:risk:*",
			"alerts:system",
			"emergency:stop",
		},
	}
}

// Connect establishes connection to Redis with exponential backoff retry.
func (s *Subscriber) Connect(ctx context.Context) error {
	var lastErr error

	for attempt := 0; attempt < s.config.MaxRetries; attempt++ {
		// Check context before attempting connection
		select {
		case <-ctx.Done():
			return fmt.Errorf("connection cancelled: %w", ctx.Err())
		default:
		}

		// Create Redis client
		s.client = redis.NewClient(&redis.Options{
			Addr:     s.config.RedisURL,
			Password: s.config.RedisPassword,
		})

		// Health check via PING
		_, err := s.client.Ping(ctx).Result()
		if err == nil {
			if attempt > 0 {
				log.Printf("Redis connection succeeded on attempt %d", attempt+1)
			}
			s.connected.Store(true)
			log.Printf("Redis connected to %s", s.config.RedisURL)
			return nil
		}

		lastErr = err
		s.client.Close()
		s.client = nil

		delay := s.config.RetryBaseDelay * time.Duration(1<<attempt) // 1s, 2s, 4s, 8s...
		if delay > s.config.MaxRetryDelay {
			delay = s.config.MaxRetryDelay
		}

		log.Printf("Redis connection attempt %d/%d failed: %v. Retrying in %v",
			attempt+1, s.config.MaxRetries, err, delay)

		// Respect context cancellation during sleep
		select {
		case <-ctx.Done():
			return fmt.Errorf("connection cancelled during retry: %w", ctx.Err())
		case <-time.After(delay):
			// Continue to next attempt
		}
	}

	s.connected.Store(false)
	return errors.Wrap("Connect", errors.ErrRedisConnection,
		fmt.Sprintf("failed after %d attempts: %v", s.config.MaxRetries, lastErr))
}

// IsConnected returns whether the subscriber is connected to Redis.
func (s *Subscriber) IsConnected() bool {
	return s.connected.Load()
}

// Channels returns the list of channels to subscribe to.
func (s *Subscriber) Channels() []string {
	return s.channels
}

// Start begins subscribing to alert channels and processing messages.
// This method blocks until the context is cancelled or an unrecoverable error occurs.
func (s *Subscriber) Start(ctx context.Context) error {
	if s.client == nil {
		return errors.Wrap("Start", errors.ErrRedisConnection, "not connected - call Connect first")
	}

	// Subscribe to all channels with single PSubscribe call
	s.pubsub = s.client.PSubscribe(ctx, s.channels...)

	// Wait for subscription confirmation
	_, err := s.pubsub.Receive(ctx)
	if err != nil {
		s.connected.Store(false)
		return errors.Wrap("Subscribe", errors.ErrSubscriptionFailed, err.Error())
	}

	log.Println("Redis subscriber started. Subscribed to channels:")
	for _, ch := range s.channels {
		log.Printf("  - %s", ch)
	}

	// Message loop with reconnection handling
	ch := s.pubsub.Channel()
	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case msg, ok := <-ch:
			if !ok {
				// Channel closed - attempt reconnection
				log.Println("Redis subscription channel closed, attempting reconnection...")
				s.connected.Store(false)

				if err := s.reconnect(ctx); err != nil {
					return errors.Wrap("Reconnect", errors.ErrRedisConnection, err.Error())
				}

				// Re-acquire channel after reconnection
				ch = s.pubsub.Channel()
				continue
			}

			// Route message to appropriate handler
			// msg.Channel = actual channel (e.g., "alerts:trade:ftmo-gold-001")
			// msg.Payload = JSON message content
			s.router.Route(msg.Channel, msg.Payload)
		}
	}
}

// reconnect attempts to reconnect to Redis with exponential backoff.
func (s *Subscriber) reconnect(ctx context.Context) error {
	// Close existing connections
	if s.pubsub != nil {
		s.pubsub.Close()
		s.pubsub = nil
	}
	if s.client != nil {
		s.client.Close()
		s.client = nil
	}

	var lastErr error

	for attempt := 0; attempt < s.config.MaxRetries; attempt++ {
		// Check context before attempting reconnection
		select {
		case <-ctx.Done():
			return fmt.Errorf("reconnection cancelled: %w", ctx.Err())
		default:
		}

		// Create new Redis client
		s.client = redis.NewClient(&redis.Options{
			Addr:     s.config.RedisURL,
			Password: s.config.RedisPassword,
		})

		// Health check via PING
		_, err := s.client.Ping(ctx).Result()
		if err != nil {
			lastErr = err
			s.client.Close()
			s.client = nil

			delay := s.config.RetryBaseDelay * time.Duration(1<<attempt)
			if delay > s.config.MaxRetryDelay {
				delay = s.config.MaxRetryDelay
			}

			log.Printf("Redis reconnection attempt %d/%d failed: %v. Retrying in %v",
				attempt+1, s.config.MaxRetries, err, delay)

			select {
			case <-ctx.Done():
				return fmt.Errorf("reconnection cancelled during retry: %w", ctx.Err())
			case <-time.After(delay):
				continue
			}
		}

		// Re-subscribe to channels
		s.pubsub = s.client.PSubscribe(ctx, s.channels...)

		// Wait for subscription confirmation
		_, err = s.pubsub.Receive(ctx)
		if err != nil {
			lastErr = err
			s.pubsub.Close()
			s.pubsub = nil
			s.client.Close()
			s.client = nil

			delay := s.config.RetryBaseDelay * time.Duration(1<<attempt)
			if delay > s.config.MaxRetryDelay {
				delay = s.config.MaxRetryDelay
			}

			log.Printf("Redis re-subscription attempt %d/%d failed: %v. Retrying in %v",
				attempt+1, s.config.MaxRetries, err, delay)

			select {
			case <-ctx.Done():
				return fmt.Errorf("reconnection cancelled during retry: %w", ctx.Err())
			case <-time.After(delay):
				continue
			}
		}

		s.connected.Store(true)
		log.Printf("Redis reconnected successfully on attempt %d", attempt+1)
		log.Println("Re-subscribed to all channels")
		return nil
	}

	return errors.Wrap("Reconnect", errors.ErrRedisConnection,
		fmt.Sprintf("failed after %d attempts: %v", s.config.MaxRetries, lastErr))
}

// Close cleans up the subscriber connections.
func (s *Subscriber) Close() {
	if s.pubsub != nil {
		s.pubsub.Close()
	}
	if s.client != nil {
		s.client.Close()
	}
	s.connected.Store(false)
	log.Println("Redis subscriber closed")
}
