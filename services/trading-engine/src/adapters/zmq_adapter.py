"""ZeroMQ adapter for mt5-bridge communication.

This module provides bidirectional communication with mt5-bridge:
- SUB socket receives tick data and order results from bridge PUB (port 5556)
- PUB socket sends order commands to bridge SUB (port 5557)

``ZmqAdapter`` is the canonical implementation of
:class:`src.orders.order_gateway.OrderGateway` (Epic 9 P0.12). Callers
that only need the gateway surface should depend on the protocol so a
future futures broker can be swapped in without touching this module.

CRITICAL: The receive_ticks() async generator MUST run in a background task
for order results to work. See usage pattern in docstring.

Example:
    async def main():
        adapter = ZmqAdapter()
        await adapter.connect()

        # Start tick receiver in background (REQUIRED for order results)
        async def tick_receiver():
            async for tick in adapter.receive_ticks():
                print(f"Tick: {tick.symbol} bid={tick.bid}")

        receiver_task = asyncio.create_task(tick_receiver())

        # Now orders can be sent
        order = Order(account_id="ftmo-001", action=OrderSide.BUY, ...)
        result = await adapter.send_order_and_wait(order, timeout=5.0)

        receiver_task.cancel()
        await adapter.disconnect()
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, AsyncIterator

import zmq
import zmq.asyncio
from pydantic import BaseModel

from .zmq_models import MT5Position, Order, OrderResult, OrderStatus, Tick

if TYPE_CHECKING:
    from ..accounts.metrics_service import AccountMetricsService
    from ..accounts.pnl_registry import PnLTrackerRegistry

logger = logging.getLogger(__name__)


class ZmqConfig(BaseModel):
    """ZeroMQ adapter configuration.

    Attributes:
        bridge_host: Hostname of mt5-bridge service
        tick_port: Port to SUB for ticks (mt5-bridge PUB)
        order_port: Port to PUB for orders (mt5-bridge SUB connects)
        bind_address: Address to bind PUB socket (default 127.0.0.1 for security)
        recv_timeout_ms: Receive timeout in milliseconds
        send_timeout_ms: Send timeout in milliseconds
        reconnect_ivl_ms: Initial reconnect interval
        reconnect_ivl_max_ms: Maximum reconnect interval
        account_id: Account identifier for routing (optional, for per-account connections)
    """

    bridge_host: str = "localhost"
    tick_port: int = 5556  # Port we SUB to for ticks (mt5-bridge PUB)
    order_port: int = 5557  # Port we PUB on for orders (mt5-bridge SUB connects)
    bind_address: str = "127.0.0.1"  # Bind to localhost by default for security
    recv_timeout_ms: int = 1000
    send_timeout_ms: int = 5000
    reconnect_ivl_ms: int = 1000
    reconnect_ivl_max_ms: int = 30000
    account_id: str | None = None  # For per-account connection tracking


@dataclass
class _ConnectionState:
    """Connection state tracking (internal use only)."""

    connected: bool = False
    connecting: bool = False
    last_error: str | None = None


class ZmqAdapter:
    """ZeroMQ adapter for mt5-bridge communication.

    Provides bidirectional communication with mt5-bridge:
    - SUB socket receives tick data and order results from bridge PUB
    - PUB socket sends order commands to bridge SUB

    Attributes:
        config: ZMQ configuration
        is_connected: Whether adapter is connected

    Example:
        async with ZmqAdapter() as adapter:
            async for tick in adapter.receive_ticks():
                print(f"Tick: {tick.symbol}")
    """

    # Exponential backoff delays for reconnection (seconds)
    RECONNECT_DELAYS = [1, 2, 4, 8, 16, 30]

    def __init__(self, config: ZmqConfig | None = None):
        """Initialize ZMQ adapter.

        Args:
            config: ZMQ configuration. Uses defaults if not provided.
        """
        self.config = config or ZmqConfig()
        self._ctx = zmq.asyncio.Context.instance()
        self._sub_socket: zmq.asyncio.Socket | None = None
        self._pub_socket: zmq.asyncio.Socket | None = None
        self._state = _ConnectionState()
        self._pending_orders: dict[str, asyncio.Future[OrderResult]] = {}
        self._pending_positions: dict[str, asyncio.Future[list[MT5Position]]] = {}
        self._reconnect_attempt = 0
        self._metrics_service: AccountMetricsService | None = None
        self._pnl_registry: PnLTrackerRegistry | None = None

    def set_metrics_service(self, service: "AccountMetricsService") -> None:
        """Register metrics service for balance/equity updates.

        When registered, account_info messages from MT5 will trigger
        updates through the metrics service.

        Args:
            service: AccountMetricsService instance.
        """
        self._metrics_service = service
        logger.info("Metrics service registered with ZMQ adapter")

    def set_pnl_registry(self, registry: "PnLTrackerRegistry") -> None:
        """Register P&L tracker registry for tick routing.

        When registered, tick messages will be routed to the P&L registry
        for real-time P&L updates.

        Args:
            registry: PnLTrackerRegistry instance.
        """
        self._pnl_registry = registry
        logger.info("PnL registry registered with ZMQ adapter")

    @property
    def is_connected(self) -> bool:
        """Check if adapter is connected."""
        return self._state.connected

    async def connect(self) -> None:
        """Connect to mt5-bridge ZeroMQ sockets.

        Creates SUB socket connected to mt5-bridge PUB (port 5556) for
        receiving tick data and order results.

        Creates PUB socket bound to port 5557 for sending order commands
        to mt5-bridge SUB.

        Raises:
            zmq.ZMQError: If socket operations fail
        """
        if self._state.connected:
            return

        self._state.connecting = True
        try:
            # SUB socket - connect to mt5-bridge PUB (port 5556)
            self._sub_socket = self._ctx.socket(zmq.SUB)
            self._sub_socket.setsockopt(zmq.RCVTIMEO, self.config.recv_timeout_ms)
            self._sub_socket.setsockopt(zmq.LINGER, 1000)
            self._sub_socket.setsockopt(zmq.RECONNECT_IVL, self.config.reconnect_ivl_ms)
            self._sub_socket.setsockopt(zmq.RECONNECT_IVL_MAX, self.config.reconnect_ivl_max_ms)

            sub_endpoint = f"tcp://{self.config.bridge_host}:{self.config.tick_port}"
            self._sub_socket.connect(sub_endpoint)

            # Subscribe to tick, order_result, account_info, and positions_result topics
            self._sub_socket.subscribe(b"tick:")
            self._sub_socket.subscribe(b"order_result:")
            self._sub_socket.subscribe(b"account_info:")
            self._sub_socket.subscribe(b"positions_result:")

            logger.info("SUB socket connected to %s", sub_endpoint)

            # PUB socket - bind for mt5-bridge SUB to connect (port 5557)
            self._pub_socket = self._ctx.socket(zmq.PUB)
            self._pub_socket.setsockopt(zmq.SNDTIMEO, self.config.send_timeout_ms)
            self._pub_socket.setsockopt(zmq.LINGER, 1000)

            pub_endpoint = f"tcp://{self.config.bind_address}:{self.config.order_port}"
            self._pub_socket.bind(pub_endpoint)

            logger.info("PUB socket bound to %s", pub_endpoint)

            self._state.connected = True
            self._state.last_error = None
            self._reconnect_attempt = 0

        except zmq.ZMQError as e:
            self._state.last_error = str(e)
            logger.error("Failed to connect: %s", e)
            raise
        finally:
            self._state.connecting = False

    async def disconnect(self) -> None:
        """Disconnect and cleanup sockets.

        Closes SUB and PUB sockets gracefully.
        """
        self._state.connected = False

        if self._sub_socket:
            self._sub_socket.close()
            self._sub_socket = None

        if self._pub_socket:
            self._pub_socket.close()
            self._pub_socket = None

        logger.info("ZMQ adapter disconnected")

    async def reconnect(self) -> None:
        """Reconnect with exponential backoff.

        Uses RECONNECT_DELAYS sequence: 1s, 2s, 4s, 8s, 16s, 30s max.
        """
        delay_idx = min(self._reconnect_attempt, len(self.RECONNECT_DELAYS) - 1)
        delay = self.RECONNECT_DELAYS[delay_idx]

        logger.warning(
            "Reconnecting in %d seconds (attempt %d)",
            delay,
            self._reconnect_attempt + 1,
        )

        await asyncio.sleep(delay)
        self._reconnect_attempt += 1

        await self.disconnect()
        await self.connect()

    async def receive_ticks(self) -> AsyncIterator[Tick]:
        """Async generator yielding tick data from mt5-bridge.

        This method also handles order_result messages internally,
        resolving pending order futures when results arrive.

        IMPORTANT: This generator MUST run in a background task for
        send_order_and_wait() to work, as order results arrive here.

        Yields:
            Tick: Parsed tick data with account_id, symbol, bid, ask, timestamp

        Raises:
            RuntimeError: If not connected

        Example:
            async for tick in adapter.receive_ticks():
                print(f"{tick.symbol}: bid={tick.bid} ask={tick.ask}")
        """
        if not self._sub_socket:
            raise RuntimeError("Not connected - call connect() first")

        while True:
            try:
                msg = await self._sub_socket.recv_multipart()

                if len(msg) < 2:
                    logger.warning("Received malformed message: %s", msg)
                    continue

                topic = msg[0].decode()
                payload = msg[1].decode()

                # Route by topic prefix
                if topic.startswith("tick:"):
                    try:
                        data = json.loads(payload)
                        tick = Tick(
                            account_id=data["account_id"],
                            symbol=data["symbol"],
                            bid=data["bid"],
                            ask=data["ask"],
                            timestamp=data["timestamp"],
                        )

                        # Route tick to P&L registry for real-time P&L updates
                        if self._pnl_registry:
                            # Convert float to Decimal at boundary
                            bid_decimal = Decimal(str(tick.bid))
                            ask_decimal = Decimal(str(tick.ask))
                            await self._pnl_registry.on_tick_all(
                                tick.symbol, bid_decimal, ask_decimal
                            )

                        yield tick
                    except (json.JSONDecodeError, KeyError) as e:
                        logger.warning("Failed to parse tick: %s - %s", e, payload)

                elif topic.startswith("order_result:"):
                    try:
                        data = json.loads(payload)
                        result = OrderResult(
                            order_id=data["order_id"],
                            status=OrderStatus(data["status"]),
                            fill_price=data.get("fill_price"),
                            slippage=data.get("slippage"),
                            timestamp=data.get("timestamp", ""),
                            error=data.get("error"),
                        )
                        # Resolve pending order future
                        future = self._pending_orders.pop(result.order_id, None)
                        if future and not future.done():
                            future.set_result(result)
                        else:
                            logger.warning(
                                "Received result for unknown order: %s", result.order_id
                            )
                    except (json.JSONDecodeError, KeyError, ValueError) as e:
                        logger.warning("Failed to parse order result: %s - %s", e, payload)

                elif topic.startswith("account_info:"):
                    # Handle account balance/equity updates from MT5
                    await self._handle_account_info(payload)

                elif topic.startswith("positions_result:"):
                    # Handle position query results for crash recovery
                    await self._handle_positions_result(payload)

            except zmq.Again:
                # Receive timeout - continue loop (allows checking for cancellation)
                continue
            except zmq.ZMQError as e:
                logger.error("ZMQ receive error: %s", e)
                await self.reconnect()

    async def send_order(self, order: Order) -> None:
        """Send order command to mt5-bridge.

        Publishes order with topic format: order:{account_id}

        Args:
            order: Order to send

        Raises:
            RuntimeError: If not connected
            zmq.ZMQError: If send fails
        """
        if not self._pub_socket:
            raise RuntimeError("Not connected - call connect() first")

        topic = f"order:{order.account_id}"
        payload = order.model_dump_json()

        await self._pub_socket.send_multipart([
            topic.encode(),
            payload.encode(),
        ])

        logger.debug(
            "Order sent: %s %s %s @ %.2f",
            order.order_id,
            order.action.value,
            order.symbol,
            order.price,
        )

    async def send_order_and_wait(
        self,
        order: Order,
        timeout: float = 5.0,
    ) -> OrderResult:
        """Send order and wait for result with timeout.

        IMPORTANT: receive_ticks() must be running in a background task
        for this method to work. Order results are processed by the
        receive_ticks() generator.

        Args:
            order: Order to send
            timeout: Timeout in seconds (default 5.0)

        Returns:
            OrderResult from mt5-bridge

        Raises:
            asyncio.TimeoutError: If no result received within timeout
            RuntimeError: If not connected
        """
        # Create future for this order
        loop = asyncio.get_running_loop()
        future: asyncio.Future[OrderResult] = loop.create_future()
        self._pending_orders[order.order_id] = future

        try:
            await self.send_order(order)
            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            self._pending_orders.pop(order.order_id, None)
            logger.error("Order timeout: %s", order.order_id)
            raise

    def get_pending_order_count(self) -> int:
        """Get count of pending orders waiting for results.

        Returns:
            Number of orders awaiting results
        """
        return len(self._pending_orders)

    async def __aenter__(self) -> ZmqAdapter:
        """Async context manager entry - connect."""
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit - disconnect."""
        await self.disconnect()

    async def _handle_account_info(self, payload: str) -> None:
        """Handle account info update from MT5.

        Message format from MT5 EA:
        {"account_id": "ftmo-001", "balance": 100000.00, "equity": 98500.00}

        This updates the account metrics through AccountMetricsService
        which handles debouncing and persistence.

        Args:
            payload: JSON payload string with account info
        """
        if self._metrics_service is None:
            # No metrics service registered, skip processing
            return

        try:
            data = json.loads(payload)
            account_id = data["account_id"]
            balance = Decimal(str(data["balance"]))
            equity = Decimal(str(data["equity"]))

            await self._metrics_service.on_mt5_balance_update(
                account_id, balance, equity
            )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse account_info: %s - %s", e, payload)

    async def _handle_positions_result(self, payload: str) -> None:
        """Handle position query result from mt5-bridge.

        Message format from mt5-bridge:
        {
            "type": "positions_result",
            "request_id": "UUID",
            "account_id": "ftmo-gold-001",
            "positions": [
                {
                    "ticket": 12345678,
                    "symbol": "XAUUSD",
                    "side": "BUY",
                    "volume": 0.1,
                    "entry_price": 1850.45,
                    "entry_time": "2026-01-03T10:15:30.000Z",
                    "current_price": 1852.30,
                    "profit": 185.00,
                    "swap": -2.50,
                    "commission": -1.00
                }
            ],
            "timestamp": "2026-01-03T14:32:15.123Z"
        }

        Args:
            payload: JSON payload string with position data
        """
        try:
            data = json.loads(payload)
            request_id = data["request_id"]
            positions = [MT5Position.from_dict(p) for p in data.get("positions", [])]

            # Resolve pending position query future
            future = self._pending_positions.pop(request_id, None)
            if future and not future.done():
                future.set_result(positions)
            else:
                logger.warning(
                    "Received positions_result for unknown request: %s", request_id
                )
        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.warning("Failed to parse positions_result: %s - %s", e, payload)

    async def query_positions(
        self,
        account_id: str,
        timeout: float = 10.0,
    ) -> list[MT5Position]:
        """Query MT5 for current open positions.

        Uses the existing PUB/SUB pattern with pending futures (same as orders).
        Publishes get_positions request and waits for positions_result response.

        ARCHITECTURE: Reuses existing PUB socket for requests, SUB socket for responses.
        This follows the same pattern as send_order_and_wait() with _pending_orders.

        IMPORTANT: receive_ticks() must be running in a background task
        for this method to work, as positions_result messages are processed there.

        Args:
            account_id: Account to query positions for
            timeout: Response timeout in seconds (default 10s for recovery)

        Returns:
            List of MT5Position objects representing current open positions

        Raises:
            asyncio.TimeoutError: If no response within timeout
            RuntimeError: If not connected
        """
        if not self._pub_socket:
            raise RuntimeError("Not connected - call connect() first")

        request_id = str(uuid.uuid4())
        loop = asyncio.get_running_loop()
        future: asyncio.Future[list[MT5Position]] = loop.create_future()
        self._pending_positions[request_id] = future

        try:
            # Publish position query request
            topic = f"get_positions:{account_id}"
            payload = json.dumps({
                "type": "get_positions",
                "account_id": account_id,
                "request_id": request_id,
            })
            await self._pub_socket.send_multipart([
                topic.encode(),
                payload.encode(),
            ])

            logger.debug("Position query sent for %s (request_id=%s)", account_id, request_id)

            result = await asyncio.wait_for(future, timeout=timeout)
            return result
        except asyncio.TimeoutError:
            # CLEANUP: Remove stale pending request on timeout
            self._pending_positions.pop(request_id, None)
            logger.error("Position query timeout for account %s", account_id)
            raise

    def get_pending_position_query_count(self) -> int:
        """Get count of pending position queries waiting for results.

        Returns:
            Number of position queries awaiting results
        """
        return len(self._pending_positions)

    async def close(self) -> None:
        """Close ZMQ sockets gracefully.

        Closes all sockets with linger=0 to avoid blocking.
        Safe to call multiple times.

        Note: Does not terminate the ZMQ context since we use
        Context.instance() (singleton) which may be shared.
        """
        if not self._state.connected:
            return

        logger.info("Closing ZMQ adapter...")

        # Close sockets first
        for socket in [self._sub_socket, self._pub_socket]:
            if socket is not None:
                try:
                    socket.close(linger=0)
                except Exception as e:
                    logger.warning("Error closing ZMQ socket: %s", e)

        self._sub_socket = None
        self._pub_socket = None
        self._state.connected = False

        logger.info("ZMQ adapter closed")
