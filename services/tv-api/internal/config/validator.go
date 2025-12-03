package config

import (
	"fmt"
	"log/slog"
	"strings"

	"github.com/go-playground/validator/v10"
)

// validate is the global validator instance
var validate *validator.Validate

func init() {
	validate = validator.New()

	// Register custom validation for symbol format (EXCHANGE:TICKER)
	validate.RegisterValidation("symbol_format", validateSymbolFormat)
}

// validateSymbolFormat validates that a symbol follows the EXCHANGE:TICKER format.
func validateSymbolFormat(fl validator.FieldLevel) bool {
	symbol := fl.Field().String()

	// Must contain exactly one colon
	if !strings.Contains(symbol, ":") {
		return false
	}

	parts := strings.Split(symbol, ":")
	if len(parts) != 2 {
		return false
	}

	// Both exchange and ticker must be non-empty
	if parts[0] == "" || parts[1] == "" {
		return false
	}

	return true
}

// ValidateConfig validates the configuration structure and business rules.
// Returns an error if validation fails.
func ValidateConfig(config *Configuration) error {
	if config == nil {
		return fmt.Errorf("configuration cannot be nil")
	}

	// Check that at least one subscription type is present
	if len(config.Subscriptions) == 0 && len(config.QuoteSubscriptions) == 0 {
		return fmt.Errorf("configuration validation failed:\n  - at least one subscription (chart or quote) is required")
	}

	// Use validator to check struct constraints
	if err := validate.Struct(config); err != nil {
		return formatValidationErrors(err)
	}

	return nil
}

// formatValidationErrors converts validator errors into user-friendly messages.
func formatValidationErrors(err error) error {
	var messages []string

	if validationErrs, ok := err.(validator.ValidationErrors); ok {
		for _, e := range validationErrs {
			switch e.Tag() {
			case "required":
				messages = append(messages, fmt.Sprintf("field '%s' is required", strings.ToLower(e.Field())))
			case "min":
				if e.Field() == "Subscriptions" {
					messages = append(messages, fmt.Sprintf("at least %s subscription(s) required", e.Param()))
				} else {
					messages = append(messages, fmt.Sprintf("field '%s' must have at least %s items", strings.ToLower(e.Field()), e.Param()))
				}
			case "max":
				if e.Field() == "Subscriptions" {
					messages = append(messages, fmt.Sprintf("maximum %s chart subscriptions allowed (found %d)", e.Param(), len(e.Value().([]Subscription))))
				} else if e.Field() == "QuoteSubscriptions" {
					messages = append(messages, fmt.Sprintf("maximum %s quote subscriptions allowed (found %d)", e.Param(), len(e.Value().([]QuoteSubscription))))
				} else {
					messages = append(messages, fmt.Sprintf("field '%s' must have at most %s items", strings.ToLower(e.Field()), e.Param()))
				}
			case "oneof":
				messages = append(messages, fmt.Sprintf("field '%s' must be one of: %s", strings.ToLower(e.Field()), e.Param()))
			case "symbol_format":
				messages = append(messages, fmt.Sprintf("symbol '%v' must be in format 'EXCHANGE:TICKER' (e.g., 'NASDAQ:AAPL')", e.Value()))
			default:
				messages = append(messages, fmt.Sprintf("validation failed for field '%s': %s", strings.ToLower(e.Field()), e.Tag()))
			}
		}
	}

	if len(messages) == 0 {
		return fmt.Errorf("validation failed: %w", err)
	}

	return fmt.Errorf("configuration validation failed:\n  - %s", strings.Join(messages, "\n  - "))
}

// DeduplicateSubscriptions removes duplicate symbol-timeframe pairs from the configuration.
// Duplicates are identified by the combination of Symbol and Timeframe.
// A warning is logged for each duplicate removed.
func DeduplicateSubscriptions(config *Configuration, logger *slog.Logger) {
	if config == nil || len(config.Subscriptions) == 0 {
		return
	}

	if logger == nil {
		logger = slog.Default()
	}

	seen := make(map[string]bool)
	unique := make([]Subscription, 0, len(config.Subscriptions))

	for _, sub := range config.Subscriptions {
		// Create composite key from symbol and timeframe
		key := sub.Symbol + ":" + sub.Timeframe

		if !seen[key] {
			seen[key] = true
			unique = append(unique, sub)
		} else {
			// Log warning for duplicate
			logger.Warn("duplicate subscription removed",
				slog.String("symbol", sub.Symbol),
				slog.String("timeframe", sub.Timeframe))
		}
	}

	config.Subscriptions = unique
}

// DeduplicateQuoteSubscriptions removes duplicate symbols from the quote subscriptions.
// Duplicates are identified by the Symbol field.
// A warning is logged for each duplicate removed.
func DeduplicateQuoteSubscriptions(config *Configuration, logger *slog.Logger) {
	if config == nil || len(config.QuoteSubscriptions) == 0 {
		return
	}

	if logger == nil {
		logger = slog.Default()
	}

	seen := make(map[string]bool)
	unique := make([]QuoteSubscription, 0, len(config.QuoteSubscriptions))

	for _, sub := range config.QuoteSubscriptions {
		if !seen[sub.Symbol] {
			seen[sub.Symbol] = true
			unique = append(unique, sub)
		} else {
			// Log warning for duplicate
			logger.Warn("duplicate quote subscription removed",
				slog.String("symbol", sub.Symbol))
		}
	}

	config.QuoteSubscriptions = unique
}
