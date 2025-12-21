//! ZeroMQ server implementation.
//!
//! Implements the ZeroMQ bridge for communication between MT5 EAs
//! and the trading engine. Handles tick data, heartbeats, and order commands.

use crate::config::Config;
use crate::handlers::{OrderHandler, TickHandler};
use crate::models::{Order, OrderResult, Tick};
use crate::protocol::{AckResponse, Heartbeat, IncomingMessage, MessageType};
use std::collections::HashMap;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::{mpsc, RwLock};
use tracing::{debug, error, info, warn};
use zeromq::{PubSocket, RepSocket, Socket, SocketRecv, SocketSend, SubSocket, ZmqMessage};

/// Order queue capacity for pending orders from trading-engine.
const ORDER_QUEUE_CAPACITY: usize = 100;

/// Heartbeat timeout threshold in seconds.
const HEARTBEAT_TIMEOUT_SECS: u64 = 30;

/// Heartbeat check interval in seconds.
const HEARTBEAT_CHECK_INTERVAL_SECS: u64 = 10;

/// Message processing timeout in milliseconds.
const MESSAGE_PROCESSING_TIMEOUT_MS: u64 = 1000;

/// Heartbeat response SLA in milliseconds (AC3 requirement).
/// Heartbeat handling is simple enough to complete well under this threshold.
#[allow(dead_code)]
const HEARTBEAT_RESPONSE_SLA_MS: u64 = 100;

/// ZeroMQ server for MT5 bridge communication.
pub struct ZmqServer {
    config: Config,
    rep_socket: RepSocket,
    pub_socket: PubSocket,
    sub_socket: SubSocket,
    tick_handler: TickHandler,
    order_handler: OrderHandler,
    /// Last heartbeat time per account for timeout detection
    last_heartbeat: Arc<RwLock<HashMap<String, Instant>>>,
    /// Order queue sender for orders from trading-engine
    order_tx: mpsc::Sender<Order>,
    /// Order queue receiver for orders to forward to MT5 EA
    order_rx: mpsc::Receiver<Order>,
}

impl ZmqServer {
    /// Create a new ZeroMQ server with the given configuration.
    ///
    /// Binds REP socket on port 5555, PUB socket on port 5556,
    /// and connects SUB socket to trading-engine on port 5557.
    pub async fn new(config: Config) -> anyhow::Result<Self> {
        // Bind REP socket for MT5 EA communication (tick data, heartbeats, order results)
        let mut rep_socket = RepSocket::new();
        rep_socket.bind(&config.req_endpoint()).await?;
        info!(endpoint = %config.req_endpoint(), "REP socket bound");

        // Bind PUB socket for broadcasting ticks to trading-engine
        let mut pub_socket = PubSocket::new();
        pub_socket.bind(&config.pub_endpoint()).await?;
        info!(endpoint = %config.pub_endpoint(), "PUB socket bound");

        // Connect SUB socket to trading-engine PUB for order commands
        // NOTE: SUB sockets CONNECT to PUB sockets (trading-engine binds, bridge connects)
        let mut sub_socket = SubSocket::new();
        sub_socket.connect(&config.sub_endpoint()).await?;
        // Subscribe to all order topics
        sub_socket.subscribe("order:").await?;
        info!(endpoint = %config.sub_endpoint(), "SUB socket connected");

        // Create order queue for async delivery to MT5 EA
        let (order_tx, order_rx) = mpsc::channel(ORDER_QUEUE_CAPACITY);

        Ok(Self {
            config,
            rep_socket,
            pub_socket,
            sub_socket,
            tick_handler: TickHandler::new(),
            order_handler: OrderHandler::new(),
            last_heartbeat: Arc::new(RwLock::new(HashMap::new())),
            order_tx,
            order_rx,
        })
    }

    /// Run the ZeroMQ server main event loop.
    ///
    /// Handles:
    /// - REP socket messages from MT5 EA (ticks, heartbeats, order results)
    /// - SUB socket messages from trading-engine (order commands)
    /// - Background heartbeat timeout monitoring
    pub async fn run(&mut self) -> anyhow::Result<()> {
        info!(
            req_endpoint = %self.config.req_endpoint(),
            pub_endpoint = %self.config.pub_endpoint(),
            sub_endpoint = %self.config.sub_endpoint(),
            "ZeroMQ server starting"
        );

        // Spawn background heartbeat monitor task (AC6)
        let heartbeat_map = self.last_heartbeat.clone();
        tokio::spawn(async move {
            Self::heartbeat_monitor(heartbeat_map).await;
        });

        loop {
            tokio::select! {
                // Handle messages from MT5 EA (REP socket)
                result = self.rep_socket.recv() => {
                    match result {
                        Ok(msg) => {
                            // Timeout wrapper to prevent REP deadlock
                            let response = tokio::time::timeout(
                                tokio::time::Duration::from_millis(MESSAGE_PROCESSING_TIMEOUT_MS),
                                self.handle_rep_message(msg)
                            ).await.unwrap_or_else(|_| {
                                error!("Message processing timeout - REP deadlock prevention");
                                self.create_response(&AckResponse::error("Processing timeout"))
                            });

                            // REP socket MUST send reply after every receive
                            if let Err(e) = self.rep_socket.send(response).await {
                                error!(error = %e, "Failed to send REP response");
                            }
                        }
                        Err(e) => {
                            error!(error = %e, "REP socket receive error");
                        }
                    }
                }

                // Handle order commands from trading-engine (SUB socket)
                result = self.sub_socket.recv() => {
                    match result {
                        Ok(msg) => {
                            self.handle_order_command(msg).await;
                        }
                        Err(e) => {
                            error!(error = %e, "SUB socket receive error");
                        }
                    }
                }
            }
        }
    }

    /// Background task to monitor heartbeat timeouts per account.
    async fn heartbeat_monitor(heartbeat_map: Arc<RwLock<HashMap<String, Instant>>>) {
        let mut interval = tokio::time::interval(tokio::time::Duration::from_secs(
            HEARTBEAT_CHECK_INTERVAL_SECS,
        ));

        loop {
            interval.tick().await;
            let heartbeats = heartbeat_map.read().await;

            for (account_id, last_time) in heartbeats.iter() {
                let elapsed = last_time.elapsed().as_secs();
                if elapsed > HEARTBEAT_TIMEOUT_SECS {
                    warn!(
                        account_id = %account_id,
                        elapsed_secs = elapsed,
                        "Heartbeat timeout detected - maintaining socket readiness"
                    );
                }
            }
        }
    }

    /// Handle incoming message from MT5 EA on REP socket.
    async fn handle_rep_message(&mut self, msg: ZmqMessage) -> ZmqMessage {
        let data = msg
            .get(0)
            .map(|b| String::from_utf8_lossy(b).to_string())
            .unwrap_or_default();

        debug!(data = %data, "Received REP message");

        let response = match serde_json::from_str::<IncomingMessage>(&data) {
            Ok(incoming) => match incoming.msg_type {
                MessageType::Tick => self.handle_tick_message(&incoming.payload).await,
                MessageType::Heartbeat => self.handle_heartbeat_message(&incoming.payload).await,
                MessageType::OrderResult => {
                    self.handle_order_result_message(&incoming.payload).await
                }
                _ => AckResponse::error("Unexpected message type on REP socket"),
            },
            Err(e) => {
                warn!(error = %e, data = %data, "Failed to parse message");
                AckResponse::error(format!("JSON parse error: {}", e))
            }
        };

        self.create_response(&response)
    }

    /// Handle tick message from MT5 EA.
    async fn handle_tick_message(&mut self, payload: &serde_json::Value) -> AckResponse {
        match serde_json::from_value::<Tick>(payload.clone()) {
            Ok(tick) => {
                // Publish tick to PUB socket for trading-engine
                if let Err(e) = self.publish_tick(&tick).await {
                    error!(error = %e, symbol = %tick.symbol, "Failed to publish tick");
                    return AckResponse::error(format!("Failed to publish tick: {}", e));
                }

                // Use tick handler for logging/processing
                self.tick_handler.handle(&tick)
            }
            Err(e) => {
                warn!(error = %e, "Invalid tick payload");
                AckResponse::error(format!("Invalid tick payload: {}", e))
            }
        }
    }

    /// Handle heartbeat message from MT5 EA.
    async fn handle_heartbeat_message(&mut self, payload: &serde_json::Value) -> AckResponse {
        match serde_json::from_value::<Heartbeat>(payload.clone()) {
            Ok(heartbeat) => {
                // Track heartbeat time per account (AC6)
                {
                    let mut heartbeats = self.last_heartbeat.write().await;
                    heartbeats.insert(heartbeat.account_id.clone(), Instant::now());
                    debug!(account_id = %heartbeat.account_id, "Heartbeat received");
                } // Drop the write lock before accessing other self fields

                // Check for pending orders to deliver to this account
                if let Some(order) = self.get_pending_order().await {
                    if order.account_id == heartbeat.account_id {
                        debug!(order_id = %order.order_id, "Delivering pending order with heartbeat response");
                        // Return order instead of ACK
                        return self.order_to_ack_response(&order);
                    } else {
                        // Put it back if it's for a different account
                        // (This is a simplification - production would use per-account queues)
                        let _ = self.order_tx.send(order).await;
                    }
                }

                AckResponse::ok()
            }
            Err(e) => {
                warn!(error = %e, "Invalid heartbeat payload");
                AckResponse::error(format!("Invalid heartbeat payload: {}", e))
            }
        }
    }

    /// Handle order result message from MT5 EA.
    async fn handle_order_result_message(&mut self, payload: &serde_json::Value) -> AckResponse {
        match serde_json::from_value::<OrderResult>(payload.clone()) {
            Ok(result) => {
                info!(
                    order_id = %result.order_id,
                    status = ?result.status,
                    "Order result received from MT5"
                );

                // Publish order result to trading-engine
                if let Err(e) = self.publish_order_result(&result).await {
                    error!(error = %e, "Failed to publish order result");
                }

                AckResponse::ok()
            }
            Err(e) => {
                warn!(error = %e, "Invalid order result payload");
                AckResponse::error(format!("Invalid order result payload: {}", e))
            }
        }
    }

    /// Handle order command from trading-engine on SUB socket.
    async fn handle_order_command(&mut self, msg: ZmqMessage) {
        // Multipart message: [topic, payload]
        if let Some(payload_bytes) = msg.get(1) {
            let data_str = String::from_utf8_lossy(payload_bytes);
            match serde_json::from_str::<Order>(&data_str) {
                Ok(order) => {
                    info!(
                        order_id = %order.order_id,
                        account_id = %order.account_id,
                        symbol = %order.symbol,
                        action = ?order.action,
                        "Order command received, queuing for MT5 EA"
                    );

                    // Queue order for delivery to MT5 EA on next poll/heartbeat
                    if let Err(e) = self.order_tx.send(order).await {
                        error!(error = %e, "Failed to queue order - channel full or closed");
                    }
                }
                Err(e) => {
                    warn!(error = %e, data = %data_str, "Failed to parse order command JSON");
                }
            }
        } else {
            warn!("Order command missing payload");
        }
    }

    /// Publish tick to PUB socket with topic prefix.
    async fn publish_tick(&mut self, tick: &Tick) -> anyhow::Result<()> {
        let topic = tick.topic();
        let payload = serde_json::to_string(tick)?;

        // Create multipart message: [topic, payload]
        let mut msg = ZmqMessage::from(topic.as_str());
        msg.push_back(payload.into_bytes().into());

        self.pub_socket.send(msg).await?;
        debug!(symbol = %tick.symbol, topic = %topic, "Tick published");

        Ok(())
    }

    /// Publish order result to PUB socket for trading-engine.
    async fn publish_order_result(&mut self, result: &OrderResult) -> anyhow::Result<()> {
        let topic = format!("order_result:{}", result.order_id);
        let payload = serde_json::to_string(result)?;

        let mut msg = ZmqMessage::from(topic.as_str());
        msg.push_back(payload.into_bytes().into());

        self.pub_socket.send(msg).await?;
        info!(order_id = %result.order_id, topic = %topic, "Order result published");

        Ok(())
    }

    /// Get next pending order from queue (non-blocking).
    async fn get_pending_order(&mut self) -> Option<Order> {
        self.order_rx.try_recv().ok()
    }

    /// Convert order to ACK response for delivery via REP socket.
    fn order_to_ack_response(&self, order: &Order) -> AckResponse {
        // Return order details in the response message field
        // The MT5 EA will parse this to execute the order
        AckResponse {
            msg_type: MessageType::Order,
            status: "order".to_string(),
            message: serde_json::to_string(order).ok(),
        }
    }

    /// Create ZMQ response message from AckResponse.
    fn create_response(&self, response: &AckResponse) -> ZmqMessage {
        let json = serde_json::to_string(response).unwrap_or_else(|_| {
            r#"{"type":"error","status":"error","message":"Serialization failed"}"#.to_string()
        });
        ZmqMessage::from(json)
    }

    /// Get reference to tick handler.
    pub fn tick_handler(&self) -> &TickHandler {
        &self.tick_handler
    }

    /// Get reference to order handler.
    pub fn order_handler(&self) -> &OrderHandler {
        &self.order_handler
    }

    /// Get order sender for external order submission (used in tests).
    pub fn order_sender(&self) -> mpsc::Sender<Order> {
        self.order_tx.clone()
    }

    /// Get heartbeat map for external monitoring (used in tests).
    pub fn heartbeat_map(&self) -> Arc<RwLock<HashMap<String, Instant>>> {
        self.last_heartbeat.clone()
    }
}
