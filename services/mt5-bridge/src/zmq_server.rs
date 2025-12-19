//! ZeroMQ server implementation.
//!
//! This is a scaffold placeholder. Full ZeroMQ socket implementation
//! will be completed in Story 2.3.

use crate::config::Config;
use crate::handlers::{OrderHandler, TickHandler};
use tracing::{info, warn};

/// ZeroMQ server for MT5 bridge communication.
pub struct ZmqServer {
    config: Config,
    tick_handler: TickHandler,
    order_handler: OrderHandler,
}

impl ZmqServer {
    /// Create a new ZeroMQ server with the given configuration.
    pub fn new(config: Config) -> anyhow::Result<Self> {
        Ok(Self {
            config,
            tick_handler: TickHandler::new(),
            order_handler: OrderHandler::new(),
        })
    }

    /// Run the ZeroMQ server.
    ///
    /// This scaffold demonstrates the async structure that will be
    /// used for the actual implementation in Story 2.3.
    pub async fn run(&self) -> anyhow::Result<()> {
        info!(
            req_endpoint = %self.config.req_endpoint(),
            pub_endpoint = %self.config.pub_endpoint(),
            sub_endpoint = %self.config.sub_endpoint(),
            "ZeroMQ server starting (scaffold mode)"
        );

        // Scaffold: Log port availability
        // In Story 2.3, this will bind actual ZeroMQ sockets
        warn!("ZeroMQ sockets not bound - scaffold only");
        warn!("Full implementation in Story 2.3: MT5 Bridge ZeroMQ Server");

        // Keep running until shutdown signal
        // In production, this will be the main event loop
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(60)).await;
            info!("MT5 Bridge heartbeat (scaffold mode)");
        }
    }

    /// Get reference to tick handler.
    pub fn tick_handler(&self) -> &TickHandler {
        &self.tick_handler
    }

    /// Get reference to order handler.
    pub fn order_handler(&self) -> &OrderHandler {
        &self.order_handler
    }
}
