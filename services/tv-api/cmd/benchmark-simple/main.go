// Package main - Simplified Hot Path Benchmark
// Story 1.5: Quick Redis benchmark for NFR1 validation
package main

import (
	"context"
	"flag"
	"fmt"
	"log/slog"
	"os"
	"sort"
	"time"

	"github.com/avvotinh/tv-api/internal/store"
)

func main() {
	iterations := flag.Int("iterations", 1000, "Number of iterations")
	redisURL := flag.String("redis", "localhost:6379", "Redis URL")
	flag.Parse()

	logger := slog.New(slog.NewTextHandler(os.Stderr, &slog.HandlerOptions{
		Level: slog.LevelWarn,
	}))

	fmt.Println("╔══════════════════════════════════════════════════════════╗")
	fmt.Println("║   HFT Data Lakehouse - Hot Path Benchmark (NFR1)        ║")
	fmt.Println("╚══════════════════════════════════════════════════════════╝")
	fmt.Println()
	fmt.Printf("Target: <20ms average latency\n")
	fmt.Printf("Iterations: %d\n", *iterations)
	fmt.Printf("Redis: %s\n", *redisURL)
	fmt.Println()

	ctx := context.Background()

	// Setup test data
	fmt.Println("Setup: Preparing test data...")
	redisStore, err := store.NewRedisStore(*redisURL, "", 0, logger)
	if err != nil {
		fmt.Printf("❌ Failed to connect to Redis: %v\n", err)
		os.Exit(1)
	}

	testTick := store.TickData{
		Timestamp: time.Now(),
		Symbol:    "BINANCE:BTCUSDT",
		Price:     50000.0,
		Volume:    1.5,
		Bid:       49999.0,
		Ask:       50001.0,
		Exchange:  "BINANCE",
	}

	if err := redisStore.SaveLatestTick(ctx, testTick); err != nil {
		fmt.Printf("❌ Failed to save test data: %v\n", err)
		os.Exit(1)
	}
	fmt.Println("✓ Test data ready")
	fmt.Println()

	// Run benchmark
	fmt.Printf("Running benchmark (%d iterations)...\n", *iterations)
	latencies := make([]time.Duration, *iterations)
	successCount := 0

	startTime := time.Now()

	for i := 0; i < *iterations; i++ {
		queryStart := time.Now()
		_, err := redisStore.GetLatestTick(ctx, "BINANCE:BTCUSDT")
		latencies[i] = time.Since(queryStart)

		if err == nil {
			successCount++
		}

		// Progress indicator
		if (i+1)%100 == 0 {
			fmt.Printf("  Progress: %d/%d\r", i+1, *iterations)
		}
	}

	totalDuration := time.Since(startTime)
	fmt.Println()

	redisStore.Close()

	// Calculate statistics
	sort.Slice(latencies, func(i, j int) bool {
		return latencies[i] < latencies[j]
	})

	var sum time.Duration
	for _, lat := range latencies {
		sum += lat
	}

	avgLatency := sum / time.Duration(*iterations)
	minLatency := latencies[0]
	maxLatency := latencies[*iterations-1]
	p50Latency := latencies[*iterations*50/100]
	p95Latency := latencies[*iterations*95/100]
	p99Latency := latencies[*iterations*99/100]

	successRate := float64(successCount) / float64(*iterations) * 100
	avgLatencyMs := avgLatency.Seconds() * 1000
	targetMet := avgLatencyMs < 20.0

	// Display results
	fmt.Println()
	fmt.Println("═══ Results ═══")
	fmt.Println()

	status := "❌"
	if targetMet {
		status = "✅"
	}

	fmt.Printf("┌─ %s Redis Hot Path Performance ──────────────────────────┐\n", status)
	fmt.Printf("│\n")
	fmt.Printf("│ Iterations:    %d\n", *iterations)
	fmt.Printf("│ Success Rate:  %.1f%%\n", successRate)
	fmt.Printf("│ Total Time:    %.2f seconds\n", totalDuration.Seconds())
	fmt.Printf("│\n")
	fmt.Printf("│ Average:       %.3f ms\n", avgLatencyMs)
	fmt.Printf("│ Minimum:       %.3f ms\n", minLatency.Seconds()*1000)
	fmt.Printf("│ Maximum:       %.3f ms\n", maxLatency.Seconds()*1000)
	fmt.Printf("│ P50 (median):  %.3f ms\n", p50Latency.Seconds()*1000)
	fmt.Printf("│ P95:           %.3f ms\n", p95Latency.Seconds()*1000)
	fmt.Printf("│ P99:           %.3f ms\n", p99Latency.Seconds()*1000)
	fmt.Printf("│\n")
	fmt.Printf("│ Target:        < 20.0 ms\n")
	
	if targetMet {
		fmt.Printf("│ Status:        ✅ PASS\n")
	} else {
		fmt.Printf("│ Status:        ❌ FAIL\n")
	}
	fmt.Printf("└──────────────────────────────────────────────────────────┘\n")
	fmt.Println()

	// Final verdict
	if targetMet {
		fmt.Printf("✅ SUCCESS: Hot path meets NFR1 requirement (%.2fms < 20ms)\n", avgLatencyMs)
		fmt.Println()
		fmt.Println("🎉 System validated for real-time trading!")
		os.Exit(0)
	} else {
		fmt.Printf("❌ FAILURE: Hot path exceeds NFR1 requirement (%.2fms > 20ms)\n", avgLatencyMs)
		fmt.Println()
		fmt.Println("⚠️  Optimization needed before production use")
		os.Exit(1)
	}
}
