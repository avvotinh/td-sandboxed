"""Trading Engine Entry Point."""
import asyncio
import logging
import signal
import sys

from src.engine import TradingEngine


def setup_logging() -> None:
    """Configure structured logging."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )


def _create_signal_handler(engine: TradingEngine) -> callable:
    """Create a signal handler that triggers engine shutdown.

    Args:
        engine: The TradingEngine instance to shutdown.

    Returns:
        A callable that can be used as a signal handler.
    """
    def handler() -> None:
        asyncio.create_task(engine.shutdown())
    return handler


def main() -> None:
    """Main entry point for the trading engine."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info("Trading Engine starting...")

    engine = TradingEngine()

    # Graceful shutdown handling
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    # Platform-safe signal handling (add_signal_handler is Unix-only)
    if sys.platform != "win32":
        shutdown_handler = _create_signal_handler(engine)
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, shutdown_handler)
    # On Windows, KeyboardInterrupt is caught in the try/except below

    try:
        loop.run_until_complete(engine.run())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received")
    finally:
        loop.run_until_complete(engine.shutdown())
        loop.close()
        logger.info("Trading Engine stopped")


if __name__ == "__main__":
    main()
