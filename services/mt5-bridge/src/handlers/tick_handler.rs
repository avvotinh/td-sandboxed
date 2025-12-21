//! Tick message handler.
//!
//! Handles tick data processing and logging. The actual PUB socket
//! publishing is done by ZmqServer before calling this handler.

use crate::models::Tick;
use crate::protocol::AckResponse;
use tracing::{debug, instrument};

/// Handler for incoming tick data from MT5.
///
/// Note: Tick publishing to PUB socket is handled by ZmqServer.
/// This handler performs logging and returns ACK response.
pub struct TickHandler;

impl TickHandler {
    pub fn new() -> Self {
        Self
    }

    /// Process incoming tick and return acknowledgment.
    ///
    /// The tick has already been published to the PUB socket by ZmqServer
    /// before this method is called.
    #[instrument(skip(self), fields(symbol = %tick.symbol))]
    pub fn handle(&self, tick: &Tick) -> AckResponse {
        debug!(
            account_id = %tick.account_id,
            bid = tick.bid,
            ask = tick.ask,
            spread = tick.spread(),
            "Tick processed"
        );

        AckResponse::ok()
    }
}

impl Default for TickHandler {
    fn default() -> Self {
        Self::new()
    }
}
