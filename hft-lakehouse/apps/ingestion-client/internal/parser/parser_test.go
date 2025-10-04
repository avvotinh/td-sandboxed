package parser

import (
	"encoding/json"
	"testing"
	"time"
)

func TestNewMessageParser(t *testing.T) {
	parser := NewMessageParser()
	if parser == nil {
		t.Fatal("NewMessageParser returned nil")
	}
}

func TestParseTickMessage_ValidMessage(t *testing.T) {
	tests := []struct {
		name     string
		message  string
		expected *TickData
	}{
		{
			name: "complete message with all fields",
			message: `{
				"symbol": "BTCUSD",
				"timestamp": 1696258800000,
				"bid": 45000.50,
				"ask": 45001.00,
				"price": 45000.75,
				"volume": 1.5
			}`,
			expected: &TickData{
				Symbol:    "BTCUSD",
				Timestamp: time.Unix(0, 1696258800000*int64(time.Millisecond)),
				Bid:       45000.50,
				Ask:       45001.00,
				Price:     45000.75,
				Volume:    1.5,
			},
		},
		{
			name: "message without optional fields",
			message: `{
				"symbol": "ETHUSD",
				"timestamp": 1696258800000,
				"bid": 2500.10,
				"ask": 2500.20
			}`,
			expected: &TickData{
				Symbol:    "ETHUSD",
				Timestamp: time.Unix(0, 1696258800000*int64(time.Millisecond)),
				Bid:       2500.10,
				Ask:       2500.20,
				Price:     0,
				Volume:    0,
			},
		},
		{
			name: "message with nested data object",
			message: `{
				"m": "quote_data",
				"data": {
					"symbol": "BTCUSD",
					"timestamp": 1696258800000,
					"bid": 45000.50,
					"ask": 45001.00,
					"price": 45000.75,
					"volume": 2.5
				}
			}`,
			expected: &TickData{
				Symbol:    "BTCUSD",
				Timestamp: time.Unix(0, 1696258800000*int64(time.Millisecond)),
				Bid:       45000.50,
				Ask:       45001.00,
				Price:     45000.75,
				Volume:    2.5,
			},
		},
	}

	parser := NewMessageParser()

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tick, err := parser.ParseTickMessage([]byte(tt.message))
			if err != nil {
				t.Fatalf("ParseTickMessage failed: %v", err)
			}

			if tick.Symbol != tt.expected.Symbol {
				t.Errorf("Symbol = %v, want %v", tick.Symbol, tt.expected.Symbol)
			}
			if !tick.Timestamp.Equal(tt.expected.Timestamp) {
				t.Errorf("Timestamp = %v, want %v", tick.Timestamp, tt.expected.Timestamp)
			}
			if tick.Bid != tt.expected.Bid {
				t.Errorf("Bid = %v, want %v", tick.Bid, tt.expected.Bid)
			}
			if tick.Ask != tt.expected.Ask {
				t.Errorf("Ask = %v, want %v", tick.Ask, tt.expected.Ask)
			}
			if tick.Price != tt.expected.Price {
				t.Errorf("Price = %v, want %v", tick.Price, tt.expected.Price)
			}
			if tick.Volume != tt.expected.Volume {
				t.Errorf("Volume = %v, want %v", tick.Volume, tt.expected.Volume)
			}
		})
	}
}

func TestParseTickMessage_InvalidMessages(t *testing.T) {
	tests := []struct {
		name        string
		message     string
		expectedErr string
	}{
		{
			name:        "empty message",
			message:     "",
			expectedErr: "empty message",
		},
		{
			name:        "invalid JSON",
			message:     `{invalid json}`,
			expectedErr: "failed to parse JSON",
		},
		{
			name: "missing symbol",
			message: `{
				"timestamp": 1696258800000,
				"bid": 45000.50,
				"ask": 45001.00
			}`,
			expectedErr: "missing required field: symbol",
		},
		{
			name: "missing timestamp",
			message: `{
				"symbol": "BTCUSD",
				"bid": 45000.50,
				"ask": 45001.00
			}`,
			expectedErr: "missing required field: timestamp",
		},
		{
			name: "missing bid",
			message: `{
				"symbol": "BTCUSD",
				"timestamp": 1696258800000,
				"ask": 45001.00
			}`,
			expectedErr: "missing required field: bid",
		},
		{
			name: "missing ask",
			message: `{
				"symbol": "BTCUSD",
				"timestamp": 1696258800000,
				"bid": 45000.50
			}`,
			expectedErr: "missing required field: ask",
		},
	}

	parser := NewMessageParser()

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			tick, err := parser.ParseTickMessage([]byte(tt.message))
			if err == nil {
				t.Fatalf("ParseTickMessage should have failed, got tick: %+v", tick)
			}
			if tt.expectedErr != "" && err.Error()[:len(tt.expectedErr)] != tt.expectedErr {
				t.Errorf("Expected error containing %q, got %q", tt.expectedErr, err.Error())
			}
		})
	}
}

func TestTickData_JSONMarshaling(t *testing.T) {
	original := &TickData{
		Symbol:    "BTCUSD",
		Timestamp: time.Unix(0, 1696258800000*int64(time.Millisecond)),
		Bid:       45000.50,
		Ask:       45001.00,
		Price:     45000.75,
		Volume:    1.5,
	}

	// Marshal to JSON
	jsonData, err := json.Marshal(original)
	if err != nil {
		t.Fatalf("Failed to marshal TickData: %v", err)
	}

	// Unmarshal back
	var restored TickData
	if err := json.Unmarshal(jsonData, &restored); err != nil {
		t.Fatalf("Failed to unmarshal TickData: %v", err)
	}

	// Compare
	if restored.Symbol != original.Symbol {
		t.Errorf("Symbol mismatch after JSON round-trip")
	}
	if !restored.Timestamp.Equal(original.Timestamp) {
		t.Errorf("Timestamp mismatch after JSON round-trip")
	}
	if restored.Bid != original.Bid {
		t.Errorf("Bid mismatch after JSON round-trip")
	}
	if restored.Ask != original.Ask {
		t.Errorf("Ask mismatch after JSON round-trip")
	}
	if restored.Price != original.Price {
		t.Errorf("Price mismatch after JSON round-trip")
	}
	if restored.Volume != original.Volume {
		t.Errorf("Volume mismatch after JSON round-trip")
	}
}
