package websocket

import (
	"context"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/gorilla/websocket"
	"github.com/hft-lakehouse/ingestion-client/internal/config"
	"github.com/hft-lakehouse/ingestion-client/internal/logger"
	"github.com/hft-lakehouse/ingestion-client/internal/repository"
	"github.com/redis/go-redis/v9"
)

var upgrader = websocket.Upgrader{
	CheckOrigin: func(r *http.Request) bool {
		return true
	},
}

// mockWebSocketServer creates a test WebSocket server
func mockWebSocketServer(t *testing.T, handler func(*websocket.Conn)) *httptest.Server {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		conn, err := upgrader.Upgrade(w, r, nil)
		if err != nil {
			t.Fatalf("Failed to upgrade connection: %v", err)
		}
		defer conn.Close()

		if handler != nil {
			handler(conn)
		}
	}))

	return server
}

// setupTestRedis creates a miniredis instance and repository for testing
func setupTestRedis(t *testing.T) (*miniredis.Miniredis, repository.TickRepository) {
	t.Helper()

	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("Failed to start miniredis: %v", err)
	}

	client := redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})

	repo := repository.NewRedisTickRepository(client)
	return mr, repo
}

func TestNew(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	cfg := &config.Config{
		TradingViewWSURL:    "wss://test.example.com",
		TradingViewUsername: "test",
		TradingViewPassword: "test",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)

	if client == nil {
		t.Fatal("New() returned nil client")
	}

	if client.config != cfg {
		t.Error("Client config not set correctly")
	}

	if client.logger != log {
		t.Error("Client logger not set correctly")
	}

	if client.repo != repo {
		t.Error("Client repository not set correctly")
	}

	if client.parser == nil {
		t.Error("Client parser not initialized")
	}
}

func TestConnect(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	// Create mock WebSocket server
	server := mockWebSocketServer(t, func(conn *websocket.Conn) {
		// Read authentication message
		var authMsg map[string]interface{}
		if err := conn.ReadJSON(&authMsg); err != nil {
			t.Logf("Error reading auth message: %v", err)
		}
	})
	defer server.Close()

	// Convert http:// to ws://
	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")

	cfg := &config.Config{
		TradingViewWSURL:    wsURL,
		TradingViewUsername: "testuser",
		TradingViewPassword: "testpass",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)
	ctx := context.Background()

	err := client.Connect(ctx)
	if err != nil {
		t.Fatalf("Connect() failed: %v", err)
	}

	if !client.IsConnected() {
		t.Error("Client should be connected")
	}

	// Cleanup
	client.Close()
}

func TestConnectFailure(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	// Test connection to invalid URL
	cfg := &config.Config{
		TradingViewWSURL:    "ws://invalid-host-that-doesnt-exist:99999",
		TradingViewUsername: "test",
		TradingViewPassword: "test",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)
	ctx := context.Background()

	err := client.Connect(ctx)
	if err == nil {
		t.Error("Connect() should fail with invalid URL")
	}

	if client.IsConnected() {
		t.Error("Client should not be connected after failed connection")
	}
}

func TestIsConnected(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	cfg := &config.Config{
		TradingViewWSURL:    "wss://test.example.com",
		TradingViewUsername: "test",
		TradingViewPassword: "test",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)

	if client.IsConnected() {
		t.Error("Client should not be connected initially")
	}
}

func TestClose(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	server := mockWebSocketServer(t, func(conn *websocket.Conn) {
		// Read auth message
		var authMsg map[string]interface{}
		conn.ReadJSON(&authMsg)
	})
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")

	cfg := &config.Config{
		TradingViewWSURL:    wsURL,
		TradingViewUsername: "test",
		TradingViewPassword: "test",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)
	ctx := context.Background()

	// Connect first
	if err := client.Connect(ctx); err != nil {
		t.Fatalf("Connect() failed: %v", err)
	}

	// Close connection
	if err := client.Close(); err != nil {
		t.Fatalf("Close() failed: %v", err)
	}

	// Closing again should not error
	if err := client.Close(); err != nil {
		t.Errorf("Second Close() should not error: %v", err)
	}
}

func TestAuthenticate(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	receivedAuth := false

	server := mockWebSocketServer(t, func(conn *websocket.Conn) {
		// Read and verify authentication message
		var authMsg map[string]interface{}
		if err := conn.ReadJSON(&authMsg); err != nil {
			t.Errorf("Failed to read auth message: %v", err)
			return
		}

		if authMsg["m"] != "auth" {
			t.Errorf("Auth message type = %v, want 'auth'", authMsg["m"])
		}

		receivedAuth = true
	})
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")

	cfg := &config.Config{
		TradingViewWSURL:    wsURL,
		TradingViewUsername: "testuser",
		TradingViewPassword: "testpass",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)
	ctx := context.Background()

	if err := client.Connect(ctx); err != nil {
		t.Fatalf("Connect() failed: %v", err)
	}
	defer client.Close()

	// Give server time to receive auth message
	time.Sleep(50 * time.Millisecond)

	if !receivedAuth {
		t.Error("Server did not receive authentication message")
	}
}

func TestReconnect(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	attemptCount := 0

	server := mockWebSocketServer(t, func(conn *websocket.Conn) {
		attemptCount++
		// Read auth message
		var authMsg map[string]interface{}
		conn.ReadJSON(&authMsg)
	})
	defer server.Close()

	wsURL := "ws" + strings.TrimPrefix(server.URL, "http")

	cfg := &config.Config{
		TradingViewWSURL:    wsURL,
		TradingViewUsername: "test",
		TradingViewPassword: "test",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)
	ctx := context.Background()

	// Reconnect should succeed on first attempt since server is up
	if err := client.Reconnect(ctx); err != nil {
		t.Fatalf("Reconnect() failed: %v", err)
	}
	defer client.Close()

	if !client.IsConnected() {
		t.Error("Client should be connected after successful reconnect")
	}

	if attemptCount == 0 {
		t.Error("Server should have received connection attempt")
	}
}

func TestReconnectCancelled(t *testing.T) {
	mr, repo := setupTestRedis(t)
	defer mr.Close()

	// Create a server that never accepts connections to force retries
	cfg := &config.Config{
		TradingViewWSURL:    "ws://invalid-host-999999:99999",
		TradingViewUsername: "test",
		TradingViewPassword: "test",
		RedisHost:           "localhost",
		RedisPort:           6379,
	}
	log := logger.New()

	client := New(cfg, log, repo)

	// Create context that will be cancelled
	ctx, cancel := context.WithCancel(context.Background())

	// Cancel context after short delay
	go func() {
		time.Sleep(100 * time.Millisecond)
		cancel()
	}()

	err := client.Reconnect(ctx)
	if err == nil {
		t.Error("Reconnect() should return error when context is cancelled")
	}

	if err != context.Canceled {
		t.Logf("Got error: %v (expected context.Canceled)", err)
	}
}
