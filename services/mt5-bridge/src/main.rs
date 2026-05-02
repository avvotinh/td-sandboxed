//! MT5 Bridge Service - Entry Point
//!
//! High-performance ZeroMQ bridge for MetaTrader 5 communication.
//! This service handles tick data forwarding and order execution.

use mt5_bridge::{config::Config, zmq_server::ZmqServer};
use tracing::{error, info, Level};
use tracing_subscriber::EnvFilter;

#[tokio::main]
async fn main() -> anyhow::Result<()> {
    // Initialize tracing
    tracing_subscriber::fmt()
        .with_env_filter(EnvFilter::from_default_env().add_directive(Level::INFO.into()))
        .json()
        .init();

    info!(version = env!("CARGO_PKG_VERSION"), "MT5 Bridge starting");

    // Load configuration
    let config = Config::load()?;
    info!(
        req_port = config.zmq_req_port,
        pub_port = config.zmq_pub_port,
        sub_port = config.zmq_sub_port,
        "Configuration loaded"
    );

    // Create and run server
    let mut server = ZmqServer::new(config).await?;

    // Handle shutdown signals (SIGINT and SIGTERM)
    let shutdown = async {
        let ctrl_c = tokio::signal::ctrl_c();

        #[cfg(unix)]
        let terminate = async {
            tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate())
                .expect("Failed to install SIGTERM handler")
                .recv()
                .await;
        };

        #[cfg(not(unix))]
        let terminate = std::future::pending::<()>();

        tokio::select! {
            _ = ctrl_c => info!("SIGINT received"),
            _ = terminate => info!("SIGTERM received"),
        }
        info!("Shutdown signal received");
    };

    tokio::select! {
        result = server.run() => {
            if let Err(e) = result {
                error!(error = %e, "Server error");
                return Err(e);
            }
        }
        _ = shutdown => {
            info!("Initiating graceful shutdown");
        }
    }

    info!("MT5 Bridge stopped");
    Ok(())
}
