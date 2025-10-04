package main

import (
	"context"
	"fmt"
	"log/slog"
	"os"
	"os/signal"
	"syscall"

	"github.com/hft-lakehouse/ingestion-client/internal/config"
	"github.com/hft-lakehouse/ingestion-client/internal/logger"
	"github.com/hft-lakehouse/ingestion-client/internal/repository"
	"github.com/hft-lakehouse/ingestion-client/internal/websocket"
	"github.com/redis/go-redis/v9"
)

func main() {
	// Initialize structured logger
	log := logger.New()

	log.Info("starting ingestion client")

	// Load configuration from environment variables
	cfg, err := config.Load()
	if err != nil {
		log.Error("failed to load configuration",
			slog.String("error", err.Error()),
		)
		os.Exit(1)
	}

	log.Info("configuration loaded successfully")

	// Create context with cancellation for graceful shutdown
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize Redis client
	redisClient := redis.NewClient(&redis.Options{
		Addr:     fmt.Sprintf("%s:%d", cfg.RedisHost, cfg.RedisPort),
		Password: cfg.RedisPassword,
		DB:       cfg.RedisDB,
	})
	defer redisClient.Close()

	// Verify Redis connection
	if err := redisClient.Ping(ctx).Err(); err != nil {
		log.Error("failed to connect to redis",
			slog.String("error", err.Error()),
			slog.String("host", cfg.RedisHost),
			slog.Int("port", cfg.RedisPort),
		)
		os.Exit(1)
	}

	log.Info("redis connection established",
		slog.String("host", cfg.RedisHost),
		slog.Int("port", cfg.RedisPort),
	)

	// Create Redis repository
	tickRepo := repository.NewRedisTickRepository(redisClient)

	// Create WebSocket client with repository
	wsClient := websocket.New(cfg, log, tickRepo)

	// Handle OS signals for graceful shutdown
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Goroutine to handle connection and reconnection
	go func() {
		// Initial connection attempt
		if err := wsClient.Connect(ctx); err != nil {
			log.Error("initial connection failed, starting reconnection loop",
				slog.String("error", err.Error()),
			)

			// Start reconnection loop
			if err := wsClient.Reconnect(ctx); err != nil {
				log.Error("reconnection stopped",
					slog.String("error", err.Error()),
				)
				cancel()
				return
			}
		}

		log.Info("websocket client connected and running")

		// Start reading and processing messages
		if err := wsClient.ReadMessages(ctx); err != nil {
			log.Error("message processing stopped",
				slog.String("error", err.Error()),
			)
			cancel()
		}
	}()

	// Wait for shutdown signal
	sig := <-sigChan
	log.Info("received shutdown signal",
		slog.String("signal", sig.String()),
	)

	// Cancel context to trigger graceful shutdown
	cancel()

	// Close WebSocket connection
	if err := wsClient.Close(); err != nil {
		log.Error("error closing websocket",
			slog.String("error", err.Error()),
		)
	}

	log.Info("ingestion client stopped gracefully")
}
