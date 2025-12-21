//! Configuration module for MT5 Bridge.

use serde::Deserialize;
use thiserror::Error;

/// Configuration errors (reserved for future validation).
#[derive(Debug, Error)]
#[allow(dead_code)]
pub enum ConfigError {
    #[error("Environment variable {0} not set")]
    MissingEnv(String),
    #[error("Invalid port number: {0}")]
    InvalidPort(String),
}

/// MT5 Bridge configuration.
///
/// NOTE: This scaffold supports single-port configuration.
/// For multi-account support (Epic 2+), this will be extended to support
/// multiple port ranges per MT5 instance (e.g., 5555/5565/5575 for FTMO/5ers/Personal).
/// See Architecture docs: Multi-Account MT5 Deployment (Option 1).
#[derive(Debug, Clone, Deserialize)]
pub struct Config {
    /// ZeroMQ REQ/REP port for MT5 EA commands (default: 5555)
    pub zmq_req_port: u16,
    /// ZeroMQ PUB port for tick data (default: 5556)
    pub zmq_pub_port: u16,
    /// ZeroMQ SUB port for order commands (default: 5557)
    pub zmq_sub_port: u16,
    /// Bind address (default: 0.0.0.0)
    pub bind_address: String,
}

impl Default for Config {
    fn default() -> Self {
        Self {
            zmq_req_port: 5555,
            zmq_pub_port: 5556,
            zmq_sub_port: 5557,
            bind_address: "0.0.0.0".to_string(),
        }
    }
}

impl Config {
    /// Load configuration from environment variables.
    pub fn load() -> anyhow::Result<Self> {
        let config = Self {
            zmq_req_port: std::env::var("ZMQ_REQ_PORT")
                .unwrap_or_else(|_| "5555".to_string())
                .parse()?,
            zmq_pub_port: std::env::var("ZMQ_PUB_PORT")
                .unwrap_or_else(|_| "5556".to_string())
                .parse()?,
            zmq_sub_port: std::env::var("ZMQ_SUB_PORT")
                .unwrap_or_else(|_| "5557".to_string())
                .parse()?,
            bind_address: std::env::var("BIND_ADDRESS").unwrap_or_else(|_| "0.0.0.0".to_string()),
        };
        Ok(config)
    }

    /// Get REQ/REP endpoint string.
    pub fn req_endpoint(&self) -> String {
        format!("tcp://{}:{}", self.bind_address, self.zmq_req_port)
    }

    /// Get PUB endpoint string.
    pub fn pub_endpoint(&self) -> String {
        format!("tcp://{}:{}", self.bind_address, self.zmq_pub_port)
    }

    /// Get SUB endpoint string.
    pub fn sub_endpoint(&self) -> String {
        format!("tcp://{}:{}", self.bind_address, self.zmq_sub_port)
    }
}
