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

	// Initialize Telegram bot
	bot, err := telegram.NewBot(cfg)
	if err != nil {
		log.Fatalf("Failed to initialize Telegram bot: %v", err)
	}
	log.Println("Telegram bot connected")

	// Initialize Redis subscriber (scaffold - doesn't connect yet)
	sub := subscriber.New(cfg)
	log.Printf("Redis subscriber initialized (scaffold mode)")

	// Handle shutdown signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, syscall.SIGINT, syscall.SIGTERM)

	// Start bot in goroutine
	go func() {
		if err := bot.Start(ctx); err != nil {
			log.Printf("Bot error: %v", err)
			cancel()
		}
	}()

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
