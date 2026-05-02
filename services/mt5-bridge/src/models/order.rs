//! Order data models.

use serde::{Deserialize, Serialize};

/// Order side (direction).
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "UPPERCASE")]
pub enum OrderSide {
    Buy,
    Sell,
}

/// Order command to MT5.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Order {
    /// Order action type
    pub action: OrderSide,
    /// Trading symbol
    pub symbol: String,
    /// Volume in lots
    pub volume: f64,
    /// Requested price
    pub price: f64,
    /// Stop loss price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub sl: Option<f64>,
    /// Take profit price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tp: Option<f64>,
    /// Unique order identifier
    pub order_id: String,
    /// Account identifier
    pub account_id: String,
}

/// Order execution status.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq)]
#[serde(rename_all = "snake_case")]
pub enum OrderStatus {
    Filled,
    PartiallyFilled,
    Rejected,
    Error,
}

/// Order execution result from MT5.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct OrderResult {
    /// Original order ID
    pub order_id: String,
    /// Execution status
    pub status: OrderStatus,
    /// Actual fill price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub fill_price: Option<f64>,
    /// Slippage from requested price
    #[serde(skip_serializing_if = "Option::is_none")]
    pub slippage: Option<f64>,
    /// Execution timestamp
    pub timestamp: String,
    /// Error message if failed
    #[serde(skip_serializing_if = "Option::is_none")]
    pub error: Option<String>,
}
