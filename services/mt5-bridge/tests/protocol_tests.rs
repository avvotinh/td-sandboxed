//! Protocol serialization and deserialization tests.

use mt5_bridge::models::{Order, OrderResult, OrderSide, OrderStatus, Tick};
use mt5_bridge::protocol::MessageType;

#[test]
fn test_tick_serialization_roundtrip() {
    let tick = Tick {
        account_id: "ftmo-gold-001".to_string(),
        symbol: "XAUUSD".to_string(),
        bid: 1850.25,
        ask: 1850.45,
        timestamp: "2025-12-19T14:32:15.123Z".to_string(),
    };

    let json = serde_json::to_string(&tick).unwrap();
    let deserialized: Tick = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.account_id, tick.account_id);
    assert_eq!(deserialized.symbol, tick.symbol);
    assert!((deserialized.bid - tick.bid).abs() < 0.001);
}

#[test]
fn test_order_serialization_roundtrip() {
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
    let deserialized: Order = serde_json::from_str(&json).unwrap();

    assert_eq!(deserialized.order_id, order.order_id);
    assert_eq!(deserialized.action, OrderSide::Buy);
}

#[test]
fn test_message_type_serialization() {
    let msg_type = MessageType::Tick;
    let json = serde_json::to_string(&msg_type).unwrap();
    assert_eq!(json, "\"tick\"");

    let msg_type = MessageType::Order;
    let json = serde_json::to_string(&msg_type).unwrap();
    assert_eq!(json, "\"order\"");
}

#[test]
fn test_order_result_with_error() {
    let result = OrderResult {
        order_id: "ORDER-123".to_string(),
        status: OrderStatus::Rejected,
        fill_price: None,
        slippage: None,
        timestamp: "2025-12-19T14:32:15.456Z".to_string(),
        error: Some("Insufficient margin".to_string()),
    };

    let json = serde_json::to_string(&result).unwrap();
    assert!(json.contains("rejected"));
    assert!(json.contains("Insufficient margin"));
}

#[test]
fn test_order_side_serialization() {
    let buy = OrderSide::Buy;
    let sell = OrderSide::Sell;

    assert_eq!(serde_json::to_string(&buy).unwrap(), "\"BUY\"");
    assert_eq!(serde_json::to_string(&sell).unwrap(), "\"SELL\"");
}

#[test]
fn test_order_status_serialization() {
    assert_eq!(
        serde_json::to_string(&OrderStatus::Filled).unwrap(),
        "\"filled\""
    );
    assert_eq!(
        serde_json::to_string(&OrderStatus::PartiallyFilled).unwrap(),
        "\"partially_filled\""
    );
    assert_eq!(
        serde_json::to_string(&OrderStatus::Rejected).unwrap(),
        "\"rejected\""
    );
    assert_eq!(
        serde_json::to_string(&OrderStatus::Error).unwrap(),
        "\"error\""
    );
}

#[test]
fn test_order_without_optional_fields() {
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

    let json = serde_json::to_string(&order).unwrap();
    // sl and tp should not be present in JSON when None
    assert!(!json.contains("\"sl\""));
    assert!(!json.contains("\"tp\""));
}
