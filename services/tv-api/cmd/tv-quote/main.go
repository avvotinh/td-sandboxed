// Package main provides a TradingView multi-symbol quote monitoring CLI tool.
// It enables users to configure and monitor multiple trading symbols for real-time
// quote data through external YAML configuration.
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
	// Deduplicate quote subscriptions
	config.DeduplicateQuoteSubscriptions(cfg, logger)

	// Check if there are quote subscriptions
	if len(cfg.QuoteSubscriptions) == 0 {
		return ConfigError{fmt.Errorf("no quote subscriptions found in configuration")}
	}

	logger.Info("configuration loaded successfully",
		slog.Int("quote_subscriptions", len(cfg.QuoteSubscriptions)))

	// Display loaded configuration
	fmt.Printf("Loaded %d quote subscription(s):\n", len(cfg.QuoteSubscriptions))
	for i, sub := range cfg.QuoteSubscriptions {
		fmt.Printf("  %d. %s\n", i+1, sub.Symbol)
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

	// Create session manager for tracking quote session
	sessionManager := session.NewManagerWithContext(ctx, logger)

	// Create display manager for output formatting
	displayManager := display.NewManager()

	// Create quote session for all subscriptions
	logger.Info("creating quote session for all subscriptions",
		slog.Int("count", len(cfg.QuoteSubscriptions)))

	if err := createQuoteSession(ctx, client, sessionManager, displayManager, cfg.QuoteSubscriptions, logger); err != nil {
		logger.Error("failed to create quote session", slog.Any("error", err))
		return fmt.Errorf("failed to create quote session: %w", err)
	}

	logger.Info("quote session initialized",
		slog.Int("active_sessions", sessionManager.Count()))

	fmt.Printf("\nMonitoring %d symbol(s). Waiting for data...\n", len(cfg.QuoteSubscriptions))
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

// createQuoteSession creates a quote session for multiple symbols and sets up event handlers.
func createQuoteSession(
	ctx context.Context,
	client *tradingview.Client,
	sessionManager *session.Manager,
	displayManager *display.Manager,
	subscriptions []config.QuoteSubscription,
	logger *slog.Logger,
) error {
	// Create internal quote session with default fields
	quoteSession := session.NewQuoteSession(client, nil)

	// CRITICAL: Register session with CLIENT to receive packets
	if err := client.RegisterSession(quoteSession); err != nil {
		return fmt.Errorf("failed to register with client: %w", err)
	}

	// Register with session manager for tracking
	if err := sessionManager.Register(quoteSession); err != nil {
		// Cleanup: unregister from client if sessionManager registration fails
		client.UnregisterSession(quoteSession.ID())
		return fmt.Errorf("failed to register quote session: %w", err)
	}

	logger.Debug("quote session registered",
		slog.String("session_id", quoteSession.ID()))

	// Subscribe to all symbols
	for _, sub := range subscriptions {
		market, err := quoteSession.AddSymbol(sub.Symbol)
		if err != nil {
			logger.Error("failed to add symbol",
				slog.String("symbol", sub.Symbol),
				slog.Any("error", err))
			continue
		}

		logger.Debug("symbol added",
			slog.String("session_id", quoteSession.ID()),
			slog.String("symbol", sub.Symbol))

		// Set up data handler for this symbol
		symbol := sub.Symbol // Capture for closure
		market.OnData(func(data map[string]interface{}) {
			// Log data received event
			logger.Debug("quote data received",
				slog.String("session_id", quoteSession.ID()),
				slog.String("symbol", symbol),
				slog.String("event_type", "data_received"))

			// Display update using DisplayManager
			displayManager.UpdateQuoteSection(symbol, data)
		})

		// Log subscription event
		logger.Info("symbol subscribed",
			slog.String("session_id", quoteSession.ID()),
			slog.String("symbol", symbol),
			slog.String("event_type", "subscribed"))
	}

	return nil
}
