//! Unit tests for ZeroMQ server operations.
//!
//! Tests message parsing, response generation, and protocol handling.

use mt5_bridge::models::{Order, OrderResult, OrderSide, OrderStatus, Tick};
use mt5_bridge::protocol::{AckResponse, Heartbeat, IncomingMessage, MessageType};

// ==================== Message Parsing Tests ====================

#[test]
fn test_tick_message_parsing() {
    let json = r#"{
        "type": "tick",
        "account_id": "test-001",
        "symbol": "XAUUSD",
        "bid": 1850.25,
        "ask": 1850.45,
        "timestamp": "2025-12-03T14:32:15.123Z"
    }"#;

    let msg: IncomingMessage = serde_json::from_str(json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Tick);

    let tick: Tick = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(tick.symbol, "XAUUSD");
    assert_eq!(tick.account_id, "test-001");
    assert!((tick.bid - 1850.25).abs() < 0.001);
    assert!((tick.ask - 1850.45).abs() < 0.001);
    assert!((tick.spread() - 0.20).abs() < 0.001);
}

#[test]
fn test_heartbeat_parsing() {
    let json =
        r#"{"type": "heartbeat", "account_id": "test-001", "timestamp": "2025-12-22T10:00:00Z"}"#;
    let msg: IncomingMessage = serde_json::from_str(json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Heartbeat);

    let heartbeat: Heartbeat = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(heartbeat.account_id, "test-001");
    assert_eq!(heartbeat.timestamp, "2025-12-22T10:00:00Z");
}

#[test]
fn test_order_message_parsing() {
    let json = r#"{
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

    let msg: IncomingMessage = serde_json::from_str(json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Order);

    let order: Order = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(order.order_id, "ORDER-UUID-123");
    assert_eq!(order.account_id, "ftmo-gold-001");
    assert_eq!(order.action, OrderSide::Buy);
    assert_eq!(order.symbol, "XAUUSD");
    assert!((order.volume - 0.1).abs() < 0.001);
}

#[test]
fn test_order_result_parsing() {
    let json = r#"{
        "type": "order_result",
        "order_id": "ORDER-UUID-123",
        "status": "filled",
        "fill_price": 1850.47,
        "slippage": 0.02,
        "timestamp": "2025-12-03T14:32:15.456Z"
    }"#;

    let msg: IncomingMessage = serde_json::from_str(json).unwrap();
    assert_eq!(msg.msg_type, MessageType::OrderResult);

    let result: OrderResult = serde_json::from_value(msg.payload).unwrap();
    assert_eq!(result.order_id, "ORDER-UUID-123");
    assert_eq!(result.status, OrderStatus::Filled);
    assert_eq!(result.fill_price, Some(1850.47));
    assert_eq!(result.slippage, Some(0.02));
}

// ==================== Response Serialization Tests ====================

#[test]
fn test_ack_response_ok_serialization() {
    let ack = AckResponse::ok();
    let json = serde_json::to_string(&ack).unwrap();

    assert!(json.contains("\"status\":\"ok\""));
    assert!(json.contains("\"type\":\"ack\""));
    assert!(!json.contains("\"message\""));
}

#[test]
fn test_ack_response_error_serialization() {
    let err = AckResponse::error("Test error message");
    let json = serde_json::to_string(&err).unwrap();

    assert!(json.contains("\"status\":\"error\""));
    assert!(json.contains("\"type\":\"error\""));
    assert!(json.contains("Test error message"));
}

#[test]
fn test_ack_response_deserialization() {
    let json = r#"{"type":"ack","status":"ok"}"#;
    let ack: AckResponse = serde_json::from_str(json).unwrap();

    assert_eq!(ack.msg_type, MessageType::Ack);
    assert_eq!(ack.status, "ok");
    assert!(ack.message.is_none());
}

// ==================== Topic Generation Tests ====================

#[test]
fn test_tick_topic_generation() {
    let tick = Tick {
        account_id: "test-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-03T14:32:15.123Z".to_string(),
    };
    assert_eq!(tick.topic(), "tick:XAUUSD");
}

#[test]
fn test_tick_topic_with_different_symbols() {
    let symbols = vec!["EURUSD", "GBPJPY", "BTCUSD", "US30"];

    for symbol in symbols {
        let tick = Tick {
            account_id: "test-001".to_string(),
            symbol: symbol.to_string(),
            bid: 100.0,
            ask: 100.1,
            timestamp: "2025-12-22T10:00:00Z".to_string(),
        };
        assert_eq!(tick.topic(), format!("tick:{}", symbol));
    }
}

// ==================== Error Handling Tests ====================

#[test]
fn test_malformed_json_handling() {
    let invalid_json = r#"{"type": "tick", "symbol": "broken"#;
    let result = serde_json::from_str::<IncomingMessage>(invalid_json);
    assert!(result.is_err());
}

#[test]
fn test_missing_required_field() {
    // Missing account_id in tick
    let json = r#"{
        "type": "tick",
        "symbol": "XAUUSD",
        "bid": 1850.25,
        "ask": 1850.45,
        "timestamp": "2025-12-03T14:32:15.123Z"
    }"#;

    let msg: IncomingMessage = serde_json::from_str(json).unwrap();
    assert_eq!(msg.msg_type, MessageType::Tick);

    // Tick parsing should fail due to missing account_id
    let tick_result = serde_json::from_value::<Tick>(msg.payload);
    assert!(tick_result.is_err());
}

#[test]
fn test_unknown_message_type() {
    let json = r#"{"type": "unknown_type", "data": "test"}"#;
    let result = serde_json::from_str::<IncomingMessage>(json);
    // Unknown message type should fail to deserialize
    assert!(result.is_err());
}

// ==================== Heartbeat Model Tests ====================

#[test]
fn test_heartbeat_serialization_roundtrip() {
    let heartbeat = Heartbeat {
        account_id: "ftmo-gold-001".to_string(),
        timestamp: "2025-12-22T10:00:00Z".to_string(),
    };

    let json = serde_json::to_string(&heartbeat).unwrap();
    let deserialized: Heartbeat = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.account_id, heartbeat.account_id);
    assert_eq!(deserialized.timestamp, heartbeat.timestamp);
}

// ==================== Order Response Tests ====================

#[test]
fn test_order_as_ack_response() {
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

    // Simulate how ZmqServer converts order to response
    let response = AckResponse {
        msg_type: MessageType::Order,
        status: "order".to_string(),
        message: serde_json::to_string(&order).ok(),
    };

    let json = serde_json::to_string(&response).unwrap();
    assert!(json.contains("\"type\":\"order\""));
    assert!(json.contains("ORDER-123"));
    assert!(json.contains("XAUUSD"));
}

// ==================== Message Type Tests ====================

#[test]
fn test_all_message_types() {
    let types = vec![
        ("tick", MessageType::Tick),
        ("order", MessageType::Order),
        ("order_result", MessageType::OrderResult),
        ("heartbeat", MessageType::Heartbeat),
        ("ack", MessageType::Ack),
        ("error", MessageType::Error),
    ];

    for (json_value, expected_type) in types {
        let json = format!("\"{}\"", json_value);
        let msg_type: MessageType = serde_json::from_str(&json).unwrap();
        assert_eq!(msg_type, expected_type);
    }
}

#[test]
fn test_message_type_serialization() {
    assert_eq!(
        serde_json::to_string(&MessageType::Tick).unwrap(),
        "\"tick\""
    );
    assert_eq!(
        serde_json::to_string(&MessageType::Heartbeat).unwrap(),
        "\"heartbeat\""
    );
    assert_eq!(
        serde_json::to_string(&MessageType::OrderResult).unwrap(),
        "\"order_result\""
    );
}

// ==================== Spread Calculation Tests ====================

#[test]
fn test_tick_spread_positive() {
    let tick = Tick {
        account_id: "test".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-22T10:00:00Z".to_string(),
    };
    assert!((tick.spread() - 0.20).abs() < 0.0001);
}

#[test]
fn test_tick_spread_zero() {
    let tick = Tick {
        account_id: "test".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.00,
        ask: 1850.00,
        timestamp: "2025-12-22T10:00:00Z".to_string(),
    };
    assert!((tick.spread()).abs() < 0.0001);
}

#[test]
fn test_tick_spread_large() {
    let tick = Tick {
        account_id: "test".to_string(),
        symbol: "BTCUSD".to_string(),
        bid: 50000.00,
        ask: 50100.00,
        timestamp: "2025-12-22T10:00:00Z".to_string(),
    };
    assert!((tick.spread() - 100.00).abs() < 0.0001);
}
