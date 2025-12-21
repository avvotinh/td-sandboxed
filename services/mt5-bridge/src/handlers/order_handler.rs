//! Order message handler.
//!
//! Handles order command processing and logging. The actual order
//! forwarding to MT5 EA is done by ZmqServer via the order queue.

use crate::models::{Order, OrderResult, OrderStatus};
use tracing::{info, instrument};

/// Handler for order commands from trading engine.
///
/// Note: Order forwarding to MT5 EA is handled by ZmqServer via mpsc queue.
/// Orders are delivered to MT5 EA on heartbeat responses.
pub struct OrderHandler;

impl OrderHandler {
    pub fn new() -> Self {
        Self
    }

    /// Log and validate order command.
    ///
    /// This method is used for order logging and validation.
    /// Actual order forwarding is handled by ZmqServer.
    #[allow(dead_code)]
    #[instrument(skip(self), fields(order_id = %order.order_id))]
    pub fn log_order(&self, order: &Order) {
        info!(
            account_id = %order.account_id,
            symbol = %order.symbol,
            action = ?order.action,
            volume = order.volume,
            price = order.price,
            sl = ?order.sl,
            tp = ?order.tp,
            "Order queued for MT5 EA"
        );
    }

    /// Process order command (legacy method for tests).
    ///
    /// In production, orders are queued by ZmqServer and delivered
    /// to MT5 EA via heartbeat responses. This method simulates
    /// order processing for testing purposes.
    #[instrument(skip(self), fields(order_id = %order.order_id))]
    pub async fn handle(&self, order: &Order) -> OrderResult {
        info!(
            account_id = %order.account_id,
            symbol = %order.symbol,
            action = ?order.action,
            volume = order.volume,
            "Order received for processing"
        );

        // Simulate order forwarding - in production this is handled by ZmqServer
        // The actual result comes from MT5 EA via order_result messages
        OrderResult {
            order_id: order.order_id.clone(),
            status: OrderStatus::Rejected,
            fill_price: None,
            slippage: None,
            timestamp: chrono::Utc::now().to_rfc3339(),
            error: Some("Order handler test mode - use ZmqServer for live trading".to_string()),
        }
    }
}

impl Default for OrderHandler {
    fn default() -> Self {
        Self::new()
    }
}
