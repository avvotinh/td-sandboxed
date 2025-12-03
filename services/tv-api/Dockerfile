# Multi-stage build for minimal production image
# Stage 1: Build
FROM golang:1.24-alpine AS builder

# Install build dependencies
RUN apk add --no-cache git ca-certificates tzdata

WORKDIR /build

# Copy go mod files first for better caching
COPY go.mod go.sum ./
RUN go mod download

# Copy source code
COPY . .

# Build the application
# CGO_ENABLED=0 for static binary
RUN CGO_ENABLED=0 GOOS=linux GOARCH=amd64 go build \
    -ldflags='-w -s -extldflags "-static"' \
    -o ingestion-client \
    ./cmd/tv-chart

# Stage 2: Runtime
FROM alpine:latest

# Install runtime dependencies
RUN apk add --no-cache ca-certificates tzdata

# Create non-root user for security
RUN addgroup -g 1000 hft && \
    adduser -D -u 1000 -G hft hft

WORKDIR /app

# Copy binary from builder
COPY --from=builder /build/ingestion-client .
COPY --from=builder /build/config.yaml .

# Change ownership
RUN chown -R hft:hft /app

# Switch to non-root user
USER hft

# Health check
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
    CMD pgrep -x ingestion-client || exit 1

# Run the application
CMD ["./ingestion-client"]
