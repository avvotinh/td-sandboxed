# Stage 1: Build
FROM rust:slim AS builder
WORKDIR /app

# Copy manifests first for dependency caching
COPY Cargo.toml Cargo.lock* ./

# Create a dummy main to build dependencies
RUN mkdir -p src && echo "fn main() {}" > src/main.rs && touch src/lib.rs

# Build dependencies only (this layer will be cached)
RUN cargo build --release 2>/dev/null || true

# Remove the dummy source files
RUN rm -rf src

# Copy actual source
COPY src ./src
COPY tests ./tests

# Build the actual application
RUN cargo build --release

# Stage 2: Runtime
FROM debian:bookworm-slim AS runtime
WORKDIR /app

# Install runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy binary from builder
COPY --from=builder /app/target/release/mt5-bridge /app/mt5-bridge

# Set environment variables
ENV RUST_LOG=info
ENV ZMQ_REQ_PORT=5555
ENV ZMQ_PUB_PORT=5556
ENV ZMQ_SUB_PORT=5557

# Expose ZeroMQ ports
EXPOSE 5555 5556 5557

# Health check (scaffold: binary exists)
# NOTE: Story 2.3 should implement proper healthcheck that verifies
# ZeroMQ sockets are bound and responding (e.g., ZMQ REQ/REP ping)
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD test -f /app/mt5-bridge || exit 1

# Run the application
CMD ["/app/mt5-bridge"]
