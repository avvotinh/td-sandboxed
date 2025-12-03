package tradingview

import "time"

// Period represents a single OHLCV (Open, High, Low, Close, Volume) candle.
type Period struct {
	Time   int64   `json:"time"`   // Unix timestamp
	Open   float64 `json:"open"`   // Opening price
	Close  float64 `json:"close"`  // Closing price
	High   float64 `json:"max"`    // Highest price (note: TradingView uses "max")
	Low    float64 `json:"min"`    // Lowest price (note: TradingView uses "min")
	Volume float64 `json:"volume"` // Trading volume
}

// MarketInfo contains detailed information about a market symbol.
type MarketInfo struct {
	Symbol               string   `json:"symbol"`
	Exchange             string   `json:"exchange"`
	FullName             string   `json:"full_name"`
	Description          string   `json:"description"`
	Type                 string   `json:"type"`
	Currency             string   `json:"currency"`
	BaseCurrency         string   `json:"base_currency"`
	PriceScale           int      `json:"pricescale"`
	MinMove              int      `json:"minmov"`
	MinMove2             int      `json:"minmove2"`
	FractionalDigits     int      `json:"fractional"`
	Session              string   `json:"session"`
	Timezone             string   `json:"timezone"`
	HasIntraday          bool     `json:"has_intraday"`
	HasDaily             bool     `json:"has_daily"`
	HasWeekly            bool     `json:"has_weekly_and_monthly"`
	HasNoVolume          bool     `json:"has_no_volume"`
	VolumeScale          int      `json:"volume_precision"`
	DataStatus           string   `json:"data_status"`
	Expired              bool     `json:"expired"`
	ExpirationDate       int64    `json:"expiration_date"`
	Sector               string   `json:"sector"`
	Industry             string   `json:"industry"`
	CurrencyCode         string   `json:"currency_code"`
	OriginalCurrencyCode string   `json:"original_currency_code"`
	UnitID               string   `json:"unit_id"`
	OriginalUnitID       string   `json:"original_unit_id"`
	UnitConversionTypes  []string `json:"unit_conversion_types"`
}

// User represents an authenticated TradingView user.
type User struct {
	ID             string    `json:"id"`
	Username       string    `json:"username"`
	FirstName      string    `json:"firstName"`
	LastName       string    `json:"lastName"`
	Reputation     float64   `json:"reputation"`
	Following      int       `json:"following"`
	Followers      int       `json:"followers"`
	AuthToken      string    `json:"authToken"`
	Session        string    `json:"session"`
	SessionHash    string    `json:"sessionHash"`
	PrivateChannel string    `json:"privateChannel"`
	JoinDate       time.Time `json:"joinDate"`
}

// TimeFrame represents a chart timeframe.
type TimeFrame string

// Common timeframe constants.
const (
	TimeFrame1S  TimeFrame = "1S"  // 1 second
	TimeFrame5S  TimeFrame = "5S"  // 5 seconds
	TimeFrame10S TimeFrame = "10S" // 10 seconds
	TimeFrame15S TimeFrame = "15S" // 15 seconds
	TimeFrame30S TimeFrame = "30S" // 30 seconds
	TimeFrame1   TimeFrame = "1"   // 1 minute
	TimeFrame3   TimeFrame = "3"   // 3 minutes
	TimeFrame5   TimeFrame = "5"   // 5 minutes
	TimeFrame15  TimeFrame = "15"  // 15 minutes
	TimeFrame30  TimeFrame = "30"  // 30 minutes
	TimeFrame45  TimeFrame = "45"  // 45 minutes
	TimeFrame60  TimeFrame = "60"  // 1 hour
	TimeFrame120 TimeFrame = "120" // 2 hours
	TimeFrame180 TimeFrame = "180" // 3 hours
	TimeFrame240 TimeFrame = "240" // 4 hours
	TimeFrame1D  TimeFrame = "1D"  // 1 day
	TimeFrame1W  TimeFrame = "1W"  // 1 week
	TimeFrame1M  TimeFrame = "1M"  // 1 month
)

// Timezone represents a TradingView timezone.
type Timezone string

// Common timezone constants.
const (
	TimezoneExchange   Timezone = "exchange" // Exchange timezone
	TimezoneUTC        Timezone = "Etc/UTC"  // UTC
	TimezoneNewYork    Timezone = "America/New_York"
	TimezoneChicago    Timezone = "America/Chicago"
	TimezoneLosAngeles Timezone = "America/Los_Angeles"
	TimezoneLondon     Timezone = "Europe/London"
	TimezoneParis      Timezone = "Europe/Paris"
	TimezoneTokyo      Timezone = "Asia/Tokyo"
	TimezoneShanghai   Timezone = "Asia/Shanghai"
	TimezoneHongKong   Timezone = "Asia/Hong_Kong"
	TimezoneSydney     Timezone = "Australia/Sydney"
)

// SessionType represents the type of session.
type SessionType string

const (
	// SessionTypeQuote represents a quote session.
	SessionTypeQuote SessionType = "quote"

	// SessionTypeChart represents a chart session.
	SessionTypeChart SessionType = "chart"
)
