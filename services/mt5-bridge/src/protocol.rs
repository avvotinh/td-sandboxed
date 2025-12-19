//! Message protocol definitions for MT5 Bridge.
//!
//! Defines the JSON message format for communication between
//! MT5 EAs and the trading engine.

use serde::{Deserialize, Serialize};

/// Message type identifier.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum MessageType {
    Tick,
    Order,
    OrderResult,
    Heartbeat,
    Ack,
    Error,
}

/// Incoming message from MT5 EA or trading engine.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct IncomingMessage {
    #[serde(rename = "type")]
    pub msg_type: MessageType,
    #[serde(flatten)]
    pub payload: serde_json::Value,
}

/// Acknowledgment response.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct AckResponse {
    #[serde(rename = "type")]
    pub msg_type: MessageType,
    pub status: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
}

impl AckResponse {
    pub fn ok() -> Self {
        Self {
            msg_type: MessageType::Ack,
            status: "ok".to_string(),
            message: None,
        }
    }

    pub fn error(message: impl Into<String>) -> Self {
        Self {
            msg_type: MessageType::Error,
            status: "error".to_string(),
            message: Some(message.into()),
        }
    }
}
