package auth

import (
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

func TestCredentials_GenAuthCookies(t *testing.T) {
	tests := []struct {
		name        string
		credentials *Credentials
		expected    string
	}{
		{
			name: "normal credentials",
			credentials: &Credentials{
				SessionID:   "abc123",
				SessionSign: "xyz789",
			},
			expected: "sessionid=abc123; sessionid_sign=xyz789",
		},
		{
			name: "credentials with special characters",
			credentials: &Credentials{
				SessionID:   "test_id_with_underscore",
				SessionSign: "test-sign-with-dash",
			},
			expected: "sessionid=test_id_with_underscore; sessionid_sign=test-sign-with-dash",
		},
		{
			name: "empty credentials",
			credentials: &Credentials{
				SessionID:   "",
				SessionSign: "",
			},
			expected: "sessionid=; sessionid_sign=",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			result := tt.credentials.GenAuthCookies()
			assert.Equal(t, tt.expected, result)
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
