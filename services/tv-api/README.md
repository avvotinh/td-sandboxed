# TradingView Go API

A Go library for accessing TradingView's real-time market data via WebSocket connections. This is a port of the JavaScript TradingView API library, providing real-time quotes and historical chart data.

## Features

- **Real-time Quote Data**: Subscribe to live price updates for any symbol
- **Historical Chart Data**: Retrieve OHLCV (Open, High, Low, Close, Volume) data with configurable timeframes
- **Session-based Authentication**: Use browser session cookies for authenticated access
- **Event-driven Architecture**: Built with Go channels and callbacks for reactive programming
- **Thread-safe**: Concurrent session management with proper synchronization
- **Comprehensive Testing**: Unit and integration tests with 80%+ coverage

## Installation

### As a Library

```bash
go get github.com/avvotinh/tv-api
```

### As a CLI Tool

```bash
go install github.com/avvotinh/tv-api/cmd/tv-cli@latest
```

## Quick Start

### Prerequisites

You'll need TradingView session credentials from your browser cookies:
1. Log in to [tradingview.com](https://tradingview.com)
2. Open browser Developer Tools (F12) → Application/Storage → Cookies → https://tradingview.com
3. Copy the values of `sessionid` and `sessionid_sign` cookies
4. Set them as environment variables or create a `.env` file:

```bash
# .env file
SESSION_ID=your_session_id_here
SESSION_SIGN=your_session_signature_here
```

You can also use `configs/.env.sample` as a template.

### Example: Real-time Quotes

```go
package main

import (
    "context"
    "fmt"
    "log"

    "github.com/avvotinh/tv-api/pkg/tradingview"
)

func main() {
    // Create client (loads credentials from environment)
    client, err := tradingview.NewClient(&tradingview.ClientConfig{})
    if err != nil {
        log.Fatal(err)
    }

    // Connect to TradingView
    if err := client.Connect(context.Background()); err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    // Create quote session
    quoteSession := client.NewQuoteSession(nil)
    defer quoteSession.Delete()

    // Subscribe to symbol
    market, err := quoteSession.NewMarket("BINANCE:BTCUSDT")
    if err != nil {
        log.Fatal(err)
    }
    defer market.Close()

    // Handle price updates
    market.OnData(func(data map[string]interface{}) {
        fmt.Printf("Price update: %+v\n", data)
    })

    // Keep running
    select {}
}
```

See [examples/simple-quote.go](examples/simple-quote.go) for a complete example.

### Example: Historical Chart Data

```go
package main

import (
    "context"
    "fmt"
    "log"

    "github.com/avvotinh/tv-api/pkg/tradingview"
)

func main() {
    // Create client (loads credentials from environment)
    client, err := tradingview.NewClient(&tradingview.ClientConfig{})
    if err != nil {
        log.Fatal(err)
    }

    // Connect to TradingView
    if err := client.Connect(context.Background()); err != nil {
        log.Fatal(err)
    }
    defer client.Close()

    // Create chart session
    chart := client.NewChartSession()
    defer chart.Delete()

    // Set market and timeframe
    err = chart.SetMarket("BINANCE:ETHUSDT", &tradingview.ChartSessionOptions{
        Timeframe: "1D",
        Range:     100,
    })
    if err != nil {
        log.Fatal(err)
    }

    // Handle chart updates
    chart.OnUpdate(func(periods []*tradingview.Period) {
        fmt.Printf("Received %d periods\n", len(periods))
        if len(periods) > 0 {
            latest := periods[0]
            fmt.Printf("Latest: O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f\n",
                latest.Open, latest.High, latest.Low, latest.Close, latest.Volume)
        }
    })

    // Keep running
    select {}
}
```

See [examples/simple-chart.go](examples/simple-chart.go) for a complete example.

## CLI Usage

The package includes a command-line tool for testing and demonstration:

```bash
# Get real-time quotes
tv-cli -command quote -symbol BINANCE:BTCUSDT

# Get historical chart data
tv-cli -command chart -symbol BINANCE:ETHUSDT -timeframe 1D -range 100

# JSON output format
tv-cli -command quote -symbol NASDAQ:AAPL -format

# Specify custom quote fields
tv-cli -command quote -symbol BINANCE:BTCUSDT -fields "lp,volume,bid,ask"

# Show help
tv-cli -help
```

### CLI Options

- `-command`: Command to run (`quote` or `chart`, default: `quote`)
- `-symbol`: Symbol to subscribe to (default: `BINANCE:BTCUSDT`)
- `-timeframe`: Chart timeframe for chart command (default: `1D`)
- `-range`: Number of bars to retrieve for chart (default: `100`)
- `-format`: Output in JSON format (flag, default: false)
- `-fields`: Comma-separated list of quote fields (default: all fields)
- `-help`: Show help documentation

## API Reference

### Client

#### Creating a Client

```go
client, err := tradingview.NewClient(&tradingview.ClientConfig{
    Server:      tradingview.DefaultServer,  // Optional: custom WebSocket server
    Location:    tradingview.DefaultLocation, // Optional: location parameter
    Debug:       false,                       // Optional: enable debug logging
    SessionID:   "",                          // Optional: override SESSION_ID env var
    SessionSign: "",                          // Optional: override SESSION_SIGN env var
})
```

#### Client Methods

- `Connect(ctx context.Context) error` - Connect to TradingView and authenticate
- `Close() error` - Close the connection and cleanup resources
- `NewQuoteSession(options *QuoteSessionOptions) *QuoteSession` - Create a quote session
- `NewChartSession() *ChartSession` - Create a chart session
- `IsConnected() bool` - Check if WebSocket is connected
- `IsLogged() bool` - Check if client is authenticated

#### Client Events

```go
client.OnConnected(func() { ... })
client.OnDisconnected(func() { ... })
client.OnLogged(func(user *User) { ... })
client.OnPing(func() { ... })
client.OnError(func(err error) { ... })
```

### Quote Session

#### Creating Markets

```go
session := client.NewQuoteSession(&tradingview.QuoteSessionOptions{
    Fields: []string{"lp", "volume", "bid", "ask"},  // Optional: specific fields
})

market, err := session.NewMarket("BINANCE:BTCUSDT")
```

#### Market Methods

- `Symbol() string` - Get the market symbol
- `LastData() map[string]interface{}` - Get the last received quote data
- `Close() error` - Close the market subscription

#### Market Events

```go
market.OnLoaded(func() { ... })
market.OnData(func(data map[string]interface{}) { ... })
market.OnError(func(err error) { ... })
```

#### Common Quote Fields

- `lp` - Last price
- `volume` - Volume
- `bid` - Bid price
- `ask` - Ask price
- `high_price` - High price
- `low_price` - Low price
- `open_price` - Open price
- `prev_close_price` - Previous close
- `ch` - Change
- `chp` - Change percent

### Chart Session

#### Loading Chart Data

```go
chart := client.NewChartSession()

err := chart.SetMarket("BINANCE:ETHUSDT", &tradingview.ChartSessionOptions{
    Timeframe:  "1D",      // Timeframe (e.g., "1", "5", "60", "1D", "1W")
    Range:      100,       // Number of bars
    Adjustment: "splits",  // Price adjustment
    Session:    "regular", // Trading session
    Currency:   "USD",     // Currency conversion
})
```

#### Chart Methods

- `Periods() []*Period` - Get all periods sorted by time descending
- `Infos() *MarketInfo` - Get market information
- `SetSeries(timeframe string, rangeCount int) error` - Change timeframe
- `FetchMore(count int) error` - Fetch more historical data
- `SetTimezone(timezone string) error` - Change timezone
- `Delete() error` - Delete the chart session

#### Chart Events

```go
chart.OnSymbolLoaded(func(info *MarketInfo) { ... })
chart.OnUpdate(func(periods []*Period) { ... })
chart.OnError(func(err error) { ... })
```

#### Timeframes

Use the predefined constants for type safety:

```go
tradingview.TimeFrame1    // 1 minute
tradingview.TimeFrame5    // 5 minutes
tradingview.TimeFrame15   // 15 minutes
tradingview.TimeFrame60   // 1 hour
tradingview.TimeFrame1D   // 1 day
tradingview.TimeFrame1W   // 1 week
tradingview.TimeFrame1M   // 1 month
```

### Types

#### Period

```go
type Period struct {
    Time   int64   // Unix timestamp
    Open   float64 // Opening price
    Close  float64 // Closing price
    High   float64 // Highest price
    Low    float64 // Lowest price
    Volume float64 // Trading volume
}
```

#### MarketInfo

```go
type MarketInfo struct {
    Symbol      string
    Exchange    string
    Description string
    Type        string
    Currency    string
    Timezone    string
    Session     string
    // ... and more fields
}
```

### Error Handling

```go
if err != nil {
    if tvErr, ok := err.(*tradingview.TradingViewError); ok {
        switch tvErr.Type {
        case tradingview.ErrAuth:
            // Authentication error
        case tradingview.ErrConnection:
            // Connection error
        case tradingview.ErrProtocol:
            // Protocol/parsing error
        case tradingview.ErrSession:
            // Session management error
        }
    }
}
```

## Development

### Running Tests

```bash
# Run all tests
./scripts/test.sh

# Run specific package tests
go test ./pkg/tradingview/...

# Run with race detector
go test -race ./...
```

### Linting

```bash
# Run all linters
./scripts/lint.sh

# Individual tools
gofmt -l -w .
go vet ./...
golint ./...
gosec ./...
```

## Project Structure

```
.
├── cmd/
│   └── tv-cli/          # CLI application
├── pkg/
│   └── tradingview/     # Public API (importable)
├── internal/
│   ├── protocol/        # WebSocket packet parsing
│   ├── session/         # Session management
│   ├── auth/            # Authentication
│   └── transport/       # WebSocket transport
├── tests/
│   ├── integration/     # Integration tests
│   └── mocks/           # Test mocks
├── configs/
│   └── .env.sample      # Example configuration
└── scripts/             # Development scripts
```

## Architecture

The library follows clean architecture principles:

- **pkg/tradingview**: Public API surface, importable by external projects
- **internal/**: Private implementation details
  - **protocol**: Custom TradingView packet parsing
  - **session**: Quote and chart session management
  - **auth**: Browser cookie authentication
  - **transport**: WebSocket connection handling

## Authentication

This library uses session-based authentication via browser cookies:

1. Log in to TradingView in your browser
2. Extract `sessionid` and `sessionid_sign` cookies
3. Provide via `.env` file or environment variables
4. The library automatically retrieves an auth token

**Note**: Credentials expire periodically and need to be refreshed manually.

## Contributing

Contributions are welcome! Please follow these guidelines:

1. Run tests and linters before submitting
2. Follow Go best practices (gofmt, golint)
3. Add tests for new features
4. Update documentation as needed

## License

MIT License - see LICENSE file for details

## Acknowledgments

- Based on the JavaScript TradingView API library
- Uses [gorilla/websocket](https://github.com/gorilla/websocket) for WebSocket connections

## Disclaimer

This is an unofficial library and is not affiliated with TradingView. Use at your own risk and comply with TradingView's Terms of Service.
