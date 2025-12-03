// Package main - tv-chart with storage integration
// Story 1.3 & 1.4: Integrated Redis + TimescaleDB storage
package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"
	"time"

	"github.com/avvotinh/tv-api/internal/config"
	"github.com/avvotinh/tv-api/internal/display"
	"github.com/avvotinh/tv-api/internal/logging"
	"github.com/avvotinh/tv-api/internal/session"
	"github.com/avvotinh/tv-api/internal/store"
	"github.com/avvotinh/tv-api/pkg/tradingview"
)

// Storage-enabled version of tv-chart
// To use this version, rename to main.go or build with: go build -o tv-chart-storage

func mainWithStorage() {
	// Load configuration
	cfg, err := config.LoadConfig("config.yaml")
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to load configuration: %v\n", err)
		os.Exit(1)
	}

	// Setup logging
	logger := logging.Setup(&logging.Config{
		Level:     cfg.Logging.Level,
		Format:    cfg.Logging.Format,
		AddSource: true,
	})
	logging.SetDefault(logger)

	if err := runWithStorage(cfg, logger); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(1)
	}
}

func runWithStorage(cfg *config.Configuration, logger *slog.Logger) error {
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle interrupt signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		fmt.Println("\nReceived interrupt signal, shutting down...")
		logger.Info("shutdown signal received")
		cancel()
	}()

	// Initialize storage layer
	logger.Info("initializing storage layer")
	
	// Redis for hot path
	redisURL := getEnvOrDefault("REDIS_URL", "localhost:6379")
	redisStore, err := store.NewRedisStore(redisURL, "", 0, logger)
	if err != nil {
		return fmt.Errorf("failed to initialize redis: %w", err)
	}
	defer redisStore.Close()
	logger.Info("redis store initialized", "url", redisURL)

	// TimescaleDB for historical data
	timescaleURL := getEnvOrDefault("TIMESCALE_URL", 
		"postgres://hftuser:password@localhost:5432/hft_lakehouse?sslmode=disable")
	
	storeConfig := store.Config{
		TimescaleURL:  timescaleURL,
		BatchSize:     100,
		FlushInterval: 1 * time.Second,
	}
	
	timescaleStore, err := store.NewTimescaleStore(timescaleURL, storeConfig, logger)
	if err != nil {
		return fmt.Errorf("failed to initialize timescaledb: %w", err)
	}
	defer timescaleStore.Close()
	
	// Start batch processor
	if err := timescaleStore.Start(ctx); err != nil {
		return fmt.Errorf("failed to start timescale batch processor: %w", err)
	}
	logger.Info("timescaledb store initialized", "batch_size", storeConfig.BatchSize)

	// Create TradingView client
	client, err := tradingview.NewClient(&tradingview.ClientConfig{
		Debug:  false,
		Logger: logger,
	})
	if err != nil {
		return fmt.Errorf("failed to create client: %w", err)
	}

	// Connect to TradingView
	logger.Info("connecting to TradingView")
	if err := client.Connect(ctx); err != nil {
		return fmt.Errorf("failed to connect: %w", err)
	}
	defer client.Close()

	time.Sleep(2 * time.Second)

	// Create session manager
	sessionManager := session.NewManagerWithContext(ctx, logger)
	displayManager := display.NewManager()

	// Create chart sessions with storage integration
	logger.Info("creating chart sessions with storage",
		slog.Int("count", len(cfg.Subscriptions)))

	for _, sub := range cfg.Subscriptions {
		if err := createChartSessionWithStorage(
			ctx, client, sessionManager, displayManager,
			redisStore, timescaleStore,
			sub, logger,
		); err != nil {
			logger.Error("failed to create chart session",
				slog.String("symbol", sub.Symbol),
				slog.Any("error", err))
			continue
		}
	}

	logger.Info("all chart sessions initialized",
		slog.Int("active_sessions", sessionManager.Count()))

	fmt.Printf("\nMonitoring %d subscription(s) with storage enabled\n", sessionManager.Count())
	fmt.Printf("Storage: Redis (hot) + TimescaleDB (historical)\n")
	fmt.Println("Press Ctrl+C to exit")

	// Monitor storage stats
	go monitorStorageStats(ctx, timescaleStore, logger)

	// Wait for shutdown
	<-ctx.Done()

	fmt.Println("\nShutting down...")
	logger.Info("initiating graceful shutdown")

	if err := sessionManager.Shutdown(10 * time.Second); err != nil {
		logger.Error("error during shutdown", slog.Any("error", err))
	}

	logger.Info("shutdown complete")
	return nil
}

// createChartSessionWithStorage creates a chart session with storage integration
func createChartSessionWithStorage(
	ctx context.Context,
	client *tradingview.Client,
	sessionManager *session.Manager,
	displayManager *display.Manager,
	redisStore store.HotStore,
	timescaleStore store.TimeSeriesStore,
	sub config.Subscription,
	logger *slog.Logger,
) error {
	chartSession := session.NewChartSession(client)
	chartSession.SetContext(ctx, logger)
	chartSession.SetSubscription(sub.Symbol, sub.Timeframe)

	if err := client.RegisterSession(chartSession); err != nil {
		return fmt.Errorf("failed to register with client: %w", err)
	}

	if err := sessionManager.Register(chartSession); err != nil {
		client.UnregisterSession(chartSession.ID())
		return fmt.Errorf("failed to register chart session: %w", err)
	}

	if err := chartSession.ResolveSymbol(sub.Symbol, "splits", "", ""); err != nil {
		sessionManager.Unregister(chartSession.ID())
		return fmt.Errorf("failed to resolve symbol: %w", err)
	}

	if err := chartSession.CreateSeries(sub.Timeframe, 300); err != nil {
		sessionManager.Unregister(chartSession.ID())
		return fmt.Errorf("failed to create series: %w", err)
	}

	// Set up update handler WITH STORAGE
	chartSession.On("update", func(args ...interface{}) {
		if len(args) > 0 {
			if periods, ok := args[0].([]*session.Period); ok && len(periods) > 0 {
				var candleToDisplay *session.Period

				if len(periods) > 1 {
					latest := periods[0]
					isNewCandle := (latest.Open == latest.High &&
						latest.Open == latest.Low &&
						latest.Open == latest.Close) ||
						latest.Volume < 2

					if isNewCandle {
						candleToDisplay = periods[1]
					} else {
						candleToDisplay = latest
					}
				} else {
					candleToDisplay = periods[0]
				}

				// === STORAGE INTEGRATION ===
				
				// 1. Save to Redis (hot path - critical, <5ms target)
				tickData := store.TickData{
					Timestamp: time.Unix(candleToDisplay.Time, 0),
					Symbol:    sub.Symbol,
					Price:     candleToDisplay.Close,
					Volume:    candleToDisplay.Volume,
					Bid:       candleToDisplay.Low,   // Approximation
					Ask:       candleToDisplay.High,  // Approximation
					Exchange:  "BINANCE",
				}

				if err := redisStore.SaveLatestTick(ctx, tickData); err != nil {
					logger.Error("failed to save tick to redis",
						"symbol", sub.Symbol,
						"error", err)
				}

				// 2. Save to TimescaleDB (buffered, non-blocking)
				candleData := store.CandleData{
					Timestamp: time.Unix(candleToDisplay.Time, 0),
					Symbol:    sub.Symbol,
					Interval:  sub.Timeframe,
					Open:      candleToDisplay.Open,
					High:      candleToDisplay.High,
					Low:       candleToDisplay.Low,
					Close:     candleToDisplay.Close,
					Volume:    candleToDisplay.Volume,
				}

				if err := timescaleStore.SaveCandle(ctx, candleData); err != nil {
					logger.Warn("failed to buffer candle to timescaledb",
						"symbol", sub.Symbol,
						"error", err)
				}

				// Display update
				displayManager.UpdateSection(sub.Symbol, sub.Timeframe, candleToDisplay)
			}
		}
	})

	chartSession.On("error", func(args ...interface{}) {
		if len(args) > 0 {
			if err, ok := args[0].(error); ok {
				logger.Error("chart session error",
					slog.String("symbol", sub.Symbol),
					slog.Any("error", err))
			}
		}
	})

	logger.Info("chart session with storage created",
		slog.String("symbol", sub.Symbol),
		slog.String("timeframe", sub.Timeframe))

	return nil
}

// monitorStorageStats periodically logs storage statistics
func monitorStorageStats(ctx context.Context, ts store.TimeSeriesStore, logger *slog.Logger) {
	ticker := time.NewTicker(30 * time.Second)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			stats := ts.GetStats()
			logger.Info("storage statistics",
				"ticks_written", stats.TicksWritten,
				"candles_written", stats.CandlesWritten,
				"tick_buffer_size", stats.TickBufferSize,
				"candle_buffer_size", stats.CandleBufferSize,
				"errors", stats.ErrorsCount,
				"avg_flush_ms", stats.AvgFlushDuration.Milliseconds(),
			)
		case <-ctx.Done():
			return
		}
	}
}

func getEnvOrDefault(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
