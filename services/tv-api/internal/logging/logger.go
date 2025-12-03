package logging

import (
	"log/slog"
	"os"
)

// Config contains configuration for structured logging.
type Config struct {
	// Level is the minimum log level to output
	Level string

	// Format is the output format ("text" or "json")
	Format string

	// AddSource includes file:line information in logs
	AddSource bool
}

// DefaultConfig returns the default logging configuration.
func DefaultConfig() *Config {
	return &Config{
		Level:     "info",
		Format:    "text",
		AddSource: true,
	}
}

// Setup creates a configured slog.Logger instance.
// This function should be called once at application startup.
func Setup(cfg *Config) *slog.Logger {
	if cfg == nil {
		cfg = DefaultConfig()
	}

	// Parse log level
	var logLevel slog.Level
	switch cfg.Level {
	case "debug":
		logLevel = slog.LevelDebug
	case "info":
		logLevel = slog.LevelInfo
	case "warn":
		logLevel = slog.LevelWarn
	case "error":
		logLevel = slog.LevelError
	default:
		logLevel = slog.LevelInfo
	}

	// Configure handler options
	opts := &slog.HandlerOptions{
		Level:     logLevel,
		AddSource: cfg.AddSource,
	}

	// Create handler based on format
	var handler slog.Handler
	if cfg.Format == "json" {
		// JSON format for production/log aggregation
		handler = slog.NewJSONHandler(os.Stdout, opts)
	} else {
		// Text format for CLI development
		handler = slog.NewTextHandler(os.Stdout, opts)
	}

	return slog.New(handler)
}

// SetDefault sets the global default logger.
func SetDefault(logger *slog.Logger) {
	slog.SetDefault(logger)
}
