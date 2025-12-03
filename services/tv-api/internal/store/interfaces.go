// Package store provides storage abstractions for market data
// Story 1.3 & 1.4: Redis and TimescaleDB integration
package store

import (
	"context"
	"time"
)

// TickData represents a single tick/quote event
type TickData struct {
	Timestamp time.Time
	Symbol    string
	Bid       float64
	Ask       float64
	Price     float64
	Volume    float64
	Exchange  string
	Metadata  map[string]interface{}
}

// CandleData represents OHLCV candlestick data
type CandleData struct {
	Timestamp time.Time
	Symbol    string
	Interval  string
	Open      float64
	High      float64
	Low       float64
	Close     float64
	Volume    float64
	Metadata  map[string]interface{}
}

// MetricData represents system monitoring metrics (NFR7)
type MetricData struct {
	Timestamp   time.Time
	Component   string
	MetricName  string
	MetricValue float64
	Unit        string
	Metadata    map[string]interface{}
}

// HotStore interface for real-time cache (Redis)
// NFR1: Provides <20ms query latency for latest prices
type HotStore interface {
	// SaveLatestTick saves the most recent tick to cache
	// Used for real-time trading bot queries
	SaveLatestTick(ctx context.Context, data TickData) error

	// GetLatestTick retrieves the most recent tick for a symbol
	// Target latency: <5ms
	GetLatestTick(ctx context.Context, symbol string) (*TickData, error)

	// SaveLatestCandle saves the most recent candle to cache
	SaveLatestCandle(ctx context.Context, data CandleData) error

	// GetLatestCandle retrieves the most recent candle
	GetLatestCandle(ctx context.Context, symbol string, interval string) (*CandleData, error)

	// Ping tests the connection
	Ping(ctx context.Context) error

	// Close closes the connection
	Close() error
}

// TimeSeriesStore interface for historical data (TimescaleDB)
// Story 1.4: Provides short-term storage with batch processing
type TimeSeriesStore interface {
	// SaveTick buffers a tick for batch insertion
	// Non-blocking, returns immediately
	SaveTick(ctx context.Context, data TickData) error

	// SaveCandle buffers a candle for batch insertion
	SaveCandle(ctx context.Context, data CandleData) error

	// SaveBatch inserts multiple records in a single transaction
	// Used internally by the batch processor
	SaveBatch(ctx context.Context, ticks []TickData, candles []CandleData) error

	// QueryTicks retrieves ticks within a time range
	// For short-term analysis and backtesting
	QueryTicks(ctx context.Context, symbol string, from, to time.Time, limit int) ([]TickData, error)

	// QueryCandles retrieves candles within a time range
	QueryCandles(ctx context.Context, symbol string, interval string, from, to time.Time, limit int) ([]CandleData, error)

	// Start begins the background batch processor
	// Flushes buffered data every interval or when batch size is reached
	Start(ctx context.Context) error

	// Ping tests the database connection
	Ping(ctx context.Context) error

	// Close flushes remaining data and closes connection
	Close() error

	// GetStats returns buffer statistics for monitoring
	GetStats() StoreStats
}

// MetricsStore interface for system monitoring (NFR7)
type MetricsStore interface {
	// RecordMetric records a system metric
	RecordMetric(ctx context.Context, metric MetricData) error

	// RecordConnectionStatus records client connection status (NFR7.1)
	RecordConnectionStatus(ctx context.Context, clientID, status, symbol string, err error) error

	// RecordThroughput records data processing throughput (NFR7.2)
	RecordThroughput(ctx context.Context, dataType string, symbol string, messagesProcessed, errorsCount int) error

	// Close closes the connection
	Close() error
}

// StoreStats contains buffer and performance statistics
type StoreStats struct {
	TickBufferSize   int
	CandleBufferSize int
	TicksWritten     int64
	CandlesWritten   int64
	ErrorsCount      int64
	LastFlushTime    time.Time
	AvgFlushDuration time.Duration
}

// Config holds configuration for storage initialization
type Config struct {
	// Redis configuration
	RedisURL      string
	RedisPassword string
	RedisDB       int

	// TimescaleDB configuration
	TimescaleURL string

	// Batch processing configuration
	BatchSize     int           // Number of records before flush
	FlushInterval time.Duration // Time interval between flushes

	// Retry configuration
	MaxRetries    int
	RetryInterval time.Duration
}

// DefaultConfig returns sensible defaults
func DefaultConfig() Config {
	return Config{
		RedisURL:      "localhost:6379",
		RedisPassword: "",
		RedisDB:       0,
		TimescaleURL:  "postgres://hftuser:password@localhost:5432/hft_lakehouse?sslmode=disable",
		BatchSize:     100,
		FlushInterval: 1 * time.Second,
		MaxRetries:    3,
		RetryInterval: 1 * time.Second,
	}
}
