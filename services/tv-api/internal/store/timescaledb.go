// Package store - TimescaleDB implementation for time-series storage
// Story 1.4: TimescaleDB integration with batch processing
package store

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log/slog"
	"sync"
	"time"

	_ "github.com/lib/pq"
)

// TimescaleStore implements TimeSeriesStore interface
type TimescaleStore struct {
	db            *sql.DB
	logger        *slog.Logger
	config        Config
	tickBuffer    chan TickData
	candleBuffer  chan CandleData
	stats         StoreStats
	statsMutex    sync.RWMutex
	stopChan      chan struct{}
	doneChan      chan struct{}
}

// NewTimescaleStore creates a new TimescaleDB time-series storage client
func NewTimescaleStore(connStr string, config Config, logger *slog.Logger) (*TimescaleStore, error) {
	db, err := sql.Open("postgres", connStr)
	if err != nil {
		return nil, fmt.Errorf("failed to open database: %w", err)
	}

	// Configure connection pool for high throughput
	db.SetMaxOpenConns(25)
	db.SetMaxIdleConns(5)
	db.SetConnMaxLifetime(5 * time.Minute)
	db.SetConnMaxIdleTime(1 * time.Minute)

	// Test connection
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	if err := db.PingContext(ctx); err != nil {
		return nil, fmt.Errorf("database ping failed: %w", err)
	}

	logger.Info("timescaledb connected",
		"batch_size", config.BatchSize,
		"flush_interval", config.FlushInterval,
	)

	store := &TimescaleStore{
		db:           db,
		logger:       logger,
		config:       config,
		tickBuffer:   make(chan TickData, 1000),
		candleBuffer: make(chan CandleData, 1000),
		stats: StoreStats{
			LastFlushTime: time.Now(),
		},
		stopChan: make(chan struct{}),
		doneChan: make(chan struct{}),
	}

	return store, nil
}

// Start begins the background batch processor
// Non-blocking, processes data asynchronously
func (t *TimescaleStore) Start(ctx context.Context) error {
	go t.batchProcessor(ctx)
	t.logger.Info("timescale batch processor started")
	return nil
}

// SaveTick buffers a tick for batch insertion
// Non-blocking, returns immediately (NFR1 - doesn't slow down hot path)
func (t *TimescaleStore) SaveTick(ctx context.Context, data TickData) error {
	select {
	case t.tickBuffer <- data:
		t.statsMutex.Lock()
		t.stats.TickBufferSize = len(t.tickBuffer)
		t.statsMutex.Unlock()
		return nil
	case <-ctx.Done():
		return ctx.Err()
	default:
		// Buffer full - log warning but don't block
		t.logger.Warn("tick buffer full, dropping tick",
			"symbol", data.Symbol,
			"buffer_size", len(t.tickBuffer),
		)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return fmt.Errorf("buffer full")
	}
}

// SaveCandle buffers a candle for batch insertion
func (t *TimescaleStore) SaveCandle(ctx context.Context, data CandleData) error {
	select {
	case t.candleBuffer <- data:
		t.statsMutex.Lock()
		t.stats.CandleBufferSize = len(t.candleBuffer)
		t.statsMutex.Unlock()
		return nil
	case <-ctx.Done():
		return ctx.Err()
	default:
		t.logger.Warn("candle buffer full, dropping candle",
			"symbol", data.Symbol,
			"buffer_size", len(t.candleBuffer),
		)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return fmt.Errorf("buffer full")
	}
}

// batchProcessor runs in background, flushes batches periodically
func (t *TimescaleStore) batchProcessor(ctx context.Context) {
	ticker := time.NewTicker(t.config.FlushInterval)
	defer ticker.Stop()
	defer close(t.doneChan)

	tickBatch := make([]TickData, 0, t.config.BatchSize)
	candleBatch := make([]CandleData, 0, t.config.BatchSize)

	for {
		select {
		case tick := <-t.tickBuffer:
			tickBatch = append(tickBatch, tick)
			if len(tickBatch) >= t.config.BatchSize {
				t.flushTicks(ctx, tickBatch)
				tickBatch = tickBatch[:0]
			}

		case candle := <-t.candleBuffer:
			candleBatch = append(candleBatch, candle)
			if len(candleBatch) >= t.config.BatchSize {
				t.flushCandles(ctx, candleBatch)
				candleBatch = candleBatch[:0]
			}

		case <-ticker.C:
			// Flush on timer
			if len(tickBatch) > 0 {
				t.flushTicks(ctx, tickBatch)
				tickBatch = tickBatch[:0]
			}
			if len(candleBatch) > 0 {
				t.flushCandles(ctx, candleBatch)
				candleBatch = candleBatch[:0]
			}

		case <-t.stopChan:
			// Flush remaining data before shutdown
			t.logger.Info("flushing remaining data before shutdown",
				"ticks", len(tickBatch),
				"candles", len(candleBatch),
			)
			if len(tickBatch) > 0 {
				t.flushTicks(context.Background(), tickBatch)
			}
			if len(candleBatch) > 0 {
				t.flushCandles(context.Background(), candleBatch)
			}
			return

		case <-ctx.Done():
			return
		}
	}
}

// flushTicks performs batch insert of tick data
func (t *TimescaleStore) flushTicks(ctx context.Context, batch []TickData) {
	if len(batch) == 0 {
		return
	}

	start := time.Now()

	txn, err := t.db.BeginTx(ctx, nil)
	if err != nil {
		t.logger.Error("failed to begin transaction", "error", err)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return
	}
	defer txn.Rollback()

	stmt, err := txn.PrepareContext(ctx, `
		INSERT INTO ticks (time, symbol, bid, ask, price, volume, exchange, metadata)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
		ON CONFLICT DO NOTHING
	`)
	if err != nil {
		t.logger.Error("failed to prepare statement", "error", err)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return
	}
	defer stmt.Close()

	insertedCount := 0
	for _, tick := range batch {
		var metadataJSON interface{}
		if len(tick.Metadata) > 0 {
			jsonBytes, _ := json.Marshal(tick.Metadata)
			metadataJSON = jsonBytes
		} else {
			metadataJSON = nil
		}

		_, err := stmt.ExecContext(ctx,
			tick.Timestamp,
			tick.Symbol,
			tick.Bid,
			tick.Ask,
			tick.Price,
			tick.Volume,
			tick.Exchange,
			metadataJSON,
		)
		if err != nil {
			t.logger.Error("failed to insert tick",
				"error", err,
				"symbol", tick.Symbol,
			)
			continue
		}
		insertedCount++
	}

	if err := txn.Commit(); err != nil {
		t.logger.Error("failed to commit transaction", "error", err)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return
	}

	duration := time.Since(start)

	t.statsMutex.Lock()
	t.stats.TicksWritten += int64(insertedCount)
	t.stats.LastFlushTime = time.Now()
	t.stats.AvgFlushDuration = (t.stats.AvgFlushDuration + duration) / 2
	t.statsMutex.Unlock()

	t.logger.Info("ticks flushed to timescaledb",
		"count", insertedCount,
		"duration_ms", duration.Milliseconds(),
	)
}

// flushCandles performs batch insert of candle data
func (t *TimescaleStore) flushCandles(ctx context.Context, batch []CandleData) {
	if len(batch) == 0 {
		return
	}

	start := time.Now()

	txn, err := t.db.BeginTx(ctx, nil)
	if err != nil {
		t.logger.Error("failed to begin transaction", "error", err)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return
	}
	defer txn.Rollback()

	stmt, err := txn.PrepareContext(ctx, `
		INSERT INTO candles (time, symbol, interval, open, high, low, close, volume, metadata)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
		ON CONFLICT (symbol, interval, time) DO NOTHING
	`)
	if err != nil {
		t.logger.Error("failed to prepare statement", "error", err)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return
	}
	defer stmt.Close()

	insertedCount := 0
	for _, candle := range batch {
		var metadataJSON interface{}
		if len(candle.Metadata) > 0 {
			jsonBytes, _ := json.Marshal(candle.Metadata)
			metadataJSON = jsonBytes
		} else {
			metadataJSON = nil
		}

		_, err := stmt.ExecContext(ctx,
			candle.Timestamp,
			candle.Symbol,
			candle.Interval,
			candle.Open,
			candle.High,
			candle.Low,
			candle.Close,
			candle.Volume,
			metadataJSON,
		)
		if err != nil {
			t.logger.Error("failed to insert candle",
				"error", err,
				"symbol", candle.Symbol,
				"interval", candle.Interval,
			)
			continue
		}
		insertedCount++
	}

	if err := txn.Commit(); err != nil {
		t.logger.Error("failed to commit transaction", "error", err)
		t.statsMutex.Lock()
		t.stats.ErrorsCount++
		t.statsMutex.Unlock()
		return
	}

	duration := time.Since(start)

	t.statsMutex.Lock()
	t.stats.CandlesWritten += int64(insertedCount)
	t.stats.LastFlushTime = time.Now()
	t.stats.AvgFlushDuration = (t.stats.AvgFlushDuration + duration) / 2
	t.statsMutex.Unlock()

	t.logger.Info("candles flushed to timescaledb",
		"count", insertedCount,
		"duration_ms", duration.Milliseconds(),
	)
}

// SaveBatch manually inserts a batch (used for bulk imports)
func (t *TimescaleStore) SaveBatch(ctx context.Context, ticks []TickData, candles []CandleData) error {
	if len(ticks) > 0 {
		t.flushTicks(ctx, ticks)
	}
	if len(candles) > 0 {
		t.flushCandles(ctx, candles)
	}
	return nil
}

// QueryTicks retrieves ticks within a time range
func (t *TimescaleStore) QueryTicks(ctx context.Context, symbol string, from, to time.Time, limit int) ([]TickData, error) {
	query := `
		SELECT time, symbol, bid, ask, price, volume, exchange, metadata
		FROM ticks
		WHERE symbol = $1 AND time >= $2 AND time <= $3
		ORDER BY time DESC
		LIMIT $4
	`

	rows, err := t.db.QueryContext(ctx, query, symbol, from, to, limit)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var ticks []TickData
	for rows.Next() {
		var tick TickData
		var metadataJSON []byte

		err := rows.Scan(
			&tick.Timestamp,
			&tick.Symbol,
			&tick.Bid,
			&tick.Ask,
			&tick.Price,
			&tick.Volume,
			&tick.Exchange,
			&metadataJSON,
		)
		if err != nil {
			continue
		}

		if len(metadataJSON) > 0 {
			json.Unmarshal(metadataJSON, &tick.Metadata)
		}

		ticks = append(ticks, tick)
	}

	return ticks, nil
}

// QueryCandles retrieves candles within a time range
func (t *TimescaleStore) QueryCandles(ctx context.Context, symbol string, interval string, from, to time.Time, limit int) ([]CandleData, error) {
	query := `
		SELECT time, symbol, interval, open, high, low, close, volume, metadata
		FROM candles
		WHERE symbol = $1 AND interval = $2 AND time >= $3 AND time <= $4
		ORDER BY time DESC
		LIMIT $5
	`

	rows, err := t.db.QueryContext(ctx, query, symbol, interval, from, to, limit)
	if err != nil {
		return nil, fmt.Errorf("query failed: %w", err)
	}
	defer rows.Close()

	var candles []CandleData
	for rows.Next() {
		var candle CandleData
		var metadataJSON []byte

		err := rows.Scan(
			&candle.Timestamp,
			&candle.Symbol,
			&candle.Interval,
			&candle.Open,
			&candle.High,
			&candle.Low,
			&candle.Close,
			&candle.Volume,
			&metadataJSON,
		)
		if err != nil {
			continue
		}

		if len(metadataJSON) > 0 {
			json.Unmarshal(metadataJSON, &candle.Metadata)
		}

		candles = append(candles, candle)
	}

	return candles, nil
}

// GetStats returns current buffer and performance statistics
func (t *TimescaleStore) GetStats() StoreStats {
	t.statsMutex.RLock()
	defer t.statsMutex.RUnlock()
	return t.stats
}

// Ping tests the database connection
func (t *TimescaleStore) Ping(ctx context.Context) error {
	return t.db.PingContext(ctx)
}

// Close gracefully shuts down, flushing remaining data
func (t *TimescaleStore) Close() error {
	t.logger.Info("closing timescaledb connection")
	close(t.stopChan)
	<-t.doneChan // Wait for batch processor to finish
	return t.db.Close()
}
