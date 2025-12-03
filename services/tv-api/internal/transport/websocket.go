package transport

import (
	"fmt"
	"net/http"
	"sync"
	"time"

	"github.com/gorilla/websocket"
)

// WebSocketConn is an interface for WebSocket connections to enable testing.
type WebSocketConn interface {
	// Connect establishes a WebSocket connection to the specified URL.
	Connect(url string) error

	// Send sends a message through the WebSocket connection.
	Send(message string) error

	// Receive reads a message from the WebSocket connection.
	// This is a blocking call that waits for a message.
	Receive() (string, error)

	// Close closes the WebSocket connection.
	Close() error

	// IsOpen returns true if the connection is open.
	IsOpen() bool

	// SetReadDeadline sets the read deadline for the connection.
	SetReadDeadline(t time.Time) error

	// SetWriteDeadline sets the write deadline for the connection.
	SetWriteDeadline(t time.Time) error
}

// GorillaWebSocket is a WebSocketConn implementation using gorilla/websocket.
type GorillaWebSocket struct {
	conn *websocket.Conn
	mu   sync.RWMutex
	open bool
	url  string
}

// NewGorillaWebSocket creates a new GorillaWebSocket instance.
func NewGorillaWebSocket() *GorillaWebSocket {
	return &GorillaWebSocket{
		open: false,
	}
}

// Connect establishes a WebSocket connection.
func (g *GorillaWebSocket) Connect(url string) error {
	g.mu.Lock()
	defer g.mu.Unlock()

	if g.open {
		return fmt.Errorf("connection already open")
	}

	// Set up headers required by TradingView WebSocket server
	headers := http.Header{}
	headers.Set("Origin", "https://www.tradingview.com")
	headers.Set("User-Agent", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36")

	// Connect to WebSocket with headers
	conn, _, err := websocket.DefaultDialer.Dial(url, headers)
	if err != nil {
		return fmt.Errorf("failed to connect to WebSocket: %w", err)
	}

	g.conn = conn
	g.url = url
	g.open = true

	return nil
}

// Send sends a message through the WebSocket.
func (g *GorillaWebSocket) Send(message string) error {
	g.mu.RLock()
	defer g.mu.RUnlock()

	if !g.open || g.conn == nil {
		return fmt.Errorf("connection not open")
	}

	err := g.conn.WriteMessage(websocket.TextMessage, []byte(message))
	if err != nil {
		return fmt.Errorf("failed to send message: %w", err)
	}

	return nil
}

// Receive reads a message from the WebSocket.
func (g *GorillaWebSocket) Receive() (string, error) {
	g.mu.RLock()
	conn := g.conn
	open := g.open
	g.mu.RUnlock()

	if !open || conn == nil {
		return "", fmt.Errorf("connection not open")
	}

	messageType, message, err := conn.ReadMessage()
	if err != nil {
		return "", fmt.Errorf("failed to read message: %w", err)
	}

	if messageType != websocket.TextMessage {
		return "", fmt.Errorf("unexpected message type: %d", messageType)
	}

	return string(message), nil
}

// Close closes the WebSocket connection.
func (g *GorillaWebSocket) Close() error {
	g.mu.Lock()
	defer g.mu.Unlock()

	if !g.open || g.conn == nil {
		return nil // Already closed
	}

	// Send close message
	err := g.conn.WriteMessage(
		websocket.CloseMessage,
		websocket.FormatCloseMessage(websocket.CloseNormalClosure, ""),
	)
	if err != nil {
		// Ignore error on close message send
	}

	// Close the underlying connection
	closeErr := g.conn.Close()
	g.open = false
	g.conn = nil

	if closeErr != nil {
		return fmt.Errorf("failed to close connection: %w", closeErr)
	}

	return nil
}

// IsOpen returns true if the connection is open.
func (g *GorillaWebSocket) IsOpen() bool {
	g.mu.RLock()
	defer g.mu.RUnlock()
	return g.open
}

// SetReadDeadline sets the read deadline.
func (g *GorillaWebSocket) SetReadDeadline(t time.Time) error {
	g.mu.RLock()
	defer g.mu.RUnlock()

	if !g.open || g.conn == nil {
		return fmt.Errorf("connection not open")
	}

	return g.conn.SetReadDeadline(t)
}

// SetWriteDeadline sets the write deadline.
func (g *GorillaWebSocket) SetWriteDeadline(t time.Time) error {
	g.mu.RLock()
	defer g.mu.RUnlock()

	if !g.open || g.conn == nil {
		return fmt.Errorf("connection not open")
	}

	return g.conn.SetWriteDeadline(t)
}
