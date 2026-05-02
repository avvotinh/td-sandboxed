// Package main is the entry point for the notification bot service.
//
// Telegram notification service for the Sandboxed trading system.
// Receives alerts via Redis Pub/Sub and sends to Telegram.
package main

import (
	"context"
	"log"
	"os"
	"os/signal"
	"syscall"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/handlers"
	"github.com/user/sandboxed/services/notification/internal/subscriber"
	"github.com/user/sandboxed/services/notification/internal/telegram"
)

func main() {
	log.Println("Notification service starting...")

	// Load configuration
	cfg, err := config.Load()
	if err != nil {
		log.Fatalf("Failed to load configuration: %v", err)
	}

	// Create context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Initialize Telegram bot with retry logic
	bot, err := telegram.NewBotWithContext(ctx, cfg)
	if err != nil {
		log.Fatalf("Failed to initialize Telegram bot: %v", err)
	}
	log.Println("Telegram bot connected")

	// Validate chat ID if configured (sends test message)
	if err := bot.ValidateChatID(); err != nil {
		log.Printf("Warning: Chat ID validation failed: %v", err)
		// Non-blocking - continue startup
	}

	// Create message handlers (scaffolds - full impl in later stories)
	tradeHandler := handlers.NewTradeHandler()
	riskHandler := handlers.NewRiskHandler()
	systemHandler := handlers.NewSystemHandler()
	emergencyHandler := handlers.NewEmergencyHandler()

	// Create router with bot as notifier
	router := subscriber.NewRouter(bot, tradeHandler, riskHandler, systemHandler, emergencyHandler)

	// Initialize Redis subscriber
	sub := subscriber.New(cfg, router)
	log.Println("Redis subscriber initialized")

	// Connect to Redis with retry
	if err := sub.Connect(ctx); err != nil {
		log.Printf("Warning: Redis connection failed: %v", err)
		log.Println("Notification service will continue without Redis - alerts will not be received")
		// Non-blocking - continue without Redis
	}

	// Register subscriber with command handler for status checks
	telegram.SetSubscriber(sub)

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start Redis subscriber in goroutine if connected
	if sub.IsConnected() {
		go func() {
			if err := sub.Start(ctx); err != nil {
				if ctx.Err() == nil {
					log.Printf("Redis subscriber error: %v", err)
				}
			}
		}()
	}

	// Start bot in goroutine
	go func() {
		if err := bot.Start(ctx); err != nil {
			if ctx.Err() == nil {
				log.Printf("Bot error: %v", err)
				cancel()
			}
		}
	}()

	log.Println("Notification service started successfully")

	// Wait for shutdown signal
	sig := <-sigChan
	log.Printf("Received signal %v, initiating graceful shutdown", sig)

	// Cancel context to stop all goroutines
	cancel()

	// Cleanup
	sub.Close()
	bot.Stop()

	log.Println("Notification service stopped")
}
