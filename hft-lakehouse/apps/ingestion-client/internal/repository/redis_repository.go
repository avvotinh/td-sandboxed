package repository

import (
	"context"
	"fmt"
	"time"

	"github.com/hft-lakehouse/ingestion-client/internal/parser"
	"github.com/redis/go-redis/v9"
)

// TickRepository defines the interface for tick data storage operations
// Follows Coding Standard Rule #4: Access database via Repository Pattern
type TickRepository interface {
	SaveLatestTick(ctx context.Context, tick *parser.TickData) error
	Close() error
}

// RedisTickRepository implements TickRepository using Redis as the backend
type RedisTickRepository struct {
	client *redis.Client
}

// NewRedisTickRepository creates a new Redis-based tick repository
func NewRedisTickRepository(client *redis.Client) *RedisTickRepository {
	return &RedisTickRepository{
		client: client,
	}
}

// SaveLatestTick saves tick data to Redis using the key pattern: latest_tick:{symbol}
// Follows Redis schema specification from docs/architecture/phn-8-s-database-database-schema.md
// Follows Coding Standard Rule #5: Uses context.Context for I/O operations
func (r *RedisTickRepository) SaveLatestTick(ctx context.Context, tick *parser.TickData) error {
	if tick == nil {
		return fmt.Errorf("tick data is nil")
	}

	if tick.Symbol == "" {
		return fmt.Errorf("tick symbol is empty")
	}

	// Build Redis key following pattern: latest_tick:{symbol}
	key := fmt.Sprintf("latest_tick:%s", tick.Symbol)

	// Prepare hash fields
	// Store numbers as strings, timestamp in RFC3339 format
	fields := map[string]interface{}{
		"bid":       fmt.Sprintf("%.8f", tick.Bid),
		"ask":       fmt.Sprintf("%.8f", tick.Ask),
		"price":     fmt.Sprintf("%.8f", tick.Price),
		"volume":    fmt.Sprintf("%.8f", tick.Volume),
		"timestamp": tick.Timestamp.Format(time.RFC3339),
	}

	// Use HSET to store all fields in Redis hash
	// This overwrites any existing tick data for the same symbol
	if err := r.client.HSet(ctx, key, fields).Err(); err != nil {
		return fmt.Errorf("failed to save tick to Redis: %w", err)
	}

	return nil
}

// Close closes the Redis client connection
func (r *RedisTickRepository) Close() error {
	if r.client != nil {
		return r.client.Close()
	}
	return nil
}
