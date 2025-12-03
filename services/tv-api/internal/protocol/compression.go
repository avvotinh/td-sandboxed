package protocol

import (
	"bytes"
	"compress/gzip"
	"fmt"
	"io"
)

// ParseCompressed decompresses ZIP/GZIP compressed data from TradingView.
// Some packets may contain compressed data that needs to be decompressed
// before parsing.
func ParseCompressed(data []byte) ([]byte, error) {
	if len(data) == 0 {
		return nil, fmt.Errorf("empty compressed data")
	}

	// Create a gzip reader
	reader, err := gzip.NewReader(bytes.NewReader(data))
	if err != nil {
		return nil, fmt.Errorf("failed to create gzip reader: %w", err)
	}
	defer reader.Close()

	// Read all decompressed data
	decompressed, err := io.ReadAll(reader)
	if err != nil {
		return nil, fmt.Errorf("failed to decompress data: %w", err)
	}

	return decompressed, nil
}
