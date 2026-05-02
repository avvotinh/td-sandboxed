//! Integration tests for MT5 Bridge.

use mt5_bridge::config::Config;
use mt5_bridge::handlers::{OrderHandler, TickHandler};
use mt5_bridge::models::{Order, OrderResult, OrderSide, OrderStatus, Tick};
use mt5_bridge::protocol::{AckResponse, Heartbeat, IncomingMessage, MessageType};

#[test]
fn test_config_defaults() {
    let config = Config::default();
    assert_eq!(config.zmq_req_port, 5555);
    assert_eq!(config.zmq_pub_port, 5556);
    assert_eq!(config.zmq_sub_port, 5557);
}

#[test]
fn test_config_endpoints() {
    let config = Config::default();
    assert_eq!(config.req_endpoint(), "tcp://0.0.0.0:5555");
    assert_eq!(config.pub_endpoint(), "tcp://0.0.0.0:5556");
    assert_eq!(config.sub_endpoint(), "tcp://0.0.0.0:5557");
}

#[test]
fn test_tick_spread_calculation() {
    let tick = Tick {
        account_id: "test-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };
    assert!((tick.spread() - 0.20).abs() < 0.001);
}

#[test]
fn test_tick_topic() {
    let tick = Tick {
        account_id: "test-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };
    assert_eq!(tick.topic(), "tick:XAUUSD");
}

#[test]
fn test_order_serialization() {
    let order = Order {
        action: OrderSide::Buy,
        symbol: "XAUUSD".to_string(),
        volume: 0.1,
        price: 1850.45,
        sl: Some(1845.00),
        tp: Some(1860.00),
        order_id: "ORDER-123".to_string(),
        account_id: "ftmo-gold-001".to_string(),
    };

    let json = serde_json::to_string(&order).unwrap();
    assert!(json.contains("XAUUSD"));
    assert!(json.contains("ORDER-123"));
}

#[test]
fn test_ack_response_ok() {
    let ack = AckResponse::ok();
    assert_eq!(ack.msg_type, MessageType::Ack);
    assert_eq!(ack.status, "ok");
    assert!(ack.message.is_none());
}

#[test]
fn test_ack_response_error() {
    let ack = AckResponse::error("Test error");
    assert_eq!(ack.msg_type, MessageType::Error);
    assert_eq!(ack.status, "error");
    assert_eq!(ack.message, Some("Test error".to_string()));
}

// ==================== Handler Tests ====================

#[test]
fn test_tick_handler_returns_ack() {
    let handler = TickHandler::new();
    let tick = Tick {
        account_id: "test-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };

    let response = handler.handle(&tick);
    assert_eq!(response.msg_type, MessageType::Ack);
    assert_eq!(response.status, "ok");
}

#[test]
fn test_tick_handler_default() {
    let handler = TickHandler::default();
    let tick = Tick {
        account_id: "ftmo-gold-001".to_string(),
        symbol: "EURUSD".to_string(),
        bid: 1.0850,
        ask: 1.0852,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };

    let response = handler.handle(&tick);
    assert_eq!(response.status, "ok");
}

#[tokio::test]
async fn test_order_handler_test_mode_rejects() {
    let handler = OrderHandler::new();
    let order = Order {
        action: OrderSide::Buy,
        symbol: "XAUUSD".to_string(),
        volume: 0.1,
        price: 1850.45,
        sl: Some(1845.00),
        tp: Some(1860.00),
        order_id: "ORDER-123".to_string(),
        account_id: "ftmo-gold-001".to_string(),
    };

    let result = handler.handle(&order).await;
    // Handler test mode returns Rejected (actual orders go through ZmqServer)
    assert_eq!(result.status, OrderStatus::Rejected);
    assert_eq!(result.order_id, "ORDER-123");
    assert!(result.error.is_some());
    assert!(result.error.unwrap().contains("test mode"));
}

#[tokio::test]
async fn test_order_handler_default() {
    let handler = OrderHandler::default();
    let order = Order {
        action: OrderSide::Sell,
        symbol: "EURUSD".to_string(),
        volume: 0.5,
        price: 1.0850,
        sl: None,
        tp: None,
        order_id: "ORDER-456".to_string(),
        account_id: "5ers-eur-002".to_string(),
    };

    let result = handler.handle(&order).await;
    assert_eq!(result.status, OrderStatus::Rejected);
    assert!(result.timestamp.len() > 0);
}

// ==================== Heartbeat Tests ====================

#[test]
fn test_heartbeat_creation() {
    let heartbeat = Heartbeat {
        account_id: "ftmo-gold-001".to_string(),
        timestamp: "2025-12-22T10:00:00Z".to_string(),
    };

    assert_eq!(heartbeat.account_id, "ftmo-gold-001");
    assert_eq!(heartbeat.timestamp, "2025-12-22T10:00:00Z");
}

#[test]
fn test_heartbeat_serialization() {
    let heartbeat = Heartbeat {
        account_id: "test-account".to_string(),
        timestamp: "2025-12-22T10:00:00Z".to_string(),
    };

    let json = serde_json::to_string(&heartbeat).unwrap();
    assert!(json.contains("test-account"));
    assert!(json.contains("2025-12-22T10:00:00Z"));

    let deserialized: Heartbeat = serde_json::from_str(&json).unwrap();
    assert_eq!(deserialized.account_id, heartbeat.account_id);
}

#[test]
fn test_incoming_heartbeat_message() {
    let json =
        r#"{"type":"heartbeat","account_id":"ftmo-gold-001","timestamp":"2025-12-22T10:00:00Z"}"#;

    let msg: IncomingMessage = serde_json::from_str(json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Heartbeat);

    let heartbeat: Heartbeat = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(heartbeat.account_id, "ftmo-gold-001");
}

// ==================== Order Result Tests ====================

#[test]
fn test_order_result_filled() {
    let result = OrderResult {
        order_id: "ORDER-123".to_string(),
        status: OrderStatus::Filled,
        fill_price: Some(1850.47),
        slippage: Some(0.02),
        timestamp: "2025-12-22T10:00:00Z".to_string(),
        error: None,
    };

    let json = serde_json::to_string(&result).unwrap();
    assert!(json.contains("\"status\":\"filled\""));
    assert!(json.contains("1850.47"));
    assert!(!json.contains("\"error\""));
}

#[test]
fn test_order_result_partially_filled() {
    let result = OrderResult {
        order_id: "ORDER-456".to_string(),
        status: OrderStatus::PartiallyFilled,
        fill_price: Some(1850.00),
        slippage: Some(0.05),
        timestamp: "2025-12-22T10:00:00Z".to_string(),
        error: None,
    };

    assert_eq!(result.status, OrderStatus::PartiallyFilled);
    assert_eq!(result.fill_price, Some(1850.00));
}

#[test]
fn test_order_result_error() {
    let result = OrderResult {
        order_id: "ORDER-789".to_string(),
        status: OrderStatus::Error,
        fill_price: None,
        slippage: None,
        timestamp: "2025-12-22T10:00:00Z".to_string(),
        error: Some("Connection timeout".to_string()),
    };

    let json = serde_json::to_string(&result).unwrap();
    assert!(json.contains("\"status\":\"error\""));
    assert!(json.contains("Connection timeout"));
}

// ==================== Complete Message Flow Tests ====================

#[test]
fn test_tick_message_flow() {
    // Simulate complete tick message as sent by MT5 EA
    let tick_json = r#"{
        "type": "tick",
        "account_id": "ftmo-gold-001",
        "symbol": "XAUUSD",
        "bid": 1850.25,
        "ask": 1850.45,
        "timestamp": "2025-12-22T10:00:00Z"
    }"#;

    // Parse incoming message
    let msg: IncomingMessage = serde_json::from_str(tick_json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Tick);

    // Extract tick
    let tick: Tick = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(tick.topic(), "tick:XAUUSD");

    // Verify tick handler returns ACK
    let handler = TickHandler::new();
    let response = handler.handle(&tick);
    assert_eq!(response.msg_type, MessageType::Ack);
    assert_eq!(response.status, "ok");
}

#[test]
fn test_order_command_flow() {
    // Simulate order command as sent by trading-engine
    let order_json = r#"{
        "type": "order",
        "action": "BUY",
        "symbol": "XAUUSD",
        "volume": 0.1,
        "price": 1850.45,
        "sl": 1845.00,
        "tp": 1860.00,
        "order_id": "ORDER-UUID-123",
        "account_id": "ftmo-gold-001"
    }"#;

    // Parse incoming message
    let msg: IncomingMessage = serde_json::from_str(order_json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Order);

    // Extract order
    let order: Order = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(order.order_id, "ORDER-UUID-123");
    assert_eq!(order.action, OrderSide::Buy);
}

#[test]
fn test_order_result_flow() {
    // Simulate order result as sent by MT5 EA
    let result_json = r#"{
        "type": "order_result",
        "order_id": "ORDER-UUID-123",
        "status": "filled",
        "fill_price": 1850.47,
        "slippage": 0.02,
        "timestamp": "2025-12-22T10:00:00.456Z"
    }"#;

    // Parse incoming message
    let msg: IncomingMessage = serde_json::from_str(result_json).unwrap();
    assert_eq!(msg.msg_type, MessageType::OrderResult);

    // Extract result
    let result: OrderResult = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(result.status, OrderStatus::Filled);
    assert_eq!(result.fill_price, Some(1850.47));
}

// ==================== Config Endpoint Tests ====================

#[test]
fn test_config_custom_ports() {
    let config = Config {
        zmq_req_port: 6555,
        zmq_pub_port: 6556,
        zmq_sub_port: 6557,
        bind_address: "127.0.0.1".to_string(),
    };

    assert_eq!(config.req_endpoint(), "tcp://127.0.0.1:6555");
    assert_eq!(config.pub_endpoint(), "tcp://127.0.0.1:6556");
    assert_eq!(config.sub_endpoint(), "tcp://127.0.0.1:6557");
}

// ==================== Error Response Tests ====================

#[test]
fn test_error_response_json_format() {
    let error = AckResponse::error("Invalid symbol format");
    let json = serde_json::to_string(&error).unwrap();

    // Verify JSON structure
    assert!(json.contains("\"type\":\"error\""));
    assert!(json.contains("\"status\":\"error\""));
    assert!(json.contains("Invalid symbol format"));
}

#[test]
fn test_error_response_deserialization() {
    let json = r#"{"type":"error","status":"error","message":"Test error"}"#;
    let response: AckResponse = serde_json::from_str(json).unwrap();

    assert_eq!(response.msg_type, MessageType::Error);
    assert_eq!(response.status, "error");
    assert_eq!(response.message, Some("Test error".to_string()));
}
