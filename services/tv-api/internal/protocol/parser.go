package protocol

import (
	"encoding/json"
	"fmt"
	"log"
	"regexp"
	"strconv"
	"strings"
)

// Packet represents a WebSocket message packet.
type Packet struct {
	Type string        `json:"m,omitempty"` // Message type
	Data []interface{} `json:"p,omitempty"` // Parameters/payload
}

var (
	// cleanerRegex removes heartbeat markers from messages.
	cleanerRegex = regexp.MustCompile(`~h~`)

	// splitterRegex splits concatenated packets.
	splitterRegex = regexp.MustCompile(`~m~[0-9]+~m~`)
)

// ParseWSPacket parses a WebSocket message into one or more packets.
// The TradingView protocol format is: ~m~<length>~m~<payload>
// Multiple packets can be concatenated in a single message.
func ParseWSPacket(message string) ([]Packet, error) {
	if message == "" {
		return nil, fmt.Errorf("empty message")
	}

	// Remove heartbeat markers
	message = cleanerRegex.ReplaceAllString(message, "")

	// Split into individual packet payloads
	parts := splitterRegex.Split(message, -1)

	var packets []Packet
	for i, part := range parts {
		part = strings.TrimSpace(part)
		if part == "" {
			continue
		}

		// Check if it's a ping packet (just a number)
		if pingID, err := strconv.Atoi(part); err == nil {
			// Ping packets are represented as special packet type "ping"
			packets = append(packets, Packet{
				Type: "ping",
				Data: []interface{}{pingID},
			})
			continue
		}

		// Try to parse as JSON packet
		var packet Packet
		if err := json.Unmarshal([]byte(part), &packet); err != nil {
			// Log warning for malformed packet but continue processing
			log.Printf("Warning: Skipping malformed packet at index %d: %v (data: %s)", i, err, truncate(part, 100))
			// Continue processing remaining packets instead of failing
			continue
		}

		packets = append(packets, packet)
	}

	return packets, nil
}

// truncate limits string length for logging
func truncate(s string, maxLen int) string {
	if len(s) <= maxLen {
		return s
	}
	return s[:maxLen] + "..."
}

// FormatWSPacket formats a packet into the TradingView WebSocket protocol format.
// Format: ~m~<length>~m~<JSON>
func FormatWSPacket(packet Packet) (string, error) {
	// Marshal packet to JSON
	jsonData, err := json.Marshal(packet)
	if err != nil {
		return "", fmt.Errorf("failed to marshal packet: %w", err)
	}

	// Calculate length and format message
	payload := string(jsonData)
	length := len(payload)
	message := fmt.Sprintf("~m~%d~m~%s", length, payload)

	return message, nil
}

// FormatPingPacket formats a ping packet.
// Ping packets are just numbers in the format: ~m~<length>~m~<number>
func FormatPingPacket(pingID int) string {
	payload := strconv.Itoa(pingID)
	length := len(payload)
	return fmt.Sprintf("~m~%d~m~%s", length, payload)
}

// FormatPongPacket formats a pong response to a ping.
// Pong responses use the format: ~m~<length>~m~~h~<pingID>
func FormatPongPacket(pingID int) string {
	payload := fmt.Sprintf("~h~%d", pingID)
	length := len(payload)
	return fmt.Sprintf("~m~%d~m~%s", length, payload)
}
