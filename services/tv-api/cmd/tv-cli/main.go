package main

import (
	"context"
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"os/signal"
	"strings"
	"syscall"
	"time"

	"github.com/avvotinh/tv-api/pkg/tradingview"
)

const (
	exitSuccess = 0
	exitError   = 1
)

var (
	// Command flags
	command    = flag.String("command", "chart", "Command to run: quote, chart, backtest-fetch")
	symbol     = flag.String("symbol", "OANDA:XAUUSD", "Symbol to subscribe to (e.g., OANDA:XAUUSD)")
	timeframe  = flag.String("timeframe", "1", "Chart timeframe (e.g., 1, 5, 15, 60, 1D, 1W)")
	rangeCount = flag.Int("range", 100, "Number of bars to retrieve for chart")
	formatJSON = flag.Bool("format", false, "Output in JSON format")
	fields     = flag.String("fields", "", "Comma-separated list of quote fields (default: all)")
	help       = flag.Bool("help", false, "Show help documentation")

	// backtest-fetch command flags (only consumed when -command=backtest-fetch).
	// Kept in the global flag set rather than a sub-FlagSet so the existing
	// chart/quote commands continue to work unchanged and -help shows
	// every option in one place.
	bfFrom           = flag.String("from", "", "[backtest-fetch] start timestamp RFC3339 (e.g., 2024-01-01T00:00:00Z)")
	bfTo             = flag.String("to", "", "[backtest-fetch] end timestamp RFC3339 (e.g., 2026-04-30T23:59:59Z)")
	bfOut            = flag.String("out", "", "[backtest-fetch] Parquet output path (manifest sidecar lands at <out>.manifest.json)")
	bfSpecName       = flag.String("spec-name", "xauusd-validation", "[backtest-fetch] manifest spec_name")
	bfDatasetVersion = flag.String("dataset-version", "v1", "[backtest-fetch] manifest dataset_version")
	bfWindowName     = flag.String("window-name", "in_sample", "[backtest-fetch] manifest window_name")
	bfWindowKind     = flag.String("window-kind", "in_sample", "[backtest-fetch] manifest window_kind (in_sample|oos_reserve)")
	bfThrottleMs     = flag.Int("throttle-ms", 150, "[backtest-fetch] delay (ms) between request_more_data calls")
	bfBatchSize      = flag.Int("batch-size", 1000, "[backtest-fetch] bars per request_more_data call")
	bfMaxGapHours    = flag.Float64("max-gap-hours", 48.0, "[backtest-fetch] gap threshold (hours) before flagging in manifest")
	bfMaxBatches     = flag.Int("max-batches", 1000, "[backtest-fetch] safety cap on FetchUntil iterations")
)

func main() {
	flag.Parse()

	// Show help if requested
	if *help {
		showHelp()
		os.Exit(exitSuccess)
	}

	// Validate command
	if *command != "quote" && *command != "chart" && *command != "backtest-fetch" {
		fmt.Fprintf(os.Stderr, "Error: Invalid command '%s'. Use 'quote', 'chart', or 'backtest-fetch'\n", *command)
		os.Exit(exitError)
	}

	// Run the command
	if err := run(*command); err != nil {
		fmt.Fprintf(os.Stderr, "Error: %v\n", err)
		os.Exit(exitError)
	}

	os.Exit(exitSuccess)
}

func run(cmd string) error {
	// Create context with cancellation
	ctx, cancel := context.WithCancel(context.Background())
	defer cancel()

	// Handle interrupt signals
	sigChan := make(chan os.Signal, 1)
	signal.Notify(sigChan, os.Interrupt, syscall.SIGTERM)
	go func() {
		<-sigChan
		fmt.Println("\nReceived interrupt signal, shutting down...")
		cancel()
	}()

	// Create client
	client, err := tradingview.NewClient(&tradingview.ClientConfig{
		Debug: false,
	})
	if err != nil {
		return fmt.Errorf("failed to create client: %w", err)
	}

	// Connect to TradingView
	if err := client.Connect(ctx); err != nil {
		return fmt.Errorf("failed to connect: %w", err)
	}
	defer client.Close()

	// Wait for authentication
	time.Sleep(2 * time.Second)

	// Execute command
	switch cmd {
	case "quote":
		return runQuote(ctx, client)
	case "chart":
		return runChart(ctx, client)
	case "backtest-fetch":
		return runBacktestFetch(ctx, client)
	default:
		return fmt.Errorf("unknown command: %s", cmd)
	}
}

func runQuote(ctx context.Context, client *tradingview.Client) error {
	// Parse fields if provided
	var fieldList []string
	if *fields != "" {
		fieldList = strings.Split(*fields, ",")
		for i, f := range fieldList {
			fieldList[i] = strings.TrimSpace(f)
		}
	}

	// Create quote session
	session := client.NewQuoteSession(&tradingview.QuoteSessionOptions{
		Fields: fieldList,
	})

	// Subscribe to symbol
	market, err := session.NewMarket(*symbol)
	if err != nil {
		return fmt.Errorf("failed to create market: %w", err)
	}

	// Set up data handler
	dataChan := make(chan map[string]interface{}, 10)
	market.OnData(func(data map[string]interface{}) {
		dataChan <- data
	})

	// Set up error handler
	errorChan := make(chan error, 1)
	market.OnError(func(err error) {
		errorChan <- err
	})

	if !*formatJSON {
		fmt.Printf("Subscribed to %s\n", *symbol)
		fmt.Println("Waiting for price updates... (Press Ctrl+C to exit)")
		fmt.Println()
	}

	// Wait for data or context cancellation
	for {
		select {
		case <-ctx.Done():
			if !*formatJSON {
				fmt.Println("\nClosing session...")
			}
			session.Delete()
			return nil

		case data := <-dataChan:
			if *formatJSON {
				output := map[string]interface{}{
					"symbol": *symbol,
					"time":   time.Now().Unix(),
					"data":   data,
				}
				jsonData, err := json.MarshalIndent(output, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal JSON: %w", err)
				}
				fmt.Println(string(jsonData))
			} else {
				fmt.Printf("[%s] %s:\n", time.Now().Format("15:04:05"), *symbol)
				for k, v := range data {
					fmt.Printf("  %s: %v\n", k, v)
				}
				fmt.Println()
			}

		case err := <-errorChan:
			return fmt.Errorf("market error: %w", err)
		}
	}
}

func runChart(ctx context.Context, client *tradingview.Client) error {
	// Track last displayed candle to avoid duplicate prints
	var lastDisplayedTime int64
	var lastDisplayedClose float64

	// Create chart session
	session := client.NewChartSession()

	// Set market with options
	if err := session.SetMarket(*symbol, &tradingview.ChartSessionOptions{
		Timeframe: *timeframe,
		Range:     *rangeCount,
	}); err != nil {
		return fmt.Errorf("failed to set market: %w", err)
	}

	// Set up update handler
	updateChan := make(chan bool, 10)
	session.OnUpdate(func(periods []*tradingview.Period) {
		updateChan <- true
	})

	// Set up error handler
	errorChan := make(chan error, 1)
	session.OnError(func(err error) {
		errorChan <- err
	})

	if !*formatJSON {
		fmt.Printf("Loading chart data for %s (timeframe: %s, bars: %d)\n", *symbol, *timeframe, *rangeCount)
		fmt.Println("Waiting for data... (Press Ctrl+C to exit)")
		fmt.Println()
	}

	// Wait for initial data with timeout
	timeout := time.After(10 * time.Second)
	dataReceived := false

	for !dataReceived {
		select {
		case <-ctx.Done():
			if !*formatJSON {
				fmt.Println("\nClosing session...")
			}
			session.Delete()
			return nil

		case <-updateChan:
			dataReceived = true
			periods := session.Periods()
			infos := session.Infos()

			if *formatJSON {
				output := map[string]interface{}{
					"symbol":    *symbol,
					"timeframe": *timeframe,
					"time":      time.Now().Unix(),
					"infos":     infos,
					"periods":   periods,
				}
				jsonData, err := json.MarshalIndent(output, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal JSON: %w", err)
				}
				fmt.Println(string(jsonData))
			} else {
				fmt.Printf("Market Info for %s:\n", *symbol)
				if infos != nil {
					fmt.Printf("  Exchange: %s\n", infos.Exchange)
					fmt.Printf("  Currency: %s\n", infos.Currency)
					fmt.Printf("  Timezone: %s\n", infos.Timezone)
					fmt.Printf("  Type: %s\n", infos.Type)
				}
				fmt.Println()

				fmt.Printf("Received %d periods:\n", len(periods))
				fmt.Println()
				fmt.Printf("%-20s %10s %10s %10s %10s %12s\n",
					"Time", "Open", "High", "Low", "Close", "Volume")
				fmt.Println(strings.Repeat("-", 80))

				// Show first 10 periods
				count := 10
				if len(periods) < count {
					count = len(periods)
				}
				for i := 0; i < count; i++ {
					p := periods[i]
					t := time.Unix(p.Time, 0)
					fmt.Printf("%-20s %10.2f %10.2f %10.2f %10.2f %12.0f\n",
						t.Format("2006-01-02 15:04"),
						p.Open, p.High, p.Low, p.Close, p.Volume)
				}

				if len(periods) > count {
					fmt.Printf("... and %d more periods\n", len(periods)-count)
				}
				fmt.Println()
				fmt.Println("Listening for real-time updates... (Press Ctrl+C to exit)")
			}

		case err := <-errorChan:
			return fmt.Errorf("chart error: %w", err)

		case <-timeout:
			return fmt.Errorf("timeout waiting for chart data")
		}
	}

	// Continue listening for updates
	for {
		select {
		case <-ctx.Done():
			if !*formatJSON {
				fmt.Println("\nClosing session...")
			}
			session.Delete()
			return nil

		case <-updateChan:
			periods := session.Periods()
			if *formatJSON {
				output := map[string]interface{}{
					"symbol":    *symbol,
					"timeframe": *timeframe,
					"time":      time.Now().Unix(),
					"update":    "realtime",
					"periods":   periods,
				}
				jsonData, err := json.MarshalIndent(output, "", "  ")
				if err != nil {
					return fmt.Errorf("failed to marshal JSON: %w", err)
				}
				fmt.Println(string(jsonData))
			} else {
				if len(periods) == 0 {
					continue
				}

				// Smart candle selection:
				// - If periods[0] looks like a newly opened candle (O=H=L=C or very small volume),
				//   display periods[1] (the just-closed candle)
				// - Otherwise, display periods[0] (the actively updating candle)
				var candleToDisplay *tradingview.Period

				if len(periods) > 1 {
					latest := periods[0]
					// Check if this is a newly opened candle with no price movement yet
					isNewCandle := (latest.Open == latest.High &&
						latest.Open == latest.Low &&
						latest.Open == latest.Close) ||
						latest.Volume < 2

					if isNewCandle {
						// Display the confirmed closed candle
						candleToDisplay = periods[1]
					} else {
						// Display the actively updating candle
						candleToDisplay = latest
					}
				} else {
					// Only one period, display it
					candleToDisplay = periods[0]
				}

				// Only print if this is a different candle or the close price has changed
				// This prevents spam from multiple du messages for the same candle state
				if candleToDisplay.Time != lastDisplayedTime ||
					candleToDisplay.Close != lastDisplayedClose {
					t := time.Unix(candleToDisplay.Time, 0)
					fmt.Printf("[%s] Update: O=%.2f H=%.2f L=%.2f C=%.2f V=%.0f\n",
						t.Format("15:04:05"),
						candleToDisplay.Open, candleToDisplay.High,
						candleToDisplay.Low, candleToDisplay.Close, candleToDisplay.Volume)

					lastDisplayedTime = candleToDisplay.Time
					lastDisplayedClose = candleToDisplay.Close
				}
			}

		case err := <-errorChan:
			return fmt.Errorf("chart error: %w", err)
		}
	}
}

func showHelp() {
	fmt.Println("TradingView CLI - Real-time market data from TradingView")
	fmt.Println()
	fmt.Println("USAGE:")
	fmt.Println("  tv-cli [options]")
	fmt.Println()
	fmt.Println("OPTIONS:")
	fmt.Println("  -command string")
	fmt.Println("        Command to run: quote, chart (default \"quote\")")
	fmt.Println("  -symbol string")
	fmt.Println("        Symbol to subscribe to (default \"BINANCE:BTCUSDT\")")
	fmt.Println("  -timeframe string")
	fmt.Println("        Chart timeframe: 1, 5, 15, 60, 1D, 1W (default \"1D\")")
	fmt.Println("  -range int")
	fmt.Println("        Number of bars to retrieve for chart (default 100)")
	fmt.Println("  -format")
	fmt.Println("        Output in JSON format")
	fmt.Println("  -fields string")
	fmt.Println("        Comma-separated list of quote fields (default: all)")
	fmt.Println("  -help")
	fmt.Println("        Show this help documentation")
	fmt.Println()
	fmt.Println("ENVIRONMENT:")
	fmt.Println("  SESSION_ID       TradingView session ID cookie")
	fmt.Println("  SESSION_SIGN     TradingView session signature cookie")
	fmt.Println()
	fmt.Println("  You can also use a .env file in the current directory.")
	fmt.Println()
	fmt.Println("EXAMPLES:")
	fmt.Println("  # Get real-time quotes for BTC/USDT on Binance")
	fmt.Println("  tv-cli -command quote -symbol BINANCE:BTCUSDT")
	fmt.Println()
	fmt.Println("  # Get chart data with 1-hour timeframe")
	fmt.Println("  tv-cli -command chart -symbol BINANCE:ETHUSDT -timeframe 60 -range 50")
	fmt.Println()
	fmt.Println("  # Output in JSON format")
	fmt.Println("  tv-cli -command quote -symbol NASDAQ:AAPL -format")
	fmt.Println()
	fmt.Println("  # Subscribe to specific quote fields")
	fmt.Println("  tv-cli -command quote -symbol BINANCE:BTCUSDT -fields \"lp,volume,bid,ask\"")
	fmt.Println()
	fmt.Println("  # Bulk-fetch XAUUSD M5 history for Epic 12 backtest dataset")
	fmt.Println("  tv-cli -command backtest-fetch \\")
	fmt.Println("    -symbol OANDA:XAUUSD -timeframe 5 \\")
	fmt.Println("    -from 2024-01-01T00:00:00Z -to 2026-01-01T00:00:00Z \\")
	fmt.Println("    -window-name in_sample -window-kind in_sample \\")
	fmt.Println("    -out data/historical/XAUUSD/M5/in_sample.parquet")
	fmt.Println()
	fmt.Println("AUTHENTICATION:")
	fmt.Println("  To use this CLI, you need to provide your TradingView session credentials.")
	fmt.Println("  You can obtain these from your browser cookies after logging into TradingView:")
	fmt.Println()
	fmt.Println("  1. Log in to tradingview.com in your browser")
	fmt.Println("  2. Open browser Developer Tools (F12)")
	fmt.Println("  3. Go to Application/Storage > Cookies > https://tradingview.com")
	fmt.Println("  4. Copy the values of 'sessionid' and 'sessionid_sign'")
	fmt.Println("  5. Set them as environment variables or in a .env file:")
	fmt.Println()
	fmt.Println("     SESSION_ID=your_session_id_here")
	fmt.Println("     SESSION_SIGN=your_session_signature_here")
	fmt.Println()
	fmt.Println("AVAILABLE QUOTE FIELDS:")
	fmt.Println("  Common fields: lp (last price), volume, bid, ask, high_price, low_price")
	fmt.Println("  Change: ch (change), chp (change percent)")
	fmt.Println("  OHLC: open_price, high_price, low_price, close_price")
	fmt.Println("  Volume: volume, volume_24h, market_cap")
	fmt.Println("  And many more... Use without -fields flag to see all available data")
	fmt.Println()
}
