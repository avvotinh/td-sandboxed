// Package subscriber provides Redis Pub/Sub subscription for alert channels.
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
