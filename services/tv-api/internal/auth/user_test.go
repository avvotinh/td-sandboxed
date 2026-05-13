package auth

import (
	"net/http"
	"net/url"
	"regexp"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestCredentials_Validate(t *testing.T) {
	tests := []struct {
		name        string
		credentials *Credentials
		wantErr     bool
		errContains string
	}{
		{
			name: "valid credentials",
			credentials: &Credentials{
				SessionID:   "test_session_id",
				SessionSign: "test_session_sign",
			},
			wantErr: false,
		},
		{
			name: "missing session ID",
			credentials: &Credentials{
				SessionID:   "",
				SessionSign: "test_session_sign",
			},
			wantErr:     true,
			errContains: "session ID is empty",
		},
		{
			name: "missing session sign",
			credentials: &Credentials{
				SessionID:   "test_session_id",
				SessionSign: "",
			},
			wantErr:     true,
			errContains: "session sign is empty",
		},
		{
			name: "both fields empty",
			credentials: &Credentials{
				SessionID:   "",
				SessionSign: "",
			},
			wantErr:     true,
			errContains: "session ID is empty",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.credentials.Validate()

			if tt.wantErr {
				require.Error(t, err)
				if tt.errContains != "" {
					assert.Contains(t, err.Error(), tt.errContains)
				}
			} else {
				require.NoError(t, err)
			}
		})
	}
}

func TestExtractAuthToken(t *testing.T) {
	tests := []struct {
		name        string
		html        string
		expected    string
		wantErr     bool
		errContains string
	}{
		{
			name:     "valid auth token",
			html:     `<script>var data = {"auth_token":"test_token_123"};</script>`,
			expected: "test_token_123",
			wantErr:  false,
		},
		{
			name:     "auth token with special characters",
			html:     `{"auth_token":"abc-123_XYZ.456"}`,
			expected: "abc-123_XYZ.456",
			wantErr:  false,
		},
		{
			name:     "auth token in complex HTML",
			html:     `<html><body><script>window.__AUTH__ = {"auth_token":"my_token","other":"data"};</script></body></html>`,
			expected: "my_token",
			wantErr:  false,
		},
		{
			name:        "missing auth token",
			html:        `<html><body>No token here</body></html>`,
			expected:    "",
			wantErr:     true,
			errContains: "auth_token not found",
		},
		{
			name:        "empty auth token",
			html:        `{"auth_token":""}`,
			expected:    "",
			wantErr:     true,
			errContains: "auth_token is empty",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			token, err := extractAuthToken(tt.html)

			if tt.wantErr {
				require.Error(t, err)
				if tt.errContains != "" {
					assert.Contains(t, err.Error(), tt.errContains)
				}
			} else {
				require.NoError(t, err)
				assert.Equal(t, tt.expected, token)
			}
		})
	}
}

func TestExtractUserData(t *testing.T) {
	tests := []struct {
		name        string
		html        string
		authToken   string
		credentials *Credentials
		validate    func(t *testing.T, user *User)
		wantErr     bool
		errContains string
	}{
		{
			name: "complete user data",
			html: `{
				"id":12345,
				"username":"testuser",
				"firstName":"Test",
				"lastName":"User",
				"reputation":100.5,
				"following":10,
				"followers":20,
				"session_hash":"hash123",
				"private_channel":"channel123"
			}`,
			authToken: "token123",
			credentials: &Credentials{
				SessionID:   "session123",
				SessionSign: "sign123",
			},
			validate: func(t *testing.T, user *User) {
				assert.Equal(t, "12345", user.ID)
				assert.Equal(t, "testuser", user.Username)
				assert.Equal(t, "Test", user.FirstName)
				assert.Equal(t, "User", user.LastName)
				assert.Equal(t, 100.5, user.Reputation)
				assert.Equal(t, 10, user.Following)
				assert.Equal(t, 20, user.Followers)
				assert.Equal(t, "token123", user.AuthToken)
				assert.Equal(t, "session123", user.Session)
				assert.Equal(t, "hash123", user.SessionHash)
				assert.Equal(t, "channel123", user.PrivateChannel)
			},
			wantErr: false,
		},
		{
			name:      "minimal user data",
			html:      `{"id":99,"username":"minimaluser"}`,
			authToken: "token456",
			credentials: &Credentials{
				SessionID:   "session456",
				SessionSign: "sign456",
			},
			validate: func(t *testing.T, user *User) {
				assert.Equal(t, "99", user.ID)
				assert.Equal(t, "minimaluser", user.Username)
				assert.Equal(t, "token456", user.AuthToken)
			},
			wantErr: false,
		},
		{
			name:      "missing user data",
			html:      `{"other":"data"}`,
			authToken: "token789",
			credentials: &Credentials{
				SessionID:   "session789",
				SessionSign: "sign789",
			},
			wantErr:     true,
			errContains: "could not extract user ID or username",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			user, err := extractUserData(tt.html, tt.credentials, tt.authToken)

			if tt.wantErr {
				require.Error(t, err)
				if tt.errContains != "" {
					assert.Contains(t, err.Error(), tt.errContains)
				}
			} else {
				require.NoError(t, err)
				require.NotNil(t, user)
				if tt.validate != nil {
					tt.validate(t, user)
				}
			}
		})
	}
}

func TestExtractRegexString(t *testing.T) {
	tests := []struct {
		name     string
		text     string
		pattern  string
		expected string
	}{
		{
			name:     "match found",
			text:     `"username":"testuser"`,
			pattern:  `"username":"([^"]*)"`,
			expected: "testuser",
		},
		{
			name:     "no match",
			text:     `"username":"testuser"`,
			pattern:  `"email":"([^"]*)"`,
			expected: "",
		},
		{
			name:     "multiple matches - first one",
			text:     `"username":"user1" and "username":"user2"`,
			pattern:  `"username":"([^"]*)"`,
			expected: "user1",
		},
		{
			name:     "empty match",
			text:     `"username":""`,
			pattern:  `"username":"([^"]*)"`,
			expected: "",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			regex := regexp.MustCompile(tt.pattern)
			result := extractRegexString(tt.text, regex)
			assert.Equal(t, tt.expected, result)
		})
	}
}

func TestParseUserJSON(t *testing.T) {
	tests := []struct {
		name        string
		jsonData    string
		validate    func(t *testing.T, user *User)
		wantErr     bool
		errContains string
	}{
		{
			name: "complete user JSON with numeric ID",
			jsonData: `{
				"id": 12345,
				"username": "jsonuser",
				"firstName": "Json",
				"lastName": "User",
				"reputation": 99.9,
				"following": 5,
				"followers": 15,
				"auth_token": "json_token",
				"session": "json_session",
				"session_hash": "json_hash",
				"private_channel": "json_channel"
			}`,
			validate: func(t *testing.T, user *User) {
				assert.Equal(t, "12345", user.ID)
				assert.Equal(t, "jsonuser", user.Username)
				assert.Equal(t, "Json", user.FirstName)
				assert.Equal(t, "User", user.LastName)
				assert.Equal(t, 99.9, user.Reputation)
				assert.Equal(t, 5, user.Following)
				assert.Equal(t, 15, user.Followers)
				assert.Equal(t, "json_token", user.AuthToken)
				assert.Equal(t, "json_session", user.Session)
				assert.Equal(t, "json_hash", user.SessionHash)
				assert.Equal(t, "json_channel", user.PrivateChannel)
			},
			wantErr: false,
		},
		{
			name: "user JSON with string ID",
			jsonData: `{
				"id": "user_123",
				"username": "stringiduser"
			}`,
			validate: func(t *testing.T, user *User) {
				assert.Equal(t, "user_123", user.ID)
				assert.Equal(t, "stringiduser", user.Username)
			},
			wantErr: false,
		},
		{
			name:        "invalid JSON",
			jsonData:    `{invalid json}`,
			wantErr:     true,
			errContains: "failed to parse user JSON",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			user, err := ParseUserJSON([]byte(tt.jsonData))

			if tt.wantErr {
				require.Error(t, err)
				if tt.errContains != "" {
					assert.Contains(t, err.Error(), tt.errContains)
				}
			} else {
				require.NoError(t, err)
				require.NotNil(t, user)
				if tt.validate != nil {
					tt.validate(t, user)
				}
			}
		})
	}
}

func TestGetUser_NilCredentials(t *testing.T) {
	user, err := GetUser(nil)
	require.Error(t, err)
	assert.Nil(t, user)
	assert.Contains(t, err.Error(), "credentials cannot be nil")
}

func TestGetUser_InvalidCredentials(t *testing.T) {
	credentials := &Credentials{
		SessionID:   "",
		SessionSign: "test",
	}

	user, err := GetUser(credentials)
	require.Error(t, err)
	assert.Nil(t, user)
	assert.Contains(t, err.Error(), "invalid credentials")
}

// TestBuildAuthCookieJar_CarriesCookiesAcrossSubdomainRedirect locks in
// the geo-redirect fix from commit 29ca9b0. Before the fix the auth
// client attached cookies via req.Header.Set("Cookie", ...), which Go
// drops on follow-up redirects — a VN-region operator hitting
// www.tradingview.com gets bounced to vn.tradingview.com and arrived
// anonymous. After the fix the cookies live in a jar with
// Domain="tradingview.com", which scopes them to every subdomain. This
// test asserts the jar's contract directly: a request to a different
// subdomain still receives the same two cookies, byte for byte.
func TestBuildAuthCookieJar_CarriesCookiesAcrossSubdomainRedirect(t *testing.T) {
	creds := &Credentials{SessionID: "abc123", SessionSign: "v3:xyz789"}

	jar, err := buildAuthCookieJar(creds)
	require.NoError(t, err)

	subdomains := []string{
		"https://www.tradingview.com",
		"https://vn.tradingview.com", // the regional bounce that broke before 29ca9b0
		"https://tradingview.com",
	}
	for _, raw := range subdomains {
		t.Run(raw, func(t *testing.T) {
			u, err := url.Parse(raw)
			require.NoError(t, err)
			cookies := jar.Cookies(u)
			require.Len(t, cookies, 2,
				"jar must serve both cookies for any tradingview subdomain")
			byName := map[string]*http.Cookie{}
			for _, c := range cookies {
				byName[c.Name] = c
			}
			require.Contains(t, byName, "sessionid")
			require.Contains(t, byName, "sessionid_sign")
			assert.Equal(t, "abc123", byName["sessionid"].Value)
			assert.Equal(t, "v3:xyz789", byName["sessionid_sign"].Value)
		})
	}
}

// TestCheckRedirectStaysOnTradingView covers the SSRF-adjacent guard
// added alongside the cookie fix. The CheckRedirect predicate must
// admit any subdomain of tradingview.com (so the geo-redirect path
// works) while refusing every other host — even one that *contains*
// the substring, which a naive strings.Contains would let through.
func TestCheckRedirectStaysOnTradingView(t *testing.T) {
	cases := []struct {
		name      string
		host      string
		shouldErr bool
	}{
		{"apex", "tradingview.com", false},
		{"www subdomain", "www.tradingview.com", false},
		{"vn subdomain", "vn.tradingview.com", false},
		{"deeper subdomain", "static.cdn.tradingview.com", false},
		// Negative cases — host either fully different or only a substring match.
		{"unrelated host", "evil.com", true},
		{"loopback", "127.0.0.1", true},
		{"substring impostor", "tradingview.com.evil.example", true},
		{"prefix impostor", "fakeradingview.com", true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			req := &http.Request{URL: &url.URL{Scheme: "https", Host: tc.host, Path: "/"}}
			err := checkRedirectStaysOnTradingView(req, nil)
			if tc.shouldErr {
				require.Error(t, err, "host %q must be refused", tc.host)
				assert.Contains(t, err.Error(), tc.host)
			} else {
				assert.NoError(t, err, "host %q must be admitted", tc.host)
			}
		})
	}
}
