package protocol

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestParseWSPacket(t *testing.T) {
	tests := []struct {
		name        string
		input       string
		expected    []Packet
		wantErr     bool
		errContains string
	}{
		{
			name:  "single packet",
			input: `~m~52~m~{"m":"quote_completed","p":["qs_ABC123","symbol1"]}`,
			expected: []Packet{
				{
					Type: "quote_completed",
					Data: []interface{}{"qs_ABC123", "symbol1"},
				},
			},
			wantErr: false,
		},
		{
			name:  "concatenated packets",
			input: `~m~30~m~{"m":"packet1","p":["a"]}~m~30~m~{"m":"packet2","p":["b"]}`,
			expected: []Packet{
				{
					Type: "packet1",
					Data: []interface{}{"a"},
				},
				{
					Type: "packet2",
					Data: []interface{}{"b"},
				},
			},
			wantErr: false,
		},
		{
			name:     "ping packet only",
			input:    `~m~3~m~123`,
			expected: []Packet{},
			wantErr:  false,
		},
		{
			name:     "ping with heartbeat marker",
			input:    `~h~123`,
			expected: []Packet{},
			wantErr:  false,
		},
		{
			name:  "packet with heartbeat marker",
			input: `~h~123~m~30~m~{"m":"test","p":["data"]}`,
			expected: []Packet{
				{
					Type: "test",
					Data: []interface{}{"data"},
				},
			},
			wantErr: false,
		},
		{
			name:        "malformed JSON",
			input:       `~m~15~m~{invalid json}`,
			expected:    nil,
			wantErr:     true,
			errContains: "failed to parse packet JSON",
		},
		{
			name:        "empty message",
			input:       "",
			expected:    nil,
			wantErr:     true,
			errContains: "empty message",
		},
		{
			name:  "packet without data field",
			input: `~m~15~m~{"m":"test"}`,
			expected: []Packet{
				{
					Type: "test",
					Data: nil,
				},
			},
			wantErr: false,
		},
		{
			name:  "packet with complex data",
			input: `~m~80~m~{"m":"qsd","p":["qs_1",{"n":"BTCUSDT","s":"ok","v":{"lp":50000.5,"volume":1234}}]}`,
			expected: []Packet{
				{
					Type: "qsd",
					Data: []interface{}{
						"qs_1",
						map[string]interface{}{
							"n": "BTCUSDT",
							"s": "ok",
							"v": map[string]interface{}{
								"lp":     float64(50000.5),
								"volume": float64(1234),
							},
						},
					},
				},
			},
			wantErr: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			packets, err := ParseWSPacket(tt.input)

			if tt.wantErr {
				require.Error(t, err)
				if tt.errContains != "" {
					assert.Contains(t, err.Error(), tt.errContains)
				}
				return
			}

			require.NoError(t, err)
			assert.Equal(t, len(tt.expected), len(packets))

			for i, expected := range tt.expected {
				assert.Equal(t, expected.Type, packets[i].Type)
				assert.Equal(t, expected.Data, packets[i].Data)
			}
		})
	}
}

func TestFormatWSPacket(t *testing.T) {
	tests := []struct {
		name     string
		packet   Packet
		expected string
		wantErr  bool
	}{
		{
			name: "simple packet",
			packet: Packet{
				Type: "test",
				Data: []interface{}{"data"},
			},
			expected: `~m~25~m~{"m":"test","p":["data"]}`,
			wantErr:  false,
		},
		{
			name: "packet with multiple parameters",
			packet: Packet{
				Type: "quote_add_symbols",
				Data: []interface{}{"qs_123", "symbol_key", "BINANCE:BTCUSDT"},
			},
			expected: `~m~71~m~{"m":"quote_add_symbols","p":["qs_123","symbol_key","BINANCE:BTCUSDT"]}`,
			wantErr:  false,
		},
		{
			name: "packet with no data",
			packet: Packet{
				Type: "test",
				Data: nil,
			},
			expected: `~m~12~m~{"m":"test"}`,
			wantErr:  false,
		},
		{
			name: "packet with empty data array",
			packet: Packet{
				Type: "test",
				Data: []interface{}{},
			},
			expected: `~m~12~m~{"m":"test"}`,
			wantErr:  false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result, err := FormatWSPacket(tt.packet)

			if tt.wantErr {
				require.Error(t, err)
				return
			}

			require.NoError(t, err)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestFormatPingPacket(t *testing.T) {
	tests := []struct {
		name     string
		pingID   int
		expected string
	}{
		{
			name:     "small ping ID",
			pingID:   1,
			expected: "~m~1~m~1",
		},
		{
			name:     "medium ping ID",
			pingID:   123,
			expected: "~m~3~m~123",
		},
		{
			name:     "large ping ID",
			pingID:   123456,
			expected: "~m~6~m~123456",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := FormatPingPacket(tt.pingID)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestParseAndFormatRoundTrip(t *testing.T) {
	// Test that formatting and then parsing returns the same packet
	original := Packet{
		Type: "test_packet",
		Data: []interface{}{"param1", "param2", float64(123)},
	}

	// Format the packet
	formatted, err := FormatWSPacket(original)
	require.NoError(t, err)

	// Parse it back
	packets, err := ParseWSPacket(formatted)
	require.NoError(t, err)
	require.Len(t, packets, 1)

	// Compare
	assert.Equal(t, original.Type, packets[0].Type)
	assert.Equal(t, original.Data, packets[0].Data)
}
