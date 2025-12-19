//! Order message handler.

use crate::models::{Order, OrderResult};
use tracing::{info, instrument};

/// Handler for order commands from trading engine.
pub struct OrderHandler;

impl OrderHandler {
    pub fn new() -> Self {
        Self
    }

    /// Process order command and forward to MT5.
    #[instrument(skip(self), fields(order_id = %order.order_id))]
    pub async fn handle(&self, order: &Order) -> OrderResult {
        info!(
            account_id = %order.account_id,
            symbol = %order.symbol,
            action = ?order.action,
            volume = order.volume,
            "Order received"
        );

        // In Story 2.3, this will forward to MT5 EA via REQ socket
        // For now, return placeholder result
        OrderResult {
            order_id: order.order_id.clone(),
            status: crate::models::OrderStatus::Rejected,
            fill_price: None,
            slippage: None,
            timestamp: chrono::Utc::now().to_rfc3339(),
            error: Some("Bridge not connected to MT5 (scaffold only)".to_string()),
        }
    }
}

impl Default for OrderHandler {
    fn default() -> Self {
        Self::new()
    }
}
