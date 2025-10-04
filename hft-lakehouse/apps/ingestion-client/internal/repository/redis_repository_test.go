package repository

import (
	"context"
	"testing"
	"time"

	"github.com/alicebob/miniredis/v2"
	"github.com/hft-lakehouse/ingestion-client/internal/parser"
	"github.com/redis/go-redis/v9"
)

func setupTestRedis(t *testing.T) (*miniredis.Miniredis, *redis.Client) {
	t.Helper()

	// Start miniredis mock server
	mr, err := miniredis.Run()
	if err != nil {
		t.Fatalf("Failed to start miniredis: %v", err)
	}

	// Create Redis client pointing to miniredis
	client := redis.NewClient(&redis.Options{
		Addr: mr.Addr(),
	})

	return mr, client
}

func TestNewRedisTickRepository(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewRedisTickRepository(client)
	if repo == nil {
		t.Fatal("NewRedisTickRepository returned nil")
	}

	if repo.client != client {
		t.Error("Repository client not set correctly")
	}
}

func TestSaveLatestTick_Success(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewRedisTickRepository(client)
	ctx := context.Background()

	tick := &parser.TickData{
		Symbol:    "BTCUSD",
		Timestamp: time.Date(2025, 10, 2, 10, 30, 0, 0, time.UTC),
		Bid:       45000.50,
		Ask:       45001.00,
		Price:     45000.75,
		Volume:    1.5,
	}

	// Save tick
	if err := repo.SaveLatestTick(ctx, tick); err != nil {
		t.Fatalf("SaveLatestTick failed: %v", err)
	}

	// Verify data in Redis
	key := "latest_tick:BTCUSD"
	result, err := client.HGetAll(ctx, key).Result()
	if err != nil {
		t.Fatalf("Failed to get data from Redis: %v", err)
	}

	// Check all fields
	if result["bid"] != "45000.50000000" {
		t.Errorf("Bid = %v, want 45000.50000000", result["bid"])
	}
	if result["ask"] != "45001.00000000" {
		t.Errorf("Ask = %v, want 45001.00000000", result["ask"])
	}
	if result["price"] != "45000.75000000" {
		t.Errorf("Price = %v, want 45000.75000000", result["price"])
	}
	if result["volume"] != "1.50000000" {
		t.Errorf("Volume = %v, want 1.50000000", result["volume"])
	}
	if result["timestamp"] != "2025-10-02T10:30:00Z" {
		t.Errorf("Timestamp = %v, want 2025-10-02T10:30:00Z", result["timestamp"])
	}
}

func TestSaveLatestTick_MultipleSymbols(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewRedisTickRepository(client)
	ctx := context.Background()

	// Save tick for BTCUSD
	tick1 := &parser.TickData{
		Symbol:    "BTCUSD",
		Timestamp: time.Date(2025, 10, 2, 10, 30, 0, 0, time.UTC),
		Bid:       45000.50,
		Ask:       45001.00,
	}
	if err := repo.SaveLatestTick(ctx, tick1); err != nil {
		t.Fatalf("SaveLatestTick for BTCUSD failed: %v", err)
	}

	// Save tick for ETHUSD
	tick2 := &parser.TickData{
		Symbol:    "ETHUSD",
		Timestamp: time.Date(2025, 10, 2, 10, 31, 0, 0, time.UTC),
		Bid:       2500.10,
		Ask:       2500.20,
	}
	if err := repo.SaveLatestTick(ctx, tick2); err != nil {
		t.Fatalf("SaveLatestTick for ETHUSD failed: %v", err)
	}

	// Verify both keys exist
	btcResult, err := client.HGetAll(ctx, "latest_tick:BTCUSD").Result()
	if err != nil || len(btcResult) == 0 {
		t.Error("BTCUSD tick not found in Redis")
	}

	ethResult, err := client.HGetAll(ctx, "latest_tick:ETHUSD").Result()
	if err != nil || len(ethResult) == 0 {
		t.Error("ETHUSD tick not found in Redis")
	}

	// Verify values
	if btcResult["bid"] != "45000.50000000" {
		t.Errorf("BTCUSD bid = %v, want 45000.50000000", btcResult["bid"])
	}
	if ethResult["bid"] != "2500.10000000" {
		t.Errorf("ETHUSD bid = %v, want 2500.10000000", ethResult["bid"])
	}
}

func TestSaveLatestTick_OverwriteExisting(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewRedisTickRepository(client)
	ctx := context.Background()

	// Save initial tick
	tick1 := &parser.TickData{
		Symbol:    "BTCUSD",
		Timestamp: time.Date(2025, 10, 2, 10, 30, 0, 0, time.UTC),
		Bid:       45000.50,
		Ask:       45001.00,
	}
	if err := repo.SaveLatestTick(ctx, tick1); err != nil {
		t.Fatalf("First SaveLatestTick failed: %v", err)
	}

	// Save updated tick for same symbol
	tick2 := &parser.TickData{
		Symbol:    "BTCUSD",
		Timestamp: time.Date(2025, 10, 2, 10, 31, 0, 0, time.UTC),
		Bid:       46000.00,
		Ask:       46001.00,
	}
	if err := repo.SaveLatestTick(ctx, tick2); err != nil {
		t.Fatalf("Second SaveLatestTick failed: %v", err)
	}

	// Verify data is overwritten
	result, err := client.HGetAll(ctx, "latest_tick:BTCUSD").Result()
	if err != nil {
		t.Fatalf("Failed to get data from Redis: %v", err)
	}

	if result["bid"] != "46000.00000000" {
		t.Errorf("Bid not updated, got %v, want 46000.00000000", result["bid"])
	}
	if result["timestamp"] != "2025-10-02T10:31:00Z" {
		t.Errorf("Timestamp not updated, got %v, want 2025-10-02T10:31:00Z", result["timestamp"])
	}
}

func TestSaveLatestTick_NilTick(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewRedisTickRepository(client)
	ctx := context.Background()

	err := repo.SaveLatestTick(ctx, nil)
	if err == nil {
		t.Fatal("SaveLatestTick with nil tick should fail")
	}
	if err.Error() != "tick data is nil" {
		t.Errorf("Unexpected error: %v", err)
	}
}

func TestSaveLatestTick_EmptySymbol(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()
	defer client.Close()

	repo := NewRedisTickRepository(client)
	ctx := context.Background()

	tick := &parser.TickData{
		Symbol:    "", // Empty symbol
		Timestamp: time.Now(),
		Bid:       45000.50,
		Ask:       45001.00,
	}

	err := repo.SaveLatestTick(ctx, tick)
	if err == nil {
		t.Fatal("SaveLatestTick with empty symbol should fail")
	}
	if err.Error() != "tick symbol is empty" {
		t.Errorf("Unexpected error: %v", err)
	}
}

func TestClose(t *testing.T) {
	mr, client := setupTestRedis(t)
	defer mr.Close()

	repo := NewRedisTickRepository(client)

	if err := repo.Close(); err != nil {
		t.Errorf("Close failed: %v", err)
	}
}

func TestClose_NilClient(t *testing.T) {
	repo := &RedisTickRepository{client: nil}

	if err := repo.Close(); err != nil {
		t.Errorf("Close with nil client should not error: %v", err)
	}
}
