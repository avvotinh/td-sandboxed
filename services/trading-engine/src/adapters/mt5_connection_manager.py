"""MT5 Connection Manager - Per-account ZeroMQ connection management.

This module provides isolated connection management for multi-account trading.
Each account gets its own ZmqAdapter instance connected to its MT5 bridge,
ensuring connection failures are isolated and don't cascade.

Example:
    from src.adapters.mt5_connection_manager import MT5ConnectionManager
    from src.accounts.account_manager import AccountManager

    account_manager = AccountManager(redis_manager)
    conn_manager = MT5ConnectionManager(account_manager)

    # Start connections for active accounts
    await conn_manager.start_all_connections()

    # Send order via correct account's connection
    result = await conn_manager.send_order(order)

    # Check connection health
    health = conn_manager.get_health("ftmo-gold-001")
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from .zmq_adapter import ZmqAdapter, ZmqConfig

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from ..accounts.models import AccountConfig
    from .zmq_models import Order, OrderResult

logger = logging.getLogger(__name__)


@dataclass
class ConnectionHealth:
    """Connection health status for an account.

    Attributes:
        connected: Whether currently connected
        last_heartbeat: Last successful heartbeat time
        last_error: Most recent error message (if any)
        reconnect_attempts: Number of reconnection attempts since last success
    """

    connected: bool = False
    last_heartbeat: datetime | None = None
    last_error: str | None = None
    reconnect_attempts: int = 0


class MT5ConnectionManager:
    """Manages per-account MT5 connections via ZeroMQ.

    Provides isolated connection management for multi-account trading:
    - Each account gets its own ZmqAdapter
    - Connection failures are isolated per account
    - Reconnection uses exponential backoff per account
    - Order routing by account_id

    Attributes:
        RECONNECT_DELAYS: Exponential backoff sequence in seconds
    """

    RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]

    def __init__(self, account_manager: AccountManager) -> None:
        """Initialize connection manager.

        Args:
            account_manager: AccountManager for account configurations
        """
        self._account_manager = account_manager
        self._connections: dict[str, ZmqAdapter] = {}
        self._health: dict[str, ConnectionHealth] = {}
        self._pending_orders: dict[str, set[str]] = {}
        self._reconnection_tasks: dict[str, asyncio.Task] = {}
        self._tick_receivers: dict[str, asyncio.Task] = {}
        self._running = False

    async def start_all_connections(self) -> None:
        """Start connections for all active accounts.

        Raises:
            ValueError: If port conflicts detected between accounts
        """
        # Validate no port conflicts before starting any connections
        self._validate_port_conflicts()

        self._running = True
        for account_id, account in self._account_manager._accounts.items():
            if account.status == "active":
                await self.start_connection(account_id)

    async def stop_all_connections(self) -> None:
        """Stop all connections gracefully."""
        self._running = False
        for account_id in list(self._connections.keys()):
            await self.stop_connection(account_id)

    async def start_connection(self, account_id: str) -> None:
        """Start connection for a specific account.

        Args:
            account_id: Account to start connection for

        Raises:
            KeyError: If account not found
        """
        if account_id in self._connections:
            logger.warning(f"Connection already exists for {account_id}")
            return

        account = self._account_manager._accounts.get(account_id)
        if not account:
            raise KeyError(f"Account {account_id} not found")

        # Initialize health tracking
        self._health[account_id] = ConnectionHealth()
        self._pending_orders[account_id] = set()

        # Create ZmqAdapter with account-specific config
        config = self._create_zmq_config(account)
        adapter = ZmqAdapter(config)

        try:
            await adapter.connect()
            self._connections[account_id] = adapter
            self._update_health(account_id, connected=True)

            # Start tick receiver in background
            task = asyncio.create_task(
                self._tick_receiver_loop(account_id, adapter),
                name=f"tick-receiver-{account_id}",
            )
            self._tick_receivers[account_id] = task

            logger.info(f"Connection started for account {account_id}")

        except Exception as e:
            self._update_health(account_id, connected=False, error=str(e))
            logger.error(f"Failed to connect account {account_id}: {e}")
            # Schedule reconnection
            self._schedule_reconnection(account_id)

    async def stop_connection(self, account_id: str) -> None:
        """Stop connection for a specific account.

        Args:
            account_id: Account to stop connection for
        """
        # Cancel tick receiver
        if account_id in self._tick_receivers:
            self._tick_receivers[account_id].cancel()
            try:
                await self._tick_receivers[account_id]
            except asyncio.CancelledError:
                pass
            del self._tick_receivers[account_id]

        # Cancel reconnection task if running
        if account_id in self._reconnection_tasks:
            self._reconnection_tasks[account_id].cancel()
            try:
                await self._reconnection_tasks[account_id]
            except asyncio.CancelledError:
                pass
            del self._reconnection_tasks[account_id]

        # Disconnect adapter
        if account_id in self._connections:
            await self._connections[account_id].disconnect()
            del self._connections[account_id]

        self._update_health(account_id, connected=False)
        logger.info(f"Connection stopped for account {account_id}")

    def get_connection(self, account_id: str) -> ZmqAdapter | None:
        """Get connection for an account.

        Args:
            account_id: Account to get connection for

        Returns:
            ZmqAdapter if connected, None otherwise
        """
        return self._connections.get(account_id)

    def get_health(self, account_id: str) -> ConnectionHealth:
        """Get connection health for an account.

        Args:
            account_id: Account to get health for

        Returns:
            ConnectionHealth status
        """
        return self._health.get(account_id, ConnectionHealth())

    def get_all_connection_health(self) -> dict[str, ConnectionHealth]:
        """Get connection health for all accounts.

        Returns:
            Dict mapping account_id to ConnectionHealth
        """
        return dict(self._health)

    async def send_order(
        self,
        order: Order,
        timeout: float = 5.0,
    ) -> OrderResult:
        """Send order via the correct account's connection.

        Routes order to the connection matching order.account_id.
        Includes idempotency check to prevent duplicate orders.

        Args:
            order: Order to send
            timeout: Timeout in seconds

        Returns:
            OrderResult from mt5-bridge

        Raises:
            RuntimeError: If account not connected
            ValueError: If duplicate order_id detected
        """
        account_id = order.account_id

        # Get adapter first - fail fast if not connected
        adapter = self._connections.get(account_id)
        if not adapter:
            raise RuntimeError(f"No connection for account {account_id}")

        # Idempotency check - use setdefault to handle edge cases robustly
        pending = self._pending_orders.setdefault(account_id, set())
        if order.order_id in pending:
            logger.warning(
                f"Duplicate order_id {order.order_id} for {account_id} - rejecting"
            )
            raise ValueError(f"Duplicate order_id: {order.order_id}")

        # Track pending order
        pending.add(order.order_id)

        try:
            result = await adapter.send_order_and_wait(order, timeout=timeout)
            return result
        finally:
            # Remove from pending (whether success or failure)
            pending.discard(order.order_id)

    def _create_zmq_config(self, account: AccountConfig) -> ZmqConfig:
        """Create ZmqConfig from account configuration.

        Args:
            account: Account configuration

        Returns:
            ZmqConfig for the account's MT5 bridge
        """
        mt5_config = account.mt5

        # Use account-specific ports from MT5Config fields
        return ZmqConfig(
            bridge_host=mt5_config.zmq_host,
            tick_port=mt5_config.zmq_tick_port,
            order_port=mt5_config.zmq_order_port,
            account_id=account.id,
        )

    def _validate_port_conflicts(self) -> None:
        """Validate no port conflicts exist across active accounts.

        Raises:
            ValueError: If two accounts share the same port configuration
        """
        port_usage: dict[tuple[str, int, int], str] = {}  # (host, tick, order) -> account_id

        for account_id, account in self._account_manager._accounts.items():
            if account.status != "active":
                continue

            mt5 = account.mt5
            port_key = (mt5.zmq_host, mt5.zmq_tick_port, mt5.zmq_order_port)

            if port_key in port_usage:
                existing = port_usage[port_key]
                raise ValueError(
                    f"Port conflict: accounts '{existing}' and '{account_id}' "
                    f"share ports {mt5.zmq_host}:{mt5.zmq_tick_port}/{mt5.zmq_order_port}. "
                    f"Each account needs unique ZMQ ports."
                )
            port_usage[port_key] = account_id

    def _update_health(
        self,
        account_id: str,
        connected: bool,
        error: str | None = None,
    ) -> None:
        """Update connection health for an account.

        Args:
            account_id: Account to update
            connected: Connection status
            error: Error message if any
        """
        health = self._health.get(account_id, ConnectionHealth())
        health.connected = connected
        health.last_error = error

        if connected:
            health.last_heartbeat = datetime.now(timezone.utc)
            health.reconnect_attempts = 0
        else:
            health.reconnect_attempts += 1

        self._health[account_id] = health

    def _schedule_reconnection(self, account_id: str) -> None:
        """Schedule reconnection task for an account.

        Args:
            account_id: Account to reconnect
        """
        if not self._running:
            return

        # Cancel existing reconnection task if any
        if account_id in self._reconnection_tasks:
            self._reconnection_tasks[account_id].cancel()

        task = asyncio.create_task(
            self._reconnect_with_backoff(account_id),
            name=f"reconnect-{account_id}",
        )
        self._reconnection_tasks[account_id] = task

    async def _reconnect_with_backoff(self, account_id: str) -> None:
        """Reconnect with exponential backoff.

        Args:
            account_id: Account to reconnect
        """
        health = self._health.get(account_id, ConnectionHealth())
        attempt = min(health.reconnect_attempts, len(self.RECONNECT_DELAYS) - 1)
        delay = self.RECONNECT_DELAYS[attempt]

        logger.info(
            f"Reconnecting {account_id} in {delay}s (attempt {health.reconnect_attempts + 1})"
        )

        await asyncio.sleep(delay)

        # Clean up old connection
        if account_id in self._connections:
            await self._connections[account_id].disconnect()
            del self._connections[account_id]

        # Remove from reconnection tasks before starting
        self._reconnection_tasks.pop(account_id, None)

        # Attempt reconnection
        await self.start_connection(account_id)

        # Recover pending orders after successful reconnection
        if self._health.get(account_id, ConnectionHealth()).connected:
            await self._recover_pending_orders(account_id)

    async def _recover_pending_orders(self, account_id: str) -> None:
        """Handle pending orders after reconnection.

        Clears local pending set and logs warning for orders that
        may have been affected during disconnection. Orders need
        manual verification - do not auto-resend to prevent duplicates.

        Args:
            account_id: Account that reconnected
        """
        pending = self._pending_orders.get(account_id, set())
        if pending:
            logger.warning(
                f"Recovering from disconnect: {len(pending)} pending orders for {account_id}. "
                f"Order IDs: {list(pending)[:5]}{'...' if len(pending) > 5 else ''}. "
                f"Manual verification recommended - orders NOT auto-resent to prevent duplicates."
            )
            # Clear pending - orders need manual verification after reconnect
            self._pending_orders[account_id] = set()
        else:
            logger.info(f"No pending orders to recover for {account_id}")

    async def _tick_receiver_loop(
        self,
        account_id: str,
        adapter: ZmqAdapter,
    ) -> None:
        """Background task to receive ticks for an account.

        Also handles order results via the shared receive_ticks() generator.

        Args:
            account_id: Account receiving ticks
            adapter: ZmqAdapter for this account
        """
        try:
            async for tick in adapter.receive_ticks():
                # Ticks are yielded, order results handled internally by adapter
                logger.debug(
                    f"Tick for {account_id}: {tick.symbol} bid={tick.bid}"
                )
                # Update heartbeat on any received data
                self._update_health(account_id, connected=True)

        except asyncio.CancelledError:
            logger.debug(f"Tick receiver cancelled for {account_id}")
            raise

        except Exception as e:
            logger.error(f"Tick receiver error for {account_id}: {e}")
            self._update_health(account_id, connected=False, error=str(e))
            self._schedule_reconnection(account_id)
