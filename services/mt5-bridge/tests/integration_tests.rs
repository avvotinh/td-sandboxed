//! Integration tests for MT5 Bridge.

use mt5_bridge::config::Config;
use mt5_bridge::handlers::{OrderHandler, TickHandler};
use mt5_bridge::models::{Order, OrderSide, OrderStatus, Tick};
use mt5_bridge::protocol::{AckResponse, MessageType};

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
async fn test_order_handler_scaffold_rejects() {
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
    // Scaffold mode always returns Rejected with explanation
    assert_eq!(result.status, OrderStatus::Rejected);
    assert_eq!(result.order_id, "ORDER-123");
    assert!(result.error.is_some());
    assert!(result.error.unwrap().contains("scaffold"));
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
