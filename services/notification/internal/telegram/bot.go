// Package telegram provides the Telegram bot client for sending notifications.
package telegram

import (
	"context"
	"log"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"

	"github.com/user/sandboxed/services/notification/internal/config"
	"github.com/user/sandboxed/services/notification/internal/errors"
)

// Bot represents the Telegram bot client.
type Bot struct {
	api    *tgbotapi.BotAPI
	chatID int64
	debug  bool
}

// NewBot creates a new Telegram bot client.
func NewBot(cfg *config.Config) (*Bot, error) {
	api, err := tgbotapi.NewBotAPI(cfg.TelegramBotToken)
	if err != nil {
		return nil, errors.Wrap("NewBot", errors.ErrTelegramConnection, err.Error())
	}

	api.Debug = cfg.Debug

	log.Printf("Authorized on account %s", api.Self.UserName)

	return &Bot{
		api:    api,
		chatID: cfg.TelegramChatID,
		debug:  cfg.Debug,
	}, nil
}

// Start begins listening for updates and processing commands.
func (b *Bot) Start(ctx context.Context) error {
	u := tgbotapi.NewUpdate(0)
	u.Timeout = 60

	updates := b.api.GetUpdatesChan(u)

	for {
		select {
		case <-ctx.Done():
			return ctx.Err()
		case update := <-updates:
			if update.Message == nil {
				continue
			}

			if update.Message.IsCommand() {
				b.handleCommand(update.Message)
			}
		}
	}
}

// Stop gracefully stops the bot.
func (b *Bot) Stop() {
	b.api.StopReceivingUpdates()
	log.Println("Telegram bot stopped")
}

// SendMessage sends a message to the configured chat.
func (b *Bot) SendMessage(text string) error {
	if b.chatID == 0 {
		log.Println("Warning: No chat ID configured, message not sent")
		return nil
	}

	msg := tgbotapi.NewMessage(b.chatID, text)
	msg.ParseMode = tgbotapi.ModeMarkdown

	_, err := b.api.Send(msg)
	if err != nil {
		return errors.Wrap("SendMessage", errors.ErrMessageSendFailed, err.Error())
	}

	return nil
}

// handleCommand processes incoming bot commands.
func (b *Bot) handleCommand(msg *tgbotapi.Message) {
	handler := NewCommandHandler(b)
	handler.Handle(msg)
}
