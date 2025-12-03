package auth

import (
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"regexp"
	"strconv"
	"time"
)

const (
	// TradingViewURL is the main TradingView website URL for authentication.
	TradingViewURL = "https://www.tradingview.com"
)

var (
	// authTokenRegex extracts the auth_token from HTML response.
	authTokenRegex = regexp.MustCompile(`"auth_token":"([^"]*)"`)

	// userDataRegex extracts user data from HTML response.
	userIDRegex         = regexp.MustCompile(`"id":(\d+)`)
	usernameRegex       = regexp.MustCompile(`"username":"([^"]*)"`)
	firstNameRegex      = regexp.MustCompile(`"firstName":"([^"]*)"`)
	lastNameRegex       = regexp.MustCompile(`"lastName":"([^"]*)"`)
	reputationRegex     = regexp.MustCompile(`"reputation":([\d.]+)`)
	followingRegex      = regexp.MustCompile(`"following":(\d+)`)
	followersRegex      = regexp.MustCompile(`"followers":(\d+)`)
	privateChannelRegex = regexp.MustCompile(`"private_channel":"([^"]*)"`)
	sessionHashRegex    = regexp.MustCompile(`"session_hash":"([^"]*)"`)
)

// User represents an authenticated TradingView user.
// Duplicated here to avoid import cycles with pkg/tradingview.
type User struct {
	ID             string
	Username       string
	FirstName      string
	LastName       string
	Reputation     float64
	Following      int
	Followers      int
	AuthToken      string
	Session        string
	SessionHash    string
	PrivateChannel string
	JoinDate       time.Time
}

// GetUser retrieves user information and authentication token from TradingView.
// It makes an HTTP GET request to tradingview.com with the session cookies,
// then parses the HTML response to extract the auth_token and user data.
func GetUser(credentials *Credentials) (*User, error) {
	if credentials == nil {
		return nil, fmt.Errorf("credentials cannot be nil")
	}

	// Validate credentials
	if err := credentials.Validate(); err != nil {
		return nil, fmt.Errorf("invalid credentials: %w", err)
	}

	// Create HTTP client
	client := &http.Client{
		Timeout: 30 * time.Second,
	}

	// Create request
	req, err := http.NewRequest("GET", TradingViewURL, nil)
	if err != nil {
		return nil, fmt.Errorf("failed to create request: %w", err)
	}

	// Add cookie header
	req.Header.Set("Cookie", credentials.GenAuthCookies())
	req.Header.Set("User-Agent", "Mozilla/5.0 (compatible; TradingView-Go-API/1.0)")

	// Execute request
	resp, err := client.Do(req)
	if err != nil {
		return nil, fmt.Errorf("failed to execute request: %w", err)
	}
	defer resp.Body.Close()

	// Check status code
	if resp.StatusCode == http.StatusUnauthorized || resp.StatusCode == http.StatusForbidden {
		return nil, fmt.Errorf("invalid or expired credentials: HTTP %d", resp.StatusCode)
	}

	if resp.StatusCode != http.StatusOK {
		return nil, fmt.Errorf("unexpected response status: HTTP %d", resp.StatusCode)
	}

	// Read response body
	body, err := io.ReadAll(resp.Body)
	if err != nil {
		return nil, fmt.Errorf("failed to read response body: %w", err)
	}

	htmlContent := string(body)

	// Extract auth token
	authToken, err := extractAuthToken(htmlContent)
	if err != nil {
		return nil, fmt.Errorf("failed to extract auth token: %w", err)
	}

	// Extract user data
	user, err := extractUserData(htmlContent, credentials, authToken)
	if err != nil {
		return nil, fmt.Errorf("failed to extract user data: %w", err)
	}

	return user, nil
}

// extractAuthToken extracts the auth_token from HTML content.
func extractAuthToken(html string) (string, error) {
	matches := authTokenRegex.FindStringSubmatch(html)
	if len(matches) < 2 {
		return "", fmt.Errorf("auth_token not found in response")
	}

	authToken := matches[1]
	if authToken == "" {
		return "", fmt.Errorf("auth_token is empty")
	}

	return authToken, nil
}

// extractUserData extracts user information from HTML content.
func extractUserData(html string, credentials *Credentials, authToken string) (*User, error) {
	user := &User{
		AuthToken:   authToken,
		Session:     credentials.SessionID,
		SessionHash: extractRegexString(html, sessionHashRegex),
	}

	// Extract user ID
	if idStr := extractRegexString(html, userIDRegex); idStr != "" {
		user.ID = idStr
	}

	// Extract username
	user.Username = extractRegexString(html, usernameRegex)

	// Extract first name
	user.FirstName = extractRegexString(html, firstNameRegex)

	// Extract last name
	user.LastName = extractRegexString(html, lastNameRegex)

	// Extract reputation
	if repStr := extractRegexString(html, reputationRegex); repStr != "" {
		if rep, err := strconv.ParseFloat(repStr, 64); err == nil {
			user.Reputation = rep
		}
	}

	// Extract following count
	if followingStr := extractRegexString(html, followingRegex); followingStr != "" {
		if following, err := strconv.Atoi(followingStr); err == nil {
			user.Following = following
		}
	}

	// Extract followers count
	if followersStr := extractRegexString(html, followersRegex); followersStr != "" {
		if followers, err := strconv.Atoi(followersStr); err == nil {
			user.Followers = followers
		}
	}

	// Extract private channel
	user.PrivateChannel = extractRegexString(html, privateChannelRegex)

	// Set join date to current time (actual join date parsing would require more complex logic)
	user.JoinDate = time.Now()

	// Validate that we got at least the essential fields
	if user.ID == "" && user.Username == "" {
		return nil, fmt.Errorf("could not extract user ID or username from response")
	}

	return user, nil
}

// extractRegexString is a helper function to extract a string using a regex.
func extractRegexString(text string, regex *regexp.Regexp) string {
	matches := regex.FindStringSubmatch(text)
	if len(matches) >= 2 {
		return matches[1]
	}
	return ""
}

// ParseUserJSON parses user data from a JSON response.
// This is an alternative method for when user data is provided as JSON.
func ParseUserJSON(jsonData []byte) (*User, error) {
	var userData struct {
		ID             interface{} `json:"id"`
		Username       string      `json:"username"`
		FirstName      string      `json:"firstName"`
		LastName       string      `json:"lastName"`
		Reputation     float64     `json:"reputation"`
		Following      int         `json:"following"`
		Followers      int         `json:"followers"`
		AuthToken      string      `json:"auth_token"`
		Session        string      `json:"session"`
		SessionHash    string      `json:"session_hash"`
		PrivateChannel string      `json:"private_channel"`
	}

	if err := json.Unmarshal(jsonData, &userData); err != nil {
		return nil, fmt.Errorf("failed to parse user JSON: %w", err)
	}

	user := &User{
		Username:       userData.Username,
		FirstName:      userData.FirstName,
		LastName:       userData.LastName,
		Reputation:     userData.Reputation,
		Following:      userData.Following,
		Followers:      userData.Followers,
		AuthToken:      userData.AuthToken,
		Session:        userData.Session,
		SessionHash:    userData.SessionHash,
		PrivateChannel: userData.PrivateChannel,
		JoinDate:       time.Now(),
	}

	// Handle ID which might be int or string
	switch v := userData.ID.(type) {
	case float64:
		user.ID = strconv.FormatInt(int64(v), 10)
	case string:
		user.ID = v
	}

	return user, nil
}
