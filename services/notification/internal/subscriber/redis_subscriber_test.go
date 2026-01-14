package subscriber

import (
	"context"
	"errors"
	"os"
	"sync"
	"testing"
	"time"

	"github.com/user/sandboxed/services/notification/internal/config"
)

// mockNotifier is a test double for the Notifier interface.
type mockNotifier struct {
	mu        sync.Mutex
	messages  []string
	returnErr error
}

func newMockNotifier() *mockNotifier {
	return &mockNotifier{
		messages: make([]string, 0),
	}
}

func newMockNotifierWithError(err error) *mockNotifier {
	return &mockNotifier{
		messages:  make([]string, 0),
		returnErr: err,
	}
}

func (m *mockNotifier) SendMessage(text string) error {
	m.mu.Lock()
	defer m.mu.Unlock()
	if m.returnErr != nil {
		return m.returnErr
	}
	m.messages = append(m.messages, text)
	return nil
}

func (m *mockNotifier) getMessages() []string {
	m.mu.Lock()
	defer m.mu.Unlock()
	result := make([]string, len(m.messages))
	copy(result, m.messages)
	return result
}

// mockHandler is a test double for the Handler interface.
type mockHandler struct {
	mu        sync.Mutex
	calls     []handlerCall
	returnMsg string
	returnErr error
}

type handlerCall struct {
	accountID string
	payload   []byte
}

func newMockHandler(returnMsg string, returnErr error) *mockHandler {
	return &mockHandler{
		calls:     make([]handlerCall, 0),
		returnMsg: returnMsg,
		returnErr: returnErr,
	}
}

func (m *mockHandler) Handle(accountID string, payload []byte) (string, error) {
	m.mu.Lock()
	defer m.mu.Unlock()
	m.calls = append(m.calls, handlerCall{accountID: accountID, payload: payload})
	return m.returnMsg, m.returnErr
}

func (m *mockHandler) getCalls() []handlerCall {
	m.mu.Lock()
	defer m.mu.Unlock()
	result := make([]handlerCall, len(m.calls))
	copy(result, m.calls)
	return result
}

func TestExtractAccountID(t *testing.T) {
	tests := []struct {
		name     string
		channel  string
		expected string
	}{
		{
			name:     "trade channel with account",
			channel:  "alerts:trade:ftmo-gold-001",
			expected: "ftmo-gold-001",
		},
		{
			name:     "risk channel with account",
			channel:  "alerts:risk:ftmo-gold-001",
			expected: "ftmo-gold-001",
		},
		{
			name:     "system channel no account",
			channel:  "alerts:system",
			expected: "",
		},
		{
			name:     "emergency channel no account",
			channel:  "emergency:stop",
			expected: "",
		},
		{
			name:     "account with hyphenated ID",
			channel:  "alerts:trade:my-account-with-many-hyphens",
			expected: "my-account-with-many-hyphens",
		},
		{
			name:     "single part channel",
			channel:  "simple",
			expected: "",
		},
		{
			name:     "two part channel",
			channel:  "alerts:trade",
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := extractAccountID(tt.channel)
			if result != tt.expected {
				t.Errorf("extractAccountID(%q) = %q, want %q", tt.channel, result, tt.expected)
			}
		})
	}
}

func TestRouterRoute_TradeChannel(t *testing.T) {
	notifier := newMockNotifier()
	tradeHandler := newMockHandler("Trade executed", nil)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	router.Route("alerts:trade:ftmo-gold-001", `{"type":"trade_executed"}`)

	// Give goroutine time to send
	time.Sleep(50 * time.Millisecond)

	calls := tradeHandler.getCalls()
	if len(calls) != 1 {
		t.Errorf("expected 1 call to trade handler, got %d", len(calls))
	}
	if len(calls) > 0 && calls[0].accountID != "ftmo-gold-001" {
		t.Errorf("expected accountID 'ftmo-gold-001', got %q", calls[0].accountID)
	}

	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Errorf("expected 1 message sent, got %d", len(messages))
	}
	if len(messages) > 0 && messages[0] != "Trade executed" {
		t.Errorf("expected message 'Trade executed', got %q", messages[0])
	}
}

func TestRouterRoute_RiskChannel(t *testing.T) {
	notifier := newMockNotifier()
	tradeHandler := newMockHandler("", nil)
	riskHandler := newMockHandler("Risk warning", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	router.Route("alerts:risk:ftmo-silver-002", `{"type":"risk_warning"}`)

	// Give goroutine time to send
	time.Sleep(50 * time.Millisecond)

	calls := riskHandler.getCalls()
	if len(calls) != 1 {
		t.Errorf("expected 1 call to risk handler, got %d", len(calls))
	}
	if len(calls) > 0 && calls[0].accountID != "ftmo-silver-002" {
		t.Errorf("expected accountID 'ftmo-silver-002', got %q", calls[0].accountID)
	}

	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Errorf("expected 1 message sent, got %d", len(messages))
	}
}

func TestRouterRoute_SystemChannel(t *testing.T) {
	notifier := newMockNotifier()
	tradeHandler := newMockHandler("", nil)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("System alert", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	router.Route("alerts:system", `{"type":"system_alert"}`)

	// Give goroutine time to send
	time.Sleep(50 * time.Millisecond)

	calls := systemHandler.getCalls()
	if len(calls) != 1 {
		t.Errorf("expected 1 call to system handler, got %d", len(calls))
	}

	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Errorf("expected 1 message sent, got %d", len(messages))
	}
}

func TestRouterRoute_EmergencyChannel(t *testing.T) {
	notifier := newMockNotifier()
	tradeHandler := newMockHandler("", nil)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("EMERGENCY STOP", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	router.Route("emergency:stop", `{"type":"emergency_stop"}`)

	// Give goroutine time to send
	time.Sleep(50 * time.Millisecond)

	calls := emergencyHandler.getCalls()
	if len(calls) != 1 {
		t.Errorf("expected 1 call to emergency handler, got %d", len(calls))
	}

	messages := notifier.getMessages()
	if len(messages) != 1 {
		t.Errorf("expected 1 message sent, got %d", len(messages))
	}
}

func TestRouterRoute_UnknownChannel(t *testing.T) {
	notifier := newMockNotifier()
	tradeHandler := newMockHandler("", nil)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	router.Route("unknown:channel", `{"type":"unknown"}`)

	// Give goroutine time to potentially send
	time.Sleep(50 * time.Millisecond)

	// Verify no handlers were called
	if len(tradeHandler.getCalls()) != 0 {
		t.Error("trade handler should not be called for unknown channel")
	}
	if len(riskHandler.getCalls()) != 0 {
		t.Error("risk handler should not be called for unknown channel")
	}
	if len(systemHandler.getCalls()) != 0 {
		t.Error("system handler should not be called for unknown channel")
	}
	if len(emergencyHandler.getCalls()) != 0 {
		t.Error("emergency handler should not be called for unknown channel")
	}

	// Verify no messages sent
	if len(notifier.getMessages()) != 0 {
		t.Error("no messages should be sent for unknown channel")
	}
}

func TestRouterRoute_EmptyMessage(t *testing.T) {
	notifier := newMockNotifier()
	// Handler returns empty string (no notification)
	tradeHandler := newMockHandler("", nil)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	router.Route("alerts:trade:test-account", `{"type":"trade_executed"}`)

	// Give goroutine time to potentially send
	time.Sleep(50 * time.Millisecond)

	// Handler was called
	if len(tradeHandler.getCalls()) != 1 {
		t.Error("trade handler should be called")
	}

	// But no message sent because handler returned empty string
	if len(notifier.getMessages()) != 0 {
		t.Error("no messages should be sent when handler returns empty string")
	}
}

func TestSubscriberNew(t *testing.T) {
	cfg := &config.Config{
		RedisURL:       "localhost:6379",
		RedisPassword:  "",
		MaxRetries:     3,
		RetryBaseDelay: time.Second,
		MaxRetryDelay:  30 * time.Second,
	}

	notifier := newMockNotifier()
	router := NewRouter(notifier, newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil))

	sub := New(cfg, router)

	if sub == nil {
		t.Fatal("New() returned nil")
	}

	if sub.IsConnected() {
		t.Error("IsConnected() should return false before Connect()")
	}

	channels := sub.Channels()
	expectedChannels := []string{"alerts:trade:*", "alerts:risk:*", "alerts:system", "emergency:stop"}
	if len(channels) != len(expectedChannels) {
		t.Errorf("expected %d channels, got %d", len(expectedChannels), len(channels))
	}
	for i, ch := range channels {
		if ch != expectedChannels[i] {
			t.Errorf("channel[%d] = %q, want %q", i, ch, expectedChannels[i])
		}
	}
}

func TestSubscriberIsConnected(t *testing.T) {
	cfg := &config.Config{
		RedisURL:       "localhost:6379",
		RedisPassword:  "",
		MaxRetries:     1,
		RetryBaseDelay: 10 * time.Millisecond,
		MaxRetryDelay:  100 * time.Millisecond,
	}

	notifier := newMockNotifier()
	router := NewRouter(notifier, newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil))

	sub := New(cfg, router)

	// Before connect - should be false
	if sub.IsConnected() {
		t.Error("IsConnected() should return false before Connect()")
	}

	// After close - should still be false
	sub.Close()
	if sub.IsConnected() {
		t.Error("IsConnected() should return false after Close()")
	}
}

func TestSubscriberConnectCancellation(t *testing.T) {
	cfg := &config.Config{
		RedisURL:       "invalid-host:9999", // Non-existent host
		RedisPassword:  "",
		MaxRetries:     5,
		RetryBaseDelay: time.Second,
		MaxRetryDelay:  10 * time.Second,
	}

	notifier := newMockNotifier()
	router := NewRouter(notifier, newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil))

	sub := New(cfg, router)

	// Create a context that cancels quickly
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()

	err := sub.Connect(ctx)
	if err == nil {
		t.Error("expected error when context is cancelled during connection")
		sub.Close()
	}

	if sub.IsConnected() {
		t.Error("should not be connected after cancelled connection")
	}
}

// Integration test - requires Redis to be running
func TestSubscriberIntegration(t *testing.T) {
	redisURL := os.Getenv("REDIS_URL")
	if redisURL == "" {
		t.Skip("Skipping integration test: REDIS_URL not set")
	}

	cfg := &config.Config{
		RedisURL:       redisURL,
		RedisPassword:  os.Getenv("REDIS_PASSWORD"),
		MaxRetries:     3,
		RetryBaseDelay: time.Second,
		MaxRetryDelay:  10 * time.Second,
	}

	notifier := newMockNotifier()
	tradeHandler := newMockHandler("Trade notification", nil)
	router := NewRouter(notifier, tradeHandler, newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil))

	sub := New(cfg, router)

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	// Connect to Redis
	err := sub.Connect(ctx)
	if err != nil {
		t.Fatalf("Connect() failed: %v", err)
	}

	if !sub.IsConnected() {
		t.Error("IsConnected() should return true after successful Connect()")
	}

	// Verify channels
	channels := sub.Channels()
	if len(channels) != 4 {
		t.Errorf("expected 4 channels, got %d", len(channels))
	}

	// Cleanup
	sub.Close()

	if sub.IsConnected() {
		t.Error("IsConnected() should return false after Close()")
	}
}

// Test pattern matching for alerts:trade:* channels
func TestPatternMatchingTradeChannels(t *testing.T) {
	notifier := newMockNotifier()
	tradeHandler := newMockHandler("Trade notification", nil)
	router := NewRouter(notifier, tradeHandler, newMockHandler("", nil), newMockHandler("", nil), newMockHandler("", nil))

	// Test various trade channel patterns
	testCases := []struct {
		channel   string
		accountID string
	}{
		{"alerts:trade:ftmo-gold-001", "ftmo-gold-001"},
		{"alerts:trade:my-account", "my-account"},
		{"alerts:trade:a", "a"},
		{"alerts:trade:account-with-numbers-123", "account-with-numbers-123"},
	}

	for _, tc := range testCases {
		t.Run(tc.channel, func(t *testing.T) {
			router.Route(tc.channel, `{"type":"trade_executed"}`)
			time.Sleep(50 * time.Millisecond)

			calls := tradeHandler.getCalls()
			if len(calls) == 0 {
				t.Error("trade handler should be called")
				return
			}
			lastCall := calls[len(calls)-1]
			if lastCall.accountID != tc.accountID {
				t.Errorf("expected accountID %q, got %q", tc.accountID, lastCall.accountID)
			}
		})
	}
}

// Test handler returning error - should log but not crash
func TestRouterRoute_HandlerError(t *testing.T) {
	notifier := newMockNotifier()
	handlerErr := errors.New("handler processing failed")
	tradeHandler := newMockHandler("", handlerErr)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	// Route should not panic when handler returns error
	router.Route("alerts:trade:test-account", `{"type":"trade_executed"}`)

	// Give goroutine time to potentially send
	time.Sleep(50 * time.Millisecond)

	// Handler was called
	calls := tradeHandler.getCalls()
	if len(calls) != 1 {
		t.Errorf("expected 1 call to trade handler, got %d", len(calls))
	}

	// No message should be sent because handler returned error
	messages := notifier.getMessages()
	if len(messages) != 0 {
		t.Errorf("expected no messages when handler errors, got %d", len(messages))
	}
}

// Test notifier returning error - should log but not crash
func TestRouterRoute_NotifierError(t *testing.T) {
	notifierErr := errors.New("telegram API unavailable")
	notifier := newMockNotifierWithError(notifierErr)
	tradeHandler := newMockHandler("Trade executed", nil)
	riskHandler := newMockHandler("", nil)
	systemHandler := newMockHandler("", nil)
	emergencyHandler := newMockHandler("", nil)

	router := NewRouter(notifier, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	// Route should not panic when notifier returns error
	router.Route("alerts:trade:test-account", `{"type":"trade_executed"}`)

	// Give goroutine time to attempt send
	time.Sleep(50 * time.Millisecond)

	// Handler was called
	calls := tradeHandler.getCalls()
	if len(calls) != 1 {
		t.Errorf("expected 1 call to trade handler, got %d", len(calls))
	}

	// Notifier was called but returned error (no messages stored)
	messages := notifier.getMessages()
	if len(messages) != 0 {
		t.Errorf("expected no messages stored when notifier errors, got %d", len(messages))
	}
}
