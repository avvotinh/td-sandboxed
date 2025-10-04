package websocket

import (
	"context"
	"fmt"
	"log/slog"
	"time"

	"github.com/gorilla/websocket"
	"github.com/hft-lakehouse/ingestion-client/internal/config"
	"github.com/hft-lakehouse/ingestion-client/internal/logger"
	"github.com/hft-lakehouse/ingestion-client/internal/parser"
	"github.com/hft-lakehouse/ingestion-client/internal/repository"
)

// WSClient represents a WebSocket client
type WSClient struct {
	config     *config.Config
	logger     *slog.Logger
	conn       *websocket.Conn
	done       chan struct{}
	doneClosed bool
	parser     *parser.MessageParser
	repo       repository.TickRepository
}

// New creates a new WebSocket client
func New(cfg *config.Config, log *slog.Logger, repo repository.TickRepository) *WSClient {
	return &WSClient{
		config: cfg,
		logger: log,
		done:   make(chan struct{}),
		parser: parser.NewMessageParser(),
		repo:   repo,
	}
}

// Connect establishes a WebSocket connection to TradingView
// Following Coding Standard Rule #5: Use context.Context for I/O operations
func (c *WSClient) Connect(ctx context.Context) error {
	c.logger.Info("connecting to websocket",
		slog.String("event", logger.EventConnectionStarted),
		slog.String("url", c.config.TradingViewWSURL),
	)

	// Create websocket dialer with context
	dialer := websocket.DefaultDialer

	conn, _, err := dialer.DialContext(ctx, c.config.TradingViewWSURL, nil)
	if err != nil {
		c.logger.Error("connection failed",
			slog.String("event", logger.EventConnectionFailed),
			slog.String("error", err.Error()),
		)
		return fmt.Errorf("failed to connect to websocket: %w", err)
	}

	c.conn = conn

	c.logger.Info("connection established",
		slog.String("event", logger.EventConnectionSuccess),
	)

	// Authenticate after connection
	if err := c.authenticate(ctx); err != nil {
		c.conn.Close()
		c.conn = nil
		return fmt.Errorf("authentication failed: %w", err)
	}

	return nil
}

// authenticate sends authentication credentials to TradingView
func (c *WSClient) authenticate(ctx context.Context) error {
	// TradingView WebSocket authentication message format
	// Note: This is a simplified implementation - actual TradingView protocol may differ
	authMsg := map[string]interface{}{
		"m": "auth",
		"p": []string{c.config.TradingViewUsername, c.config.TradingViewPassword},
	}

	c.logger.Info("sending authentication",
		slog.String("username", c.config.TradingViewUsername),
	)

	if err := c.conn.WriteJSON(authMsg); err != nil {
		c.logger.Error("authentication write failed",
			slog.String("error", err.Error()),
		)
		return fmt.Errorf("failed to send auth message: %w", err)
	}

	c.logger.Info("authentication sent successfully")

	return nil
}

// Reconnect attempts to reconnect with exponential backoff
// Following Error Handling Strategy: Exponential backoff with 1s initial, 60s max, 2x multiplier
func (c *WSClient) Reconnect(ctx context.Context) error {
	const (
		initialDelay = 1 * time.Second
		maxDelay     = 60 * time.Second
		multiplier   = 2
	)

	delay := initialDelay
	attempt := 1

	for {
		select {
		case <-ctx.Done():
			c.logger.Info("reconnection cancelled",
				slog.String("reason", "context cancelled"),
			)
			return ctx.Err()
		default:
		}

		c.logger.Info("attempting reconnection",
			slog.String("event", logger.EventReconnecting),
			slog.Int("attempt", attempt),
			slog.Duration("delay", delay),
		)

		// Wait before attempting reconnection
		time.Sleep(delay)

		// Attempt connection
		if err := c.Connect(ctx); err != nil {
			c.logger.Warn("reconnection attempt failed",
				slog.Int("attempt", attempt),
				slog.String("error", err.Error()),
			)

			// Calculate next delay with exponential backoff
			delay = delay * multiplier
			if delay > maxDelay {
				delay = maxDelay
			}

			attempt++
			continue
		}

		// Connection successful
		c.logger.Info("reconnection successful",
			slog.Int("attempts", attempt),
		)
		return nil
	}
}

// Close closes the WebSocket connection
func (c *WSClient) Close() error {
	// Close done channel only once
	if !c.doneClosed {
		close(c.done)
		c.doneClosed = true
	}

	if c.conn != nil {
		c.logger.Info("closing websocket connection")
		err := c.conn.Close()
		c.conn = nil
		return err
	}

	return nil
}

// IsConnected returns true if the client is connected
func (c *WSClient) IsConnected() bool {
	return c.conn != nil
}

// ReadMessages reads and processes messages from WebSocket
// Following Coding Standard Rule #5: Uses context.Context for I/O operations
// Following Coding Standard Rule #3: Structured logging only
func (c *WSClient) ReadMessages(ctx context.Context) error {
	if c.conn == nil {
		return fmt.Errorf("not connected")
	}

	c.logger.Info("starting message processing loop")

	for {
		select {
		case <-ctx.Done():
			c.logger.Info("message processing stopped",
				slog.String("reason", "context cancelled"),
			)
			return ctx.Err()
		case <-c.done:
			c.logger.Info("message processing stopped",
				slog.String("reason", "connection closed"),
			)
			return nil
		default:
		}

		// Read message from WebSocket
		_, message, err := c.conn.ReadMessage()
		if err != nil {
			c.logger.Error("failed to read message",
				slog.String("event", logger.EventConnectionLost),
				slog.String("error", err.Error()),
			)
			return fmt.Errorf("read message failed: %w", err)
		}

		c.logger.Debug("message received",
			slog.String("event", "message_received"),
			slog.Int("size", len(message)),
		)

		// Parse message
		tick, err := c.parser.ParseTickMessage(message)
		if err != nil {
			c.logger.Warn("failed to parse message",
				slog.String("event", "parse_failed"),
				slog.String("error", err.Error()),
				slog.String("message", string(message)),
			)
			continue // Skip invalid messages
		}

		c.logger.Info("message parsed successfully",
			slog.String("event", "parse_success"),
			slog.String("symbol", tick.Symbol),
			slog.Float64("bid", tick.Bid),
			slog.Float64("ask", tick.Ask),
		)

		// Save tick to Redis
		if err := c.repo.SaveLatestTick(ctx, tick); err != nil {
			c.logger.Error("failed to save tick to redis",
				slog.String("event", "redis_save_failed"),
				slog.String("symbol", tick.Symbol),
				slog.String("error", err.Error()),
			)
			continue // Log error but continue processing
		}

		c.logger.Info("tick saved to redis",
			slog.String("event", "redis_save_success"),
			slog.String("symbol", tick.Symbol),
			slog.String("key", fmt.Sprintf("latest_tick:%s", tick.Symbol)),
		)
	}
}
