// Package store - Redis implementation for hot path storage
// Story 1.3: Redis integration for <20ms latency queries (NFR1)
package store

import (
	"context"
	"encoding/json"
	"fmt"
	"log/slog"
	"time"

	"github.com/redis/go-redis/v9"
)

// RedisStore implements HotStore interface
type RedisStore struct {
	client *redis.Client
	logger *slog.Logger
	ttl    time.Duration
}

// NewRedisStore creates a new Redis hot storage client
func NewRedisStore(url string, password string, db int, logger *slog.Logger) (*RedisStore, error) {
	client := redis.NewClient(&redis.Options{
		Addr:         url,
		Password:     password,
		DB:           db,
		PoolSize:     10,
		MinIdleConns: 5,
		MaxRetries:   3,
		DialTimeout:  5 * time.Second,
		ReadTimeout:  3 * time.Second,
		WriteTimeout: 3 * time.Second,
	})

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := client.Ping(ctx).Err(); err != nil {
		return nil, fmt.Errorf("redis connection failed: %w", err)
	}

	logger.Info("redis connected",
		"addr", url,
		"db", db,
	)

	return &RedisStore{
		client: client,
		logger: logger,
		ttl:    24 * time.Hour, // Keep latest data for 24 hours
	}, nil
}

// SaveLatestTick saves the most recent tick to Redis cache
// Target: <5ms latency
func (r *RedisStore) SaveLatestTick(ctx context.Context, data TickData) error {
	key := fmt.Sprintf("latest_tick:%s", data.Symbol)

	start := time.Now()

	// Use pipeline for atomic multi-command execution
	pipe := r.client.Pipeline()

	// Store as Hash for efficient field access
	pipe.HSet(ctx, key, map[string]interface{}{
		"timestamp": data.Timestamp.Unix(),
		"symbol":    data.Symbol,
		"bid":       data.Bid,
		"ask":       data.Ask,
		"price":     data.Price,
		"volume":    data.Volume,
		"exchange":  data.Exchange,
	})

	// Store metadata as JSON if present
	if len(data.Metadata) > 0 {
		metadataJSON, _ := json.Marshal(data.Metadata)
		pipe.HSet(ctx, key, "metadata", metadataJSON)
	}

	// Set TTL to prevent memory overflow
	pipe.Expire(ctx, key, r.ttl)

	// Execute pipeline
	_, err := pipe.Exec(ctx)

	duration := time.Since(start)

	if err != nil {
		r.logger.Error("failed to save tick to redis",
			"symbol", data.Symbol,
			"error", err,
			"duration_ms", duration.Milliseconds(),
		)
		return fmt.Errorf("redis save failed: %w", err)
	}

	r.logger.Debug("tick saved to redis",
		"symbol", data.Symbol,
		"price", data.Price,
		"duration_ms", duration.Milliseconds(),
	)

	return nil
}

// GetLatestTick retrieves the most recent tick from Redis
// Target: <5ms latency (NFR1 contribution)
func (r *RedisStore) GetLatestTick(ctx context.Context, symbol string) (*TickData, error) {
	key := fmt.Sprintf("latest_tick:%s", symbol)

	start := time.Now()

	result, err := r.client.HGetAll(ctx, key).Result()
	if err != nil {
		return nil, fmt.Errorf("redis get failed: %w", err)
	}

	if len(result) == 0 {
		return nil, fmt.Errorf("no data found for symbol: %s", symbol)
	}

	duration := time.Since(start)

	// Parse timestamp
	var timestamp int64
	fmt.Sscanf(result["timestamp"], "%d", &timestamp)

	// Parse float fields
	var bid, ask, price, volume float64
	fmt.Sscanf(result["bid"], "%f", &bid)
	fmt.Sscanf(result["ask"], "%f", &ask)
	fmt.Sscanf(result["price"], "%f", &price)
	fmt.Sscanf(result["volume"], "%f", &volume)

	// Parse metadata if present
	var metadata map[string]interface{}
	if metadataJSON, ok := result["metadata"]; ok {
		json.Unmarshal([]byte(metadataJSON), &metadata)
	}

	tick := &TickData{
		Timestamp: time.Unix(timestamp, 0),
		Symbol:    result["symbol"],
		Bid:       bid,
		Ask:       ask,
		Price:     price,
		Volume:    volume,
		Exchange:  result["exchange"],
		Metadata:  metadata,
	}

	r.logger.Debug("tick retrieved from redis",
		"symbol", symbol,
		"price", tick.Price,
		"duration_ms", duration.Milliseconds(),
	)

	return tick, nil
}

// SaveLatestCandle saves the most recent candle to Redis cache
func (r *RedisStore) SaveLatestCandle(ctx context.Context, data CandleData) error {
	key := fmt.Sprintf("latest_candle:%s:%s", data.Symbol, data.Interval)

	start := time.Now()

	pipe := r.client.Pipeline()

	pipe.HSet(ctx, key, map[string]interface{}{
		"timestamp": data.Timestamp.Unix(),
		"symbol":    data.Symbol,
		"interval":  data.Interval,
		"open":      data.Open,
		"high":      data.High,
		"low":       data.Low,
		"close":     data.Close,
		"volume":    data.Volume,
	})

	if len(data.Metadata) > 0 {
		metadataJSON, _ := json.Marshal(data.Metadata)
		pipe.HSet(ctx, key, "metadata", metadataJSON)
	}

	pipe.Expire(ctx, key, r.ttl)

	_, err := pipe.Exec(ctx)

	duration := time.Since(start)

	if err != nil {
		r.logger.Error("failed to save candle to redis",
			"symbol", data.Symbol,
			"interval", data.Interval,
			"error", err,
			"duration_ms", duration.Milliseconds(),
		)
		return fmt.Errorf("redis save failed: %w", err)
	}

	r.logger.Debug("candle saved to redis",
		"symbol", data.Symbol,
		"interval", data.Interval,
		"close", data.Close,
		"duration_ms", duration.Milliseconds(),
	)

	return nil
}

// GetLatestCandle retrieves the most recent candle from Redis
func (r *RedisStore) GetLatestCandle(ctx context.Context, symbol string, interval string) (*CandleData, error) {
	key := fmt.Sprintf("latest_candle:%s:%s", symbol, interval)

	start := time.Now()

	result, err := r.client.HGetAll(ctx, key).Result()
	if err != nil {
		return nil, fmt.Errorf("redis get failed: %w", err)
	}

	if len(result) == 0 {
		return nil, fmt.Errorf("no candle found for %s:%s", symbol, interval)
	}

	duration := time.Since(start)

	var timestamp int64
	var open, high, low, close, volume float64
	fmt.Sscanf(result["timestamp"], "%d", &timestamp)
	fmt.Sscanf(result["open"], "%f", &open)
	fmt.Sscanf(result["high"], "%f", &high)
	fmt.Sscanf(result["low"], "%f", &low)
	fmt.Sscanf(result["close"], "%f", &close)
	fmt.Sscanf(result["volume"], "%f", &volume)

	var metadata map[string]interface{}
	if metadataJSON, ok := result["metadata"]; ok {
		json.Unmarshal([]byte(metadataJSON), &metadata)
	}

	candle := &CandleData{
		Timestamp: time.Unix(timestamp, 0),
		Symbol:    result["symbol"],
		Interval:  result["interval"],
		Open:      open,
		High:      high,
		Low:       low,
		Close:     close,
		Volume:    volume,
		Metadata:  metadata,
	}

	r.logger.Debug("candle retrieved from redis",
		"symbol", symbol,
		"interval", interval,
		"close", candle.Close,
		"duration_ms", duration.Milliseconds(),
	)

	return candle, nil
}

// Ping tests the Redis connection
func (r *RedisStore) Ping(ctx context.Context) error {
	return r.client.Ping(ctx).Err()
}

// Close closes the Redis connection
func (r *RedisStore) Close() error {
	r.logger.Info("closing redis connection")
	return r.client.Close()
}
