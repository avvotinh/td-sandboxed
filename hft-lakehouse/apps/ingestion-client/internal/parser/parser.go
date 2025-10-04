package parser

import (
	"encoding/json"
	"fmt"
	"time"
)

// TickData represents a single tick of market data
// Follows Data Model specification from docs/architecture/phn-4-m-hnh-d-liu-data-models.md
type TickData struct {
	Timestamp time.Time `json:"timestamp"` // Thời gian chính xác của tick
	Symbol    string    `json:"symbol"`    // Mã giao dịch (e.g., 'BTCUSD')
	Bid       float64   `json:"bid"`       // Giá mua tốt nhất
	Ask       float64   `json:"ask"`       // Giá bán tốt nhất
	Price     float64   `json:"price"`     // Giá khớp lệnh cuối cùng (optional)
	Volume    float64   `json:"volume"`    // Khối lượng giao dịch (optional)
}

// MessageParser handles parsing of TradingView WebSocket messages
type MessageParser struct{}

// NewMessageParser creates a new message parser instance
func NewMessageParser() *MessageParser {
	return &MessageParser{}
}

// tradingViewMessage represents the expected structure from TradingView WebSocket
// Note: Actual format may vary - this is a baseline structure to be adjusted based on real messages
type tradingViewMessage struct {
	Type      string                 `json:"m"` // Message type
	Payload   []interface{}          `json:"p"` // Payload array
	Data      map[string]interface{} `json:"data,omitempty"`
	Symbol    string                 `json:"symbol,omitempty"`
	Timestamp int64                  `json:"timestamp,omitempty"`
	Bid       float64                `json:"bid,omitempty"`
	Ask       float64                `json:"ask,omitempty"`
	Price     float64                `json:"price,omitempty"`
	Volume    float64                `json:"volume,omitempty"`
}

// ParseTickMessage parses a raw WebSocket message into TickData
// Follows Coding Standard Rule #5: Uses context for I/O operations (via caller)
func (p *MessageParser) ParseTickMessage(message []byte) (*TickData, error) {
	if len(message) == 0 {
		return nil, fmt.Errorf("empty message")
	}

	var tvMsg tradingViewMessage
	if err := json.Unmarshal(message, &tvMsg); err != nil {
		return nil, fmt.Errorf("failed to parse JSON: %w", err)
	}

	// Extract tick data from the parsed message
	// This handles multiple possible message formats from TradingView
	tick := &TickData{}

	// Try to extract symbol (required field)
	if tvMsg.Symbol != "" {
		tick.Symbol = tvMsg.Symbol
	} else if tvMsg.Data != nil {
		if symbol, ok := tvMsg.Data["symbol"].(string); ok {
			tick.Symbol = symbol
		}
	}

	if tick.Symbol == "" {
		return nil, fmt.Errorf("missing required field: symbol")
	}

	// Extract timestamp (required field)
	if tvMsg.Timestamp > 0 {
		tick.Timestamp = time.Unix(0, tvMsg.Timestamp*int64(time.Millisecond))
	} else if tvMsg.Data != nil {
		if ts, ok := tvMsg.Data["timestamp"].(float64); ok {
			tick.Timestamp = time.Unix(0, int64(ts)*int64(time.Millisecond))
		}
	}

	if tick.Timestamp.IsZero() {
		return nil, fmt.Errorf("missing required field: timestamp")
	}

	// Extract bid (required field)
	if tvMsg.Bid > 0 {
		tick.Bid = tvMsg.Bid
	} else if tvMsg.Data != nil {
		if bid, ok := tvMsg.Data["bid"].(float64); ok {
			tick.Bid = bid
		}
	}

	if tick.Bid == 0 {
		return nil, fmt.Errorf("missing required field: bid")
	}

	// Extract ask (required field)
	if tvMsg.Ask > 0 {
		tick.Ask = tvMsg.Ask
	} else if tvMsg.Data != nil {
		if ask, ok := tvMsg.Data["ask"].(float64); ok {
			tick.Ask = ask
		}
	}

	if tick.Ask == 0 {
		return nil, fmt.Errorf("missing required field: ask")
	}

	// Extract price (optional)
	if tvMsg.Price > 0 {
		tick.Price = tvMsg.Price
	} else if tvMsg.Data != nil {
		if price, ok := tvMsg.Data["price"].(float64); ok {
			tick.Price = price
		}
	}

	// Extract volume (optional)
	if tvMsg.Volume > 0 {
		tick.Volume = tvMsg.Volume
	} else if tvMsg.Data != nil {
		if volume, ok := tvMsg.Data["volume"].(float64); ok {
			tick.Volume = volume
		}
	}

	return tick, nil
}
