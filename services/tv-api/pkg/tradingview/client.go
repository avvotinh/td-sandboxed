package tradingview

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"sync"
	"time"

	"github.com/avvotinh/tv-api/internal/auth"
	"github.com/avvotinh/tv-api/internal/protocol"
	"github.com/avvotinh/tv-api/internal/session"
	"github.com/avvotinh/tv-api/internal/transport"
	"github.com/joho/godotenv"
)

const (
	// DefaultServer is the default TradingView WebSocket server.
	DefaultServer = "wss://data.tradingview.com/socket.io/websocket?type=chart"

	// DefaultLocation is the default location parameter.
	DefaultLocation = "https://www.tradingview.com"
)

// ClientConfig contains configuration for the TradingView client.
type ClientConfig struct {
	// Token is the authentication token (optional, will be fetched if not provided)
	Token string

	// Signature is the session signature (optional)
	Signature string

	// Server is the WebSocket server URL
	Server string

	// Location is the location parameter for the WebSocket connection
	Location string

	// Debug enables debug logging
	Debug bool

	// SessionID is the session ID cookie value
	SessionID string

	// SessionSign is the session signature cookie value
	SessionSign string

	// Logger is the structured logger instance (optional)
	Logger *slog.Logger
}

// SetDebug enables or disables debug logging
func (c *Client) SetDebug(debug bool) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.config.Debug = debug
}

// Client is the main TradingView WebSocket client.
type Client struct {
	config           ClientConfig
	conn             transport.WebSocketConn
	sessions         *session.Manager
	callbacks        map[string][]func(...interface{})
	sendQueue        []string
	isLogged         bool
	user             *auth.User
	logger           *slog.Logger
	mu               sync.RWMutex
	queueMu          sync.Mutex
	ctx              context.Context
	cancel           context.CancelFunc
	receiveDone      chan struct{}
	sendDone         chan struct{}
	reconnectCount   int
	maxReconnects    int
	reconnectDelay   time.Duration
	autoReconnect    bool
	rateLimitBackoff time.Duration
	lastSendTime     time.Time
}

// NewClient creates a new TradingView client with the provided configuration.
// It automatically loads credentials from environment variables if not provided in the config.
// The client must be connected using Connect() before it can be used.
//
// Environment variables:
//   - SESSION_ID: TradingView session ID cookie
//   - SESSION_SIGN: TradingView session signature cookie
//
// These can be obtained from browser cookies after logging into tradingview.com.
func NewClient(config *ClientConfig) (*Client, error) {
	if config == nil {
		config = &ClientConfig{}
	}
	// Set defaults
	if config.Server == "" {
		config.Server = DefaultServer
	}
	if config.Location == "" {
		config.Location = DefaultLocation
	}

	// Load credentials from environment if not provided
	if config.SessionID == "" || config.SessionSign == "" {
		sessionID, sessionSign, err := loadCredsFromEnv()
		if err != nil {
			return nil, NewAuthError("failed to load credentials", err)
		}
		config.SessionID = sessionID
		config.SessionSign = sessionSign
	}

	// Create context for lifecycle management
	ctx, cancel := context.WithCancel(context.Background())

	// Setup logger
	logger := config.Logger
	if logger == nil {
		// Use default logger if not provided
		logger = slog.Default()
	}

	// Create client
	client := &Client{
		config:           *config,
		conn:             transport.NewGorillaWebSocket(),
		sessions:         session.NewManager(),
		callbacks:        make(map[string][]func(...interface{})),
		sendQueue:        []string{},
		isLogged:         false,
		logger:           logger,
		ctx:              ctx,
		cancel:           cancel,
		receiveDone:      make(chan struct{}),
		sendDone:         make(chan struct{}),
		reconnectCount:   0,
		maxReconnects:    10,
		reconnectDelay:   time.Second,
		autoReconnect:    true,
		rateLimitBackoff: 0,
		lastSendTime:     time.Now(),
	}

	return client, nil
}

// Connect establishes a connection to TradingView and authenticates the client.
// This method must be called before using any session functionality.
func (c *Client) Connect(ctx context.Context) error {
	// Connect to WebSocket
	if err := c.connect(); err != nil {
		return err
	}

	// Authenticate
	if err := c.authenticate(); err != nil {
		c.Close()
		return err
	}

	// Start goroutines
	go c.receiveLoop()
	go c.sendLoop()

	return nil
}

// connect establishes the WebSocket connection.
func (c *Client) connect() error {
	url := c.config.Server
	c.logger.Debug("connecting to WebSocket", slog.String("url", url))

	if err := c.conn.Connect(url); err != nil {
		c.logger.Error("failed to connect to WebSocket",
			slog.String("url", url),
			slog.Any("error", err))
		return NewConnectionError("failed to connect to WebSocket", err)
	}

	c.logger.Info("WebSocket connected successfully", slog.String("url", url))
	c.emit("connected")
	return nil
}

// authenticate performs the authentication flow.
func (c *Client) authenticate() error {
	c.logger.Debug("authenticating client")

	// Get user info and auth token
	user, err := getUserInfo(c.config.SessionID, c.config.SessionSign)
	if err != nil {
		c.logger.Error("failed to get user info", slog.Any("error", err))
		return err
	}

	c.mu.Lock()
	c.user = user
	c.mu.Unlock()

	// Send set_auth_token packet
	packet := protocol.Packet{
		Type: "set_auth_token",
		Data: []interface{}{user.AuthToken},
	}

	formatted, err := protocol.FormatWSPacket(packet)
	if err != nil {
		c.logger.Error("failed to format auth packet", slog.Any("error", err))
		return NewProtocolError("failed to format auth packet", err)
	}

	if err := c.conn.Send(formatted); err != nil {
		c.logger.Error("failed to send auth packet", slog.Any("error", err))
		return NewConnectionError("failed to send auth packet", err)
	}

	c.mu.Lock()
	c.isLogged = true
	c.mu.Unlock()

	c.logger.Info("client authenticated successfully",
		slog.String("username", user.Username))
	c.emit("logged", user)
	return nil
}

// loadCredsFromEnv loads credentials from environment variables.
func loadCredsFromEnv() (string, string, error) {
	_ = godotenv.Load()
	sessionID := os.Getenv("SESSION_ID")
	sessionSign := os.Getenv("SESSION_SIGN")

	if sessionID == "" {
		return "", "", fmt.Errorf("SESSION_ID environment variable is required")
	}
	if sessionSign == "" {
		return "", "", fmt.Errorf("SESSION_SIGN environment variable is required")
	}

	return sessionID, sessionSign, nil
}

// getUserInfo gets user information using session credentials.
func getUserInfo(sessionID, sessionSign string) (*auth.User, error) {
	creds := &auth.Credentials{
		SessionID:   sessionID,
		SessionSign: sessionSign,
	}

	return auth.GetUser(creds)
}

// receiveLoop continuously receives and processes packets.
func (c *Client) receiveLoop() {
	defer close(c.receiveDone)

	for {
		select {
		case <-c.ctx.Done():
			return
		default:
			message, err := c.conn.Receive()
			if err != nil {
				if c.ctx.Err() != nil {
					return // Context cancelled, normal shutdown
				}

				// Connection error - attempt reconnection if enabled
				if c.autoReconnect {
					c.emit("error", NewConnectionError("connection lost, attempting reconnection", err))
					if reconnectErr := c.attemptReconnect(); reconnectErr != nil {
						c.emit("error", NewConnectionError("reconnection failed", reconnectErr))
						return
					}
					// Successfully reconnected, continue receiving
					continue
				}

				c.emit("error", NewConnectionError("receive error", err))
				continue
			}

			// Reset reconnect count on successful message
			c.mu.Lock()
			c.reconnectCount = 0
			c.mu.Unlock()

			c.handleMessage(message)
		}
	}
}

// attemptReconnect tries to reconnect to the server with exponential backoff.
func (c *Client) attemptReconnect() error {
	c.mu.Lock()
	c.reconnectCount++
	currentCount := c.reconnectCount
	c.mu.Unlock()

	if currentCount > c.maxReconnects {
		c.logger.Error("max reconnection attempts exceeded",
			slog.Int("max_reconnects", c.maxReconnects),
			slog.Int("attempt", currentCount))
		return fmt.Errorf("max reconnection attempts (%d) exceeded", c.maxReconnects)
	}

	// Calculate exponential backoff delay (max 30 seconds)
	delay := c.reconnectDelay * time.Duration(1<<uint(currentCount-1))
	if delay > 30*time.Second {
		delay = 30 * time.Second
	}

	// Ensure we reconnect within 5s for the first attempt per SC-009
	if currentCount == 1 && delay > 5*time.Second {
		delay = 5 * time.Second
	}

	c.logger.Info("attempting reconnection",
		slog.Int("attempt", currentCount),
		slog.Duration("delay", delay))
	c.emit("reconnecting", currentCount, delay)

	// Wait before reconnecting
	select {
	case <-time.After(delay):
	case <-c.ctx.Done():
		c.logger.Debug("reconnection cancelled by context")
		return fmt.Errorf("reconnection cancelled")
	}

	// Close old connection
	c.conn.Close()

	// Create new connection
	c.conn = transport.NewGorillaWebSocket()

	// Reconnect
	if err := c.connect(); err != nil {
		c.logger.Warn("reconnection attempt failed",
			slog.Int("attempt", currentCount),
			slog.Any("error", err))
		return fmt.Errorf("reconnect failed: %w", err)
	}

	// Re-authenticate
	if err := c.authenticate(); err != nil {
		c.logger.Warn("re-authentication failed",
			slog.Int("attempt", currentCount),
			slog.Any("error", err))
		return fmt.Errorf("re-authentication failed: %w", err)
	}

	c.logger.Info("reconnection successful",
		slog.Int("attempt", currentCount))
	c.emit("reconnected", currentCount)
	return nil
}

// handleMessage processes incoming WebSocket messages.
func (c *Client) handleMessage(message string) {
	packets, err := protocol.ParseWSPacket(message)
	if err != nil {
		c.emit("error", NewProtocolError("failed to parse packet", err))
		return
	}

	// DEBUG: Log all incoming packets
	if c.config.Debug {
		c.logger.Debug("received message",
			slog.Int("packet_count", len(packets)),
			slog.String("raw_message", message))
	}

	// Group packets by session for batch processing
	// This is crucial for detecting "du" + "timescale_update" sequences
	sessionPackets := make(map[string][]protocol.Packet)

	for _, packet := range packets {
		// Handle system packets immediately
		switch packet.Type {
		case "ping":
			// Extract ping ID from packet data
			if len(packet.Data) > 0 {
				if pingID, ok := packet.Data[0].(int); ok {
					c.handlePing(pingID)
				} else if pingIDFloat, ok := packet.Data[0].(float64); ok {
					c.handlePing(int(pingIDFloat))
				}
			}
			continue
		case "protocol_error":
			c.emit("error", NewProtocolError("protocol error from server", fmt.Errorf("%v", packet.Data)))
			continue
		case "rate_limit":
			c.handleRateLimit(packet)
			continue
		}

		// Extract session ID from packet data
		if len(packet.Data) == 0 {
			c.emit("event", packet.Type, packet.Data)
			continue
		}

		// Try to get session ID from first parameter
		sessionID, ok := packet.Data[0].(string)
		if !ok {
			c.emit("event", packet.Type, packet.Data)
			continue
		}

		// Group packets by session
		sessionPackets[sessionID] = append(sessionPackets[sessionID], packet)
	}

	// Process batches for each session
	for sessionID, batch := range sessionPackets {
		// DEBUG: Log batch being routed
		if c.config.Debug {
			packetTypes := make([]string, len(batch))
			for i, p := range batch {
				packetTypes[i] = p.Type
			}
			c.logger.Debug("routing packet batch to session",
				slog.String("session_id", sessionID),
				slog.Any("packet_types", packetTypes))
		}

		if err := c.sessions.RoutePacketBatch(sessionID, batch); err != nil {
			// Session not found, emit as events
			for _, packet := range batch {
				c.emit("event", packet.Type, packet.Data)
			}
		}
	}
}

// routePacket routes a packet to the appropriate handler.
func (c *Client) routePacket(packet protocol.Packet) {
	// Handle system packets
	switch packet.Type {
	case "ping":
		// Extract ping ID from packet data
		if len(packet.Data) > 0 {
			if pingID, ok := packet.Data[0].(int); ok {
				c.handlePing(pingID)
			} else if pingIDFloat, ok := packet.Data[0].(float64); ok {
				c.handlePing(int(pingIDFloat))
			}
		}
		return
	case "protocol_error":
		c.emit("error", NewProtocolError("protocol error from server", fmt.Errorf("%v", packet.Data)))
		return
	case "rate_limit":
		c.handleRateLimit(packet)
		return
	}

	// Extract session ID from packet data
	if len(packet.Data) == 0 {
		c.emit("event", packet.Type, packet.Data)
		return
	}

	// Try to get session ID from first parameter
	sessionID, ok := packet.Data[0].(string)
	if !ok {
		c.emit("event", packet.Type, packet.Data)
		return
	}

	// Route to session
	if err := c.sessions.RoutePacket(sessionID, packet); err != nil {
		// Session not found, might be a global event
		c.emit("event", packet.Type, packet.Data)
	}
}

// handlePing responds to ping packets.
func (c *Client) handlePing(pingID int) {
	// Send pong response immediately
	pongMessage := protocol.FormatPongPacket(pingID)
	if err := c.conn.Send(pongMessage); err != nil {
		c.emit("error", NewConnectionError("failed to send pong", err))
		return
	}
	c.emit("ping")
}

// handleRateLimit handles rate limit signals from the server.
func (c *Client) handleRateLimit(packet protocol.Packet) {
	// Implement exponential backoff for rate limiting
	c.mu.Lock()
	if c.rateLimitBackoff == 0 {
		c.rateLimitBackoff = time.Second
	} else {
		c.rateLimitBackoff *= 2
		if c.rateLimitBackoff > 30*time.Second {
			c.rateLimitBackoff = 30 * time.Second
		}
	}
	backoff := c.rateLimitBackoff
	c.mu.Unlock()

	c.emit("rate_limited", backoff)
	c.emit("error", NewProtocolError(fmt.Sprintf("rate limited, backing off for %v", backoff), fmt.Errorf("%v", packet.Data)))
}

// sendLoop processes the send queue.
func (c *Client) sendLoop() {
	defer close(c.sendDone)

	ticker := time.NewTicker(100 * time.Millisecond)
	defer ticker.Stop()

	for {
		select {
		case <-c.ctx.Done():
			return
		case <-ticker.C:
			c.processSendQueue()
		}
	}
}

// processSendQueue sends queued packets if logged in.
func (c *Client) processSendQueue() {
	c.mu.RLock()
	isLogged := c.isLogged
	backoff := c.rateLimitBackoff
	c.mu.RUnlock()

	if !isLogged {
		return
	}

	// Apply rate limit backoff if active
	if backoff > 0 {
		c.mu.Lock()
		timeSinceLastSend := time.Since(c.lastSendTime)
		if timeSinceLastSend < backoff {
			c.mu.Unlock()
			return // Still in backoff period
		}
		// Backoff period expired, reset it
		c.rateLimitBackoff = 0
		c.mu.Unlock()
	}

	c.queueMu.Lock()
	defer c.queueMu.Unlock()

	for len(c.sendQueue) > 0 {
		message := c.sendQueue[0]
		c.sendQueue = c.sendQueue[1:]

		if err := c.conn.Send(message); err != nil {
			c.emit("error", NewConnectionError("failed to send queued message", err))
			// Re-queue the message
			c.sendQueue = append([]string{message}, c.sendQueue...)
			return
		}

		// Update last send time
		c.mu.Lock()
		c.lastSendTime = time.Now()
		c.mu.Unlock()
	}
}

// Send queues a packet to be sent.
func (c *Client) Send(packet protocol.Packet) error {
	formatted, err := protocol.FormatWSPacket(packet)
	if err != nil {
		return NewProtocolError("failed to format packet", err)
	}

	c.queueMu.Lock()
	c.sendQueue = append(c.sendQueue, formatted)
	c.queueMu.Unlock()

	return nil
}

// SendRaw queues a raw message to be sent.
func (c *Client) SendRaw(message string) {
	c.queueMu.Lock()
	c.sendQueue = append(c.sendQueue, message)
	c.queueMu.Unlock()
}

// On registers an event callback.
func (c *Client) On(event string, callback func(...interface{})) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.callbacks[event] = append(c.callbacks[event], callback)
}

// OnConnected registers a connected event callback.
func (c *Client) OnConnected(callback func()) {
	c.On("connected", func(args ...interface{}) {
		callback()
	})
}

// OnDisconnected registers a disconnected event callback.
func (c *Client) OnDisconnected(callback func()) {
	c.On("disconnected", func(args ...interface{}) {
		callback()
	})
}

// OnLogged registers a logged in event callback.
func (c *Client) OnLogged(callback func(*auth.User)) {
	c.On("logged", func(args ...interface{}) {
		if len(args) > 0 {
			if user, ok := args[0].(*auth.User); ok {
				callback(user)
			}
		}
	})
}

// OnPing registers a ping event callback.
func (c *Client) OnPing(callback func()) {
	c.On("ping", func(args ...interface{}) {
		callback()
	})
}

// OnError registers an error event callback.
func (c *Client) OnError(callback func(error)) {
	c.On("error", func(args ...interface{}) {
		if len(args) > 0 {
			if err, ok := args[0].(error); ok {
				callback(err)
			}
		}
	})
}

// OnEvent registers a generic event callback.
func (c *Client) OnEvent(callback func(string, []interface{})) {
	c.On("event", func(args ...interface{}) {
		if len(args) >= 2 {
			if eventType, ok := args[0].(string); ok {
				if data, ok := args[1].([]interface{}); ok {
					callback(eventType, data)
				}
			}
		}
	})
}

// emit triggers event callbacks.
func (c *Client) emit(event string, args ...interface{}) {
	c.mu.RLock()
	callbacks := c.callbacks[event]
	c.mu.RUnlock()

	for _, callback := range callbacks {
		callback(args...)
	}
}

// Close closes the client and all sessions.
func (c *Client) Close() error {
	// Cancel context to stop goroutines
	c.cancel()

	// Wait for goroutines to finish
	<-c.receiveDone
	<-c.sendDone

	// Close all sessions
	if err := c.sessions.CloseAll(); err != nil {
		// Log error but continue closing
	}

	// Close WebSocket connection
	if err := c.conn.Close(); err != nil {
		return NewConnectionError("failed to close connection", err)
	}

	c.emit("disconnected")
	return nil
}

// End is an alias for Close.
func (c *Client) End() error {
	return c.Close()
}

// IsConnected returns true if the WebSocket is connected.
func (c *Client) IsConnected() bool {
	return c.conn.IsOpen()
}

// IsLogged returns true if the client is authenticated.
func (c *Client) IsLogged() bool {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.isLogged
}

// User returns the authenticated user info.
func (c *Client) User() *auth.User {
	c.mu.RLock()
	defer c.mu.RUnlock()
	return c.user
}

// RegisterSession registers a session with the client.
func (c *Client) RegisterSession(sess session.Session) error {
	return c.sessions.Register(sess)
}

// UnregisterSession unregisters a session from the client.
func (c *Client) UnregisterSession(sessionID string) error {
	return c.sessions.Unregister(sessionID)
}
