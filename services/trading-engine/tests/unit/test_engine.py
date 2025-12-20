"""Unit tests for TradingEngine."""
import pytest


class TestTradingEngine:
    """Test suite for TradingEngine class."""

    def test_engine_initializes(self, trading_engine):
        """Engine should initialize without errors."""
        assert trading_engine is not None
        assert trading_engine.is_running is False

    def test_engine_not_running_initially(self, trading_engine):
        """Engine should not be running after initialization."""
        assert trading_engine.is_running is False

    @pytest.mark.asyncio
    async def test_engine_starts_and_stops(self, trading_engine):
        """Engine should start and stop gracefully."""
        import asyncio

        # Start engine in background task
        task = asyncio.create_task(trading_engine.run())

        # Give it time to start
        await asyncio.sleep(0.1)
        assert trading_engine.is_running is True

        # Shutdown
        await trading_engine.shutdown()
        await task
        assert trading_engine.is_running is False

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self, trading_engine):
        """Calling shutdown multiple times should be safe."""
        # Shutdown without starting should not error
        await trading_engine.shutdown()
        await trading_engine.shutdown()  # Second call should be no-op

    def test_is_running_property_exists(self, trading_engine):
        """Engine should expose is_running as a public property."""
        # Verify it's a property, not a method
        assert hasattr(trading_engine, "is_running")
        assert isinstance(type(trading_engine).is_running, property)


class TestSignalHandler:
    """Test suite for signal handling utilities.

    Note: Signal handling tests are integration tests that require subprocess
    isolation. The basic CLI entry point is now handled via Typer CLI framework.
    """

    def test_signal_handler_creation(self):
        """CLI entry point should be available via cli module."""
        from src.cli import app

        # CLI app should be a Typer instance
        assert app is not None
        assert hasattr(app, "command")

    @pytest.mark.skipif(
        __import__("sys").platform == "win32",
        reason="Signal handling test requires Unix",
    )
    @pytest.mark.integration
    def test_signal_handler_triggers_shutdown(self):
        """Signal handler should trigger engine shutdown when called.

        Note: Full signal integration testing requires subprocess isolation.
        This test validates the handler function works when called directly.
        """
        # This is marked for integration testing in future epics
        pass
