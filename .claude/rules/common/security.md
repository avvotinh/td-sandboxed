# Security Guidelines

## Mandatory Security Checks

Before ANY commit:
- [ ] No hardcoded secrets (API keys, passwords, tokens)
- [ ] All user inputs validated
- [ ] SQL injection prevention (parameterized queries)
- [ ] XSS prevention (sanitized HTML)
- [ ] CSRF protection enabled
- [ ] Authentication/authorization verified
- [ ] Rate limiting on all endpoints
- [ ] Error messages don't leak sensitive data

## Secret Management

- NEVER hardcode secrets in source code
- ALWAYS use environment variables or a secret manager
- Validate that required secrets are present at startup
- Rotate any secrets that may have been exposed

## Security Response Protocol

If security issue found:
1. STOP immediately
2. Use **security-reviewer** agent
3. Fix CRITICAL issues before continuing
4. Rotate any exposed secrets
5. Review entire codebase for similar issues

## Project-specific: Sandboxed FTMO

### Credentials handling
- **NEVER** hardcode: MT5 credentials, Telegram bot token, Redis password, DB password
- All secrets loaded via `settings.get_secret(key)` → backed by env vars / vault
- Secrets lookup MUST fail loudly (raise `ConfigError`) if missing — never silently default

### Financial data integrity
- Account balance/equity reads: Redis snapshot only (key: `account:{id}:snapshot`)
- NEVER recompute balance from trade history in hot path — use Redis hwm cache
- All write paths to `account.*` tables MUST go through `audit_log` write first (double-entry)

### Network boundary
- ZeroMQ sockets MUST use CURVE auth when exposed beyond localhost
- Order flow: REQ/REP only (not PUSH/PULL) — requires ack guarantee
- Telegram webhook: verify HMAC signature before processing
