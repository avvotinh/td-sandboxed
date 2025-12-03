// Package tradingview provides a Go client for accessing TradingView's real-time market data via WebSocket.
//
// This package enables Go applications to connect to TradingView's data feeds and subscribe to:
//   - Real-time price quotes for market symbols
//   - Historical OHLCV (Open, High, Low, Close, Volume) chart data
//   - Market information and metadata
//
// # Authentication
//
// To use this package, you need TradingView session credentials from your browser cookies:
//
//  1. Log in to tradingview.com in your browser
//
//  2. Open Developer Tools (F12) > Application/Storage > Cookies
//
//  3. Copy the values of 'sessionid' and 'sessionid_sign'
//
//  4. Set them as environment variables:
//
//     SESSION_ID=your_session_id_here
//     SESSION_SIGN=your_session_signature_here
//
// You can also create a .env file in your application directory with these values.
//
// # Quick Start
//
// Basic example for real-time quotes:
//
//	client, err := tradingview.NewClient(&tradingview.ClientConfig{})
//	if err != nil {
//		log.Fatal(err)
//	}
//
//	if err := client.Connect(context.Background()); err != nil {
//		log.Fatal(err)
//	}
//	defer client.Close()
//
//	// Create quote session
//	session := client.NewQuoteSession(nil)
//
//	// Subscribe to symbol
//	market, err := session.NewMarket("BINANCE:BTCUSDT")
//	if err != nil {
//		log.Fatal(err)
//	}
//
//	// Handle price updates
//	market.OnData(func(data map[string]interface{}) {
//		fmt.Printf("Price update: %+v\n", data)
//	})
//
//	// Keep running
//	select {}
//
// # Historical Chart Data
//
// Example for retrieving historical OHLCV data:
//
//	client, err := tradingview.NewClient(&tradingview.ClientConfig{})
//	if err != nil {
//		log.Fatal(err)
//	}
//
//	if err := client.Connect(context.Background()); err != nil {
//		log.Fatal(err)
//	}
//	defer client.Close()
//
//	// Create chart session
//	chart := client.NewChartSession()
//
//	// Set market and timeframe
//	err = chart.SetMarket("BINANCE:ETHUSDT", &tradingview.ChartSessionOptions{
//		Timeframe: "1D",
//		Range:     100,
//	})
//	if err != nil {
//		log.Fatal(err)
//	}
//
//	// Handle chart updates
//	chart.OnUpdate(func(periods []*tradingview.Period) {
//		fmt.Printf("Received %d periods\n", len(periods))
//		if len(periods) > 0 {
//			latest := periods[0]
//			fmt.Printf("Latest: O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f\n",
//				latest.Open, latest.High, latest.Low, latest.Close, latest.Volume)
//		}
//	})
//
//	// Keep running
//	select {}
//
// # Symbol Format
//
// Symbols should be specified in the format "EXCHANGE:SYMBOL":
//   - "BINANCE:BTCUSDT" - Bitcoin/USDT on Binance
//   - "NASDAQ:AAPL" - Apple stock on NASDAQ
//   - "COINBASE:ETHUSD" - Ethereum/USD on Coinbase
//
// # Timeframes
//
// Supported timeframes for chart data:
//   - Second intervals: "1S", "5S", "10S", "15S", "30S"
//   - Minute intervals: "1", "3", "5", "15", "30", "45", "60", "120", "180", "240"
//   - Day/Week/Month: "1D", "1W", "1M"
//
// Use the TimeFrame constants for type safety (e.g., tradingview.TimeFrame1D).
//
// # Error Handling
//
// All errors returned by this package implement the error interface and can be type-asserted
// to *TradingViewError for more details:
//
//	if err != nil {
//		if tvErr, ok := err.(*tradingview.TradingViewError); ok {
//			switch tvErr.Type {
//			case tradingview.ErrAuth:
//				// Handle authentication error
//			case tradingview.ErrConnection:
//				// Handle connection error
//			case tradingview.ErrProtocol:
//				// Handle protocol error
//			case tradingview.ErrSession:
//				// Handle session error
//			}
//		}
//	}
//
// # Thread Safety
//
// The Client and all session types are safe for concurrent use. Multiple goroutines
// can safely subscribe to different symbols, register callbacks, and receive updates
// simultaneously.
//
// # Resource Cleanup
//
// Always call Close() on the client when done to ensure proper cleanup of WebSocket
// connections and goroutines:
//
//	defer client.Close()
//
// Similarly, delete sessions when no longer needed:
//
//	defer session.Delete()
package tradingview
