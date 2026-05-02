//! Data models for MT5 Bridge.

pub mod order;
pub mod tick;

pub use order::{Order, OrderResult, OrderSide, OrderStatus};
pub use tick::Tick;
