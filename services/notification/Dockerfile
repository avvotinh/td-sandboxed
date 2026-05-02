# Stage 1: Build
FROM golang:1.23-alpine AS builder

WORKDIR /app

# Install build dependencies
RUN apk add --no-cache git ca-certificates

# Copy go mod files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build the binary
RUN CGO_ENABLED=0 GOOS=linux go build -ldflags="-w -s" -o /bot ./cmd/bot

# Stage 2: Runtime
FROM alpine:3.19

WORKDIR /app

# Install CA certificates for HTTPS
RUN apk add --no-cache ca-certificates tzdata

# Copy binary from builder
COPY --from=builder /bot /app/bot

# Set environment variables
ENV NOTIFICATION_LOG_LEVEL=info

# Health check (basic - checks if process is running)
# Note: Story 6.1 should implement proper healthcheck with Telegram API ping
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD pgrep -f bot || exit 1

# Run the bot
CMD ["/app/bot"]
