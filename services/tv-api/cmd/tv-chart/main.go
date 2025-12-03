// Package main provides a TradingView multi-symbol multi-timeframe monitoring CLI tool.
// It enables users to configure and monitor multiple trading symbols across different
// timeframes simultaneously through external YAML configuration.
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
	"github.com/avvotinh/tv-api/pkg/tradingview"
)

const (
	exitSuccess     = 0
	exitConfigError = 1
	exitConnError   = 2
	configPath      = "config.yaml"
)

func main() {
	// Load configuration first
	cfg, err := config.LoadConfig(configPath)
	if err != nil {
		fmt.Fprintf(os.Stderr, "Failed to load configuration: %v\n", err)
		os.Exit(exitConfigError)
	}

	// Validate configuration
	if err := config.ValidateConfig(cfg); err != nil {
		fmt.Fprintf(os.Stderr, "Configuration validation failed: %v\n", err)
		os.Exit(exitConfigError)
	}

	// Setup logging from config
	logger := logging.Setup(&logging.Config{
		Level:     cfg.Logging.Level,
		Format:    cfg.Logging.Format,
		AddSource: true,
	})
	logging.SetDefault(logger)

	if err := run(cfg, logger); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)

		// Determine exit code based on error type
		if _, ok := err.(ConfigError); ok {
			os.Exit(exitConfigError)
		}
		os.Exit(exitConnError)
	}
	os.Exit(exitSuccess)
}

// ConfigError represents a configuration-related error
type ConfigError struct {
	error
}

func run(cfg *config.Configuration, logger *slog.Logger) error {
	// Deduplicate subscriptions
	config.DeduplicateSubscriptions(cfg, logger)

	logger.Info("configuration loaded successfully",
		slog.Int("subscriptions", len(cfg.Subscriptions)))

	// Display loaded configuration
	fmt.Printf("Loaded %d subscription(s):\n", len(cfg.Subscriptions))
	for i, sub := range cfg.Subscriptions {
		fmt.Printf("  %d. %s [%s]\n", i+1, sub.Symbol, sub.Timeframe)
	}
	fmt.Println()

	// Create context with cancellation
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

	// Create client
	client, err := tradingview.NewClient(&tradingview.ClientConfig{
		Debug:  false, // Set to true for debugging packet flow
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

	// Wait for authentication
	time.Sleep(2 * time.Second)

	// Create session manager for tracking all chart sessions
	sessionManager := session.NewManagerWithContext(ctx, logger)

	// Create display manager for output formatting
	displayManager := display.NewManager()

	// Create chart sessions for all subscriptions
	logger.Info("creating chart sessions for all subscriptions",
		slog.Int("count", len(cfg.Subscriptions)))

	for _, sub := range cfg.Subscriptions {
		if err := createChartSession(ctx, client, sessionManager, displayManager, sub, logger); err != nil {
			logger.Error("failed to create chart session",
				slog.String("symbol", sub.Symbol),
				slog.String("timeframe", sub.Timeframe),
				slog.Any("error", err))
			// Continue with other sessions instead of failing completely
			continue
		}

		logger.Info("chart session created",
			slog.String("symbol", sub.Symbol),
			slog.String("timeframe", sub.Timeframe),
			slog.String("event_type", "created"))
	}

	logger.Info("all chart sessions initialized",
		slog.Int("active_sessions", sessionManager.Count()))

	fmt.Printf("\nMonitoring %d subscription(s). Waiting for data...\n", sessionManager.Count())
	fmt.Println("Press Ctrl+C to exit")

	// Wait for context cancellation (Ctrl+C)
	<-ctx.Done()

	// Graceful shutdown
	fmt.Println("\nShutting down...")
	logger.Info("initiating graceful shutdown")

	// Use SessionManager.Shutdown with timeout
	shutdownTimeout := 10 * time.Second
	if err := sessionManager.Shutdown(shutdownTimeout); err != nil {
		logger.Error("error during shutdown", slog.Any("error", err))
		return fmt.Errorf("shutdown failed: %w", err)
	}

	logger.Info("shutdown complete")
	return nil
}

// createChartSession creates a chart session for a single subscription and sets up event handlers.
func createChartSession(
	ctx context.Context,
	client *tradingview.Client,
	sessionManager *session.Manager,
	displayManager *display.Manager,
	sub config.Subscription,
	logger *slog.Logger,
) error {
	// Create internal chart session
	chartSession := session.NewChartSession(client)

	// Set context and logger for reconnection support
	chartSession.SetContext(ctx, logger)

	// Store subscription information for reconnection
	chartSession.SetSubscription(sub.Symbol, sub.Timeframe)

	// CRITICAL: Register session with CLIENT to receive packets
	if err := client.RegisterSession(chartSession); err != nil {
		return fmt.Errorf("failed to register with client: %w", err)
	}

	// Register with session manager for tracking
	if err := sessionManager.Register(chartSession); err != nil {
		// Cleanup: unregister from client if sessionManager registration fails
		client.UnregisterSession(chartSession.ID())
		return fmt.Errorf("failed to register chart session: %w", err)
	}

	logger.Debug("chart session registered",
		slog.String("session_id", chartSession.ID()),
		slog.String("symbol", sub.Symbol),
		slog.String("timeframe", sub.Timeframe))

	// Resolve symbol
	if err := chartSession.ResolveSymbol(sub.Symbol, "splits", "", ""); err != nil {
		sessionManager.Unregister(chartSession.ID())
		return fmt.Errorf("failed to resolve symbol: %w", err)
	}

	logger.Debug("symbol resolved",
		slog.String("session_id", chartSession.ID()),
		slog.String("symbol", sub.Symbol))

	// Create series with specified timeframe
	if err := chartSession.CreateSeries(sub.Timeframe, 300); err != nil {
		sessionManager.Unregister(chartSession.ID())
		return fmt.Errorf("failed to create series: %w", err)
	}

	logger.Debug("series created",
		slog.String("session_id", chartSession.ID()),
		slog.String("timeframe", sub.Timeframe))

	// Set up update handler to display data using DisplayManager
	chartSession.On("update", func(args ...interface{}) {
		if len(args) > 0 {
			if periods, ok := args[0].([]*session.Period); ok && len(periods) > 0 {
				// Select the candle to display
				var candleToDisplay *session.Period

				if len(periods) > 1 {
					latest := periods[0]
					// Check if this is a newly opened candle with no price movement yet
					isNewCandle := (latest.Open == latest.High &&
						latest.Open == latest.Low &&
						latest.Open == latest.Close) ||
						latest.Volume < 2

					if isNewCandle {
						// Display the confirmed closed candle
						candleToDisplay = periods[1]
					} else {
						// Display the actively updating candle
						candleToDisplay = latest
					}
				} else {
					// Only one period, display it
					candleToDisplay = periods[0]
				}

				// Log data received event
				logger.Debug("data received",
					slog.String("session_id", chartSession.ID()),
					slog.String("symbol", sub.Symbol),
					slog.String("timeframe", sub.Timeframe),
					slog.String("event_type", "data_received"),
					slog.Int64("timestamp", candleToDisplay.Time),
					slog.Float64("close", candleToDisplay.Close))

				// Display update using DisplayManager
				displayManager.UpdateSection(sub.Symbol, sub.Timeframe, candleToDisplay)
			}
		}
	})

	// Set up error handler
	chartSession.On("error", func(args ...interface{}) {
		if len(args) > 0 {
			if err, ok := args[0].(error); ok {
				logger.Error("chart session error",
					slog.String("session_id", chartSession.ID()),
					slog.String("symbol", sub.Symbol),
					slog.String("timeframe", sub.Timeframe),
					slog.String("event_type", "error"),
					slog.Any("error", err))
			}
		}
	})

	// Log connection event
	logger.Info("chart session connected",
		slog.String("session_id", chartSession.ID()),
		slog.String("symbol", sub.Symbol),
		slog.String("timeframe", sub.Timeframe),
		slog.String("event_type", "connected"))

	return nil
}
