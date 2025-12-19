// Package telegram provides command handlers for the Telegram bot.
package telegram

import (
	"fmt"
	"log"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// CommandHandler processes bot commands.
type CommandHandler struct {
	bot *Bot
}

// NewCommandHandler creates a new command handler.
func NewCommandHandler(bot *Bot) *CommandHandler {
	return &CommandHandler{bot: bot}
}

// Handle processes a command message.
func (h *CommandHandler) Handle(msg *tgbotapi.Message) {
	var response string

	switch msg.Command() {
	case "start":
		response = h.handleStart(msg)
	case "help":
		response = h.handleHelp()
	case "status":
		response = h.handleStatus()
	case "stop_all":
		response = h.handleStopAll()
	case "resume_all":
		response = h.handleResumeAll()
	default:
		response = "Unknown command. Use /help for available commands."
	}

	reply := tgbotapi.NewMessage(msg.Chat.ID, response)
	reply.ParseMode = tgbotapi.ModeMarkdown

	if _, err := h.bot.api.Send(reply); err != nil {
		log.Printf("Failed to send reply: %v", err)
	}
}

func (h *CommandHandler) handleStart(msg *tgbotapi.Message) string {
	userName := "unknown"
	if msg.From != nil {
		userName = msg.From.UserName
	}
	log.Printf("Start command from chat_id: %d, user: %s", msg.Chat.ID, userName)
	return fmt.Sprintf(`*Welcome to Sandboxed Trading Bot!*

Your chat ID: `+"`%d`"+`

This bot will notify you about:
- Trade executions
- Risk warnings
- System alerts

Use /help for available commands.`, msg.Chat.ID)
}

func (h *CommandHandler) handleHelp() string {
	return `*Available Commands:*

/status - Show current system status
/stop_all - Emergency stop all accounts
/resume_all - Resume trading after stop
/help - Show this help message

*Note:* This is a scaffold. Full functionality in Epic 6.`
}

func (h *CommandHandler) handleStatus() string {
	// Scaffold: Return placeholder status
	return `*System Status (Scaffold)*

Bot: Online
Redis: Not connected (scaffold)
Accounts: N/A

Full status in Story 6.1+`
}

func (h *CommandHandler) handleStopAll() string {
	// Scaffold: Return placeholder response
	log.Println("Emergency stop command received (scaffold mode)")
	return `*Emergency Stop (Scaffold)*

This is a scaffold implementation.
Full emergency stop in Story 6.5.`
}

func (h *CommandHandler) handleResumeAll() string {
	// Scaffold: Return placeholder response
	log.Println("Resume command received (scaffold mode)")
	return `*Resume Trading (Scaffold)*

This is a scaffold implementation.
Full resume functionality in Story 6.6.`
}
