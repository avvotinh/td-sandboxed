//! Bridge error types.
//!
//! Defines error types for the MT5 Bridge service.
//! Full error handling implementation in Story 2.3.

use thiserror::Error;

/// Bridge-level errors.
///
/// These errors represent failures in bridge operations.
/// Used for error propagation and logging.
#[derive(Debug, Error)]
pub enum BridgeError {
    /// ZeroMQ connection was lost
    #[error("Connection lost: {0}")]
    ConnectionLost(String),

    /// Message timeout occurred
    #[error("Message timeout after {0}ms")]
    MessageTimeout(u64),

    /// Invalid message received
    #[error("Invalid message: {0}")]
    InvalidMessage(String),

    /// Account disconnected from MT5
    #[error("Account {0} disconnected")]
    AccountDisconnected(String),

    /// Configuration error
    #[error("Configuration error: {0}")]
    Config(#[from] crate::config::ConfigError),

    /// Serialization error
    #[error("Serialization error: {0}")]
    Serialization(#[from] serde_json::Error),
}

/// Result type alias for bridge operations.
pub type BridgeResult<T> = Result<T, BridgeError>;
