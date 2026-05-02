//! Tick data model.
//!
//! NOTE: This model includes `account_id` which extends the base architecture
//! message protocol to support multi-account routing. The architecture shows
//! tick messages without account_id, but this enhancement is required for
//! the multi-account trading system to route ticks to the correct account context.

use serde::{Deserialize, Serialize};

/// Market tick data from MT5.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Tick {
    /// Account identifier for multi-account support
    pub account_id: String,
    /// Trading symbol (e.g., "XAUUSD")
    pub symbol: String,
    /// Bid price
    pub bid: f64,
    /// Ask price
    pub ask: f64,
    /// Timestamp in ISO 8601 format
    pub timestamp: String,
}

impl Tick {
    /// Calculate spread in price units.
    pub fn spread(&self) -> f64 {
        self.ask - self.bid
    }

    /// Get PUB topic for this tick.
    pub fn topic(&self) -> String {
        format!("tick:{}", self.symbol)
    }
}
