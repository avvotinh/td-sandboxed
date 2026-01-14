// Package telegram provides command handlers for the Telegram bot.
package telegram

import (
	"fmt"
	"log"
	"strings"
	"sync"

	tgbotapi "github.com/go-telegram-bot-api/telegram-bot-api/v5"
)

// RedisStatusChecker provides Redis connection status.
type RedisStatusChecker interface {
	IsConnected() bool
	Channels() []string
}

// Package-level subscriber reference for status checks with mutex protection
var (
	redisSubscriber   RedisStatusChecker
	redisSubscriberMu sync.RWMutex
)

// SetSubscriber sets the subscriber reference for status checks.
// Thread-safe for concurrent access.
func SetSubscriber(sub RedisStatusChecker) {
	redisSubscriberMu.Lock()
	defer redisSubscriberMu.Unlock()
	redisSubscriber = sub
}

// getSubscriber returns the subscriber reference safely.
func getSubscriber() RedisStatusChecker {
	redisSubscriberMu.RLock()
	defer redisSubscriberMu.RUnlock()
	return redisSubscriber
}

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
	// Extract user information
	userName := "unknown"
	firstName := ""
	lastName := ""
	userID := int64(0)
	if msg.From != nil {
		userName = msg.From.UserName
		firstName = msg.From.FirstName
		lastName = msg.From.LastName
		userID = msg.From.ID
	}

	// Log comprehensive user and chat information
	log.Printf("=== /start command received ===")
	log.Printf("  Chat ID: %d", msg.Chat.ID)
	log.Printf("  Chat Type: %s", msg.Chat.Type)
	log.Printf("  User ID: %d", userID)
	log.Printf("  Username: @%s", userName)
	log.Printf("  Name: %s %s", firstName, lastName)
	log.Printf("================================")

	// Format welcome message with configuration instructions
	return fmt.Sprintf(`*Welcome to Sandboxed Trading Bot!*

*Your Configuration Details:*
━━━━━━━━━━━━━━━━━━━━━━
Chat ID: `+"`%d`"+`
Username: @%s
━━━━━━━━━━━━━━━━━━━━━━

*To receive notifications:*
Add this to your environment:
`+"```"+`
TELEGRAM_CHAT_ID=%d
`+"```"+`

*This bot will notify you about:*
• Trade executions and fills
• Risk limit warnings
• FTMO rule violations
• System alerts and errors
• Emergency stop notifications

*Available Commands:*
/status - Check bot connection status
/help - Show all available commands
/stop_all - Emergency stop all trading
/resume_all - Resume trading after stop

_Tip: Save your Chat ID above for configuration!_`, msg.Chat.ID, userName, msg.Chat.ID)
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
	// Check actual bot health status
	botStatus := "Disconnected"
	if h.bot.IsHealthy() {
		botStatus = "Connected"
	}

	// Get configured chat ID status
	chatIDStatus := "Not configured"
	if h.bot.ChatID() != 0 {
		chatIDStatus = fmt.Sprintf("Configured (%d)", h.bot.ChatID())
	}

	// Check Redis connection status (thread-safe access)
	redisStatus := "Not initialized"
	channelInfo := ""
	sub := getSubscriber()
	if sub != nil {
		if sub.IsConnected() {
			redisStatus = "Connected"
			channels := sub.Channels()
			channelInfo = fmt.Sprintf("\n• Channels: %s", strings.Join(channels, ", "))
		} else {
			redisStatus = "Disconnected"
		}
	}

	return fmt.Sprintf(`*System Status*

*Telegram Bot:*
• Status: %s
• Username: @%s
• Chat ID: %s

*Redis Subscriber:*
• Status: %s%s

*Services:*
• Trading Accounts: N/A (Story 6.3+)

_Last checked: now_`, botStatus, h.bot.Username(), chatIDStatus, redisStatus, channelInfo)
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
