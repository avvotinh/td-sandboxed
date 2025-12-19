//! Tick message handler.

use crate::models::Tick;
use crate::protocol::AckResponse;
use tracing::{debug, instrument};

/// Handler for incoming tick data from MT5.
pub struct TickHandler;

impl TickHandler {
    pub fn new() -> Self {
        Self
    }

    /// Process incoming tick and prepare for publishing.
    #[instrument(skip(self), fields(symbol = %tick.symbol))]
    pub fn handle(&self, tick: &Tick) -> AckResponse {
        debug!(
            account_id = %tick.account_id,
            bid = tick.bid,
            ask = tick.ask,
            spread = tick.spread(),
            "Tick received"
        );

        // In Story 2.3, this will publish to PUB socket
        // For now, just acknowledge receipt
        AckResponse::ok()
    }
}

impl Default for TickHandler {
    fn default() -> Self {
        Self::new()
    }
}
