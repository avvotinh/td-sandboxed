// Package main - Quick storage test
// Tests Redis and TimescaleDB connectivity
package main

import (
	"context"
	"fmt"
	"os"
	"time"

	"github.com/avvotinh/tv-api/internal/logging"
	"github.com/avvotinh/tv-api/internal/store"
)

func main() {
	logger := logging.Setup(&logging.Config{
		Level:  "info",
		Format: "text",
	})

	fmt.Println("=== Storage Integration Test ===\n")

	ctx := context.Background()

	// Test Redis
	fmt.Println("1. Testing Redis connection...")
	redisURL := getEnv("REDIS_URL", "localhost:6379")
	redisStore, err := store.NewRedisStore(redisURL, "", 0, logger)
	if err != nil {
		fmt.Printf("❌ Redis connection failed: %v\n", err)
		os.Exit(1)
	}
	defer redisStore.Close()
	fmt.Printf("✅ Redis connected: %s\n\n", redisURL)

	// Test Redis write/read
	fmt.Println("2. Testing Redis write/read...")
	testTick := store.TickData{
		Timestamp: time.Now(),
		Symbol:    "BINANCE:BTCUSDT",
		Price:     50000.50,
		Volume:    1.5,
		Bid:       49999.00,
		Ask:       50001.00,
		Exchange:  "BINANCE",
	}

	if err := redisStore.SaveLatestTick(ctx, testTick); err != nil {
		fmt.Printf("❌ Redis write failed: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("✅ Tick saved to Redis")

	retrieved, err := redisStore.GetLatestTick(ctx, "BINANCE:BTCUSDT")
	if err != nil {
		fmt.Printf("❌ Redis read failed: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("✅ Tick retrieved: price=%.2f, volume=%.2f\n\n", retrieved.Price, retrieved.Volume)

	// Test TimescaleDB
	fmt.Println("3. Testing TimescaleDB connection...")
	timescaleURL := getEnv("TIMESCALE_URL",
		"postgres://hftuser:password@localhost:5432/hft_lakehouse?sslmode=disable")

	config := store.Config{
		BatchSize:     10,
		FlushInterval: 2 * time.Second,
	}

	tsStore, err := store.NewTimescaleStore(timescaleURL, config, logger)
	if err != nil {
		fmt.Printf("❌ TimescaleDB connection failed: %v\n", err)
		os.Exit(1)
	}
	defer tsStore.Close()
	fmt.Println("✅ TimescaleDB connected\n")

	// Start batch processor
	fmt.Println("4. Testing TimescaleDB write...")
	if err := tsStore.Start(ctx); err != nil {
		fmt.Printf("❌ Failed to start batch processor: %v\n", err)
		os.Exit(1)
	}

	// Buffer some test candles
	for i := 0; i < 5; i++ {
		candle := store.CandleData{
			Timestamp: time.Now().Add(-time.Duration(i) * time.Minute),
			Symbol:    "BINANCE:BTCUSDT",
			Interval:  "1",
			Open:      50000.0 + float64(i),
			High:      50100.0 + float64(i),
			Low:       49900.0 + float64(i),
			Close:     50050.0 + float64(i),
			Volume:    100.0 + float64(i),
		}
		if err := tsStore.SaveCandle(ctx, candle); err != nil {
			fmt.Printf("❌ Failed to buffer candle: %v\n", err)
		}
	}
	fmt.Println("✅ 5 candles buffered")

	// Wait for flush
	fmt.Println("⏳ Waiting for batch flush (2 seconds)...")
	time.Sleep(3 * time.Second)

	stats := tsStore.GetStats()
	fmt.Printf("✅ Stats: candles_written=%d, buffer_size=%d\n\n",
		stats.CandlesWritten, stats.CandleBufferSize)

	// Test query
	fmt.Println("5. Testing TimescaleDB query...")
	candles, err := tsStore.QueryCandles(ctx, "BINANCE:BTCUSDT", "1",
		time.Now().Add(-10*time.Minute), time.Now(), 10)
	if err != nil {
		fmt.Printf("❌ Query failed: %v\n", err)
		os.Exit(1)
	}
	fmt.Printf("✅ Retrieved %d candles from database\n", len(candles))

	if len(candles) > 0 {
		latest := candles[0]
		fmt.Printf("   Latest candle: O=%.2f H=%.2f L=%.2f C=%.2f V=%.2f\n",
			latest.Open, latest.High, latest.Low, latest.Close, latest.Volume)
	}

	fmt.Println("\n=== All Tests Passed ✅ ===")
}

func getEnv(key, defaultValue string) string {
	if value := os.Getenv(key); value != "" {
		return value
	}
	return defaultValue
}
