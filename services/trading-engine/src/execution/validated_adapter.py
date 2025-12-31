"""Validated ZMQ Adapter - ZmqAdapter wrapper with pre-trade validation.

This module provides ValidatedZmqAdapter that wraps ZmqAdapter to add
pre-trade validation against compliance rules before sending orders to MT5.

Execution flow:
    Strategy/SignalRouter -> ValidatedZmqAdapter.send_order(order)
                                    |
                                    v
                         RiskStateRegistry.get_risk_state(account_id)
                                    |
                                    v
                         OrderValidator.validate_order(order, account_state)
                                    |
                         +----------+----------+
                         |          |          |
                         v          v          v
                       BLOCK      WARN       ALLOW
                         |          |          |
                         v          v          v
                   Raise Error   Log+Notify   Continue
                   + Notify      (async)        |
                                               v
                                     ZmqAdapter.send_order() -> MT5
"""

import logging
from typing import Any

from ..accounts.risk_registry import RiskStateRegistry
from ..accounts.risk_state import RiskState
from ..adapters.zmq_adapter import ZmqAdapter
from ..adapters.zmq_models import Order, OrderResult
from .exceptions import OrderBlockedError
from .order_validator import OrderValidator

logger = logging.getLogger(__name__)


class ValidatedZmqAdapter:
    """ZmqAdapter wrapper that validates orders before sending to MT5.

    This adapter wraps ZmqAdapter using composition (not inheritance) to add
    pre-trade validation. Every order is validated against compliance rules
    before being forwarded to the underlying ZmqAdapter.

    The ValidatedZmqAdapter:
    1. Fetches account state from RiskStateRegistry
    2. Calls OrderValidator.validate_order()
    3. If BLOCKED: raises OrderBlockedError (order NOT sent to MT5)
    4. If WARN: logs warning, proceeds to send order
    5. If ALLOW: proceeds to send order

    Attributes:
        zmq_adapter: The underlying ZmqAdapter for MT5 communication.
        order_validator: OrderValidator for pre-trade validation.
        risk_registry: RiskStateRegistry for fetching account state.

    Example:
        validated_adapter = ValidatedZmqAdapter(zmq_adapter, validator, registry)

        try:
            await validated_adapter.send_order(order)
        except OrderBlockedError as e:
            print(f"Order blocked: {e.reason}")
    """

    def __init__(
        self,
        zmq_adapter: ZmqAdapter,
        order_validator: OrderValidator,
        risk_registry: RiskStateRegistry,
    ) -> None:
        """Initialize ValidatedZmqAdapter.

        Args:
            zmq_adapter: ZmqAdapter instance for MT5 communication.
            order_validator: OrderValidator for pre-trade validation.
            risk_registry: RiskStateRegistry for fetching account state.
        """
        self._adapter = zmq_adapter
        self._validator = order_validator
        self._risk_registry = risk_registry

    async def send_order(self, order: Order) -> None:
        """Validate and send order to MT5.

        This method:
        1. Fetches account state from RiskStateRegistry
        2. Validates order against compliance rules
        3. If blocked, raises OrderBlockedError (order NOT sent)
        4. If allowed (with or without warnings), sends to MT5

        Args:
            order: Order to validate and send.

        Raises:
            OrderBlockedError: If order is blocked by compliance rules.
            RuntimeError: If not connected to MT5.
            zmq.ZMQError: If send fails.
        """
        # Get account state from RiskStateRegistry
        risk_state = self._risk_registry.get_risk_state(order.account_id)
        account_state = self._build_account_state(risk_state, order.account_id, order)

        # Validate order against rules
        result = await self._validator.validate_order(order, account_state)

        # If blocked, raise exception (order NOT sent to MT5)
        if result.is_blocked:
            logger.warning(
                "Order blocked by validation: %s - Rule: %s - Reason: %s",
                order.order_id,
                result.blocked_by_rule,
                result.reason,
            )
            raise OrderBlockedError(
                reason=result.reason or "Order blocked by compliance rules",
                blocked_by_rule=result.blocked_by_rule,
                current_value=result.current_value,
                threshold_value=result.threshold_value,
            )

        # Log warnings if present
        if result.has_warnings:
            logger.info(
                "Order allowed with warnings: %s - Warnings: %s",
                order.order_id,
                result.warnings,
            )

        # Proceed to send order to MT5
        await self._adapter.send_order(order)

        logger.debug(
            "Order sent after validation: %s in %.2fms",
            order.order_id,
            result.evaluation_time_ms,
        )

    async def send_order_and_wait(
        self,
        order: Order,
        timeout: float = 5.0,
    ) -> OrderResult:
        """Validate order and send to MT5, waiting for result.

        This method validates the order before sending. If blocked,
        raises OrderBlockedError without sending to MT5.

        IMPORTANT: receive_ticks() must be running in a background task
        for this method to work.

        Args:
            order: Order to validate and send.
            timeout: Timeout in seconds (default 5.0).

        Returns:
            OrderResult from MT5.

        Raises:
            OrderBlockedError: If order is blocked by compliance rules.
            asyncio.TimeoutError: If no result received within timeout.
            RuntimeError: If not connected to MT5.
        """
        # Get account state from RiskStateRegistry
        risk_state = self._risk_registry.get_risk_state(order.account_id)
        account_state = self._build_account_state(risk_state, order.account_id, order)

        # Validate order against rules
        result = await self._validator.validate_order(order, account_state)

        # If blocked, raise exception (order NOT sent to MT5)
        if result.is_blocked:
            logger.warning(
                "Order blocked by validation: %s - Rule: %s - Reason: %s",
                order.order_id,
                result.blocked_by_rule,
                result.reason,
            )
            raise OrderBlockedError(
                reason=result.reason or "Order blocked by compliance rules",
                blocked_by_rule=result.blocked_by_rule,
                current_value=result.current_value,
                threshold_value=result.threshold_value,
            )

        # Log warnings if present
        if result.has_warnings:
            logger.info(
                "Order allowed with warnings: %s - Warnings: %s",
                order.order_id,
                result.warnings,
            )

        # Proceed to send order and wait for result
        order_result = await self._adapter.send_order_and_wait(order, timeout)

        logger.debug(
            "Order result received after validation: %s in %.2fms",
            order.order_id,
            result.evaluation_time_ms,
        )

        return order_result

    def _build_account_state(
        self,
        risk_state: RiskState | None,
        account_id: str,
        order: Order | None = None,
    ) -> dict[str, Any]:
        """Build account_state dict from RiskState for validation context.

        Args:
            risk_state: RiskState from RiskStateRegistry (may be None).
            account_id: Account identifier for logging.
            order: Order being validated (for extracting volume/lots).

        Returns:
            Dictionary with account state for validation context.

        Note:
            This method builds context for both RuleContextBuilder standard fields
            AND direct rule access fields (account_balance, requested_lots).
            Position count and exposure are not currently tracked in RiskState -
            rules depending on these will see 0 values.
        """
        if risk_state is None:
            # No risk state available - return minimal state
            # This will cause validation to fail-safe (likely BLOCK)
            logger.warning(
                "No risk state available for account %s - using minimal state",
                account_id,
            )
            return {
                "balance": 0.0,
                "equity": 0.0,
                "initial_balance": 0.0,
                "peak_balance": 0.0,
                "daily_pnl": 0.0,
                "daily_pnl_percent": 0.0,
                "total_drawdown_percent": 0.0,
                "open_positions_count": 0,
                "total_exposure": 0.0,
                # Additional fields for rules that access context directly
                "account_balance": 0.0,
                "requested_lots": order.volume if order else 0.0,
                "current_position_lots": 0.0,
                "total_pnl_percent": 0.0,
                "trading_days_count": 0,
            }

        # Build account_state from RiskState
        # Note: RiskState uses Decimal, convert to float for context
        #
        # Field mapping:
        # - balance: Use daily_starting_balance (settled cash, not equity)
        # - equity: Use current_equity (balance + unrealized P&L)
        # - initial_balance: daily_starting_balance (for daily loss calc)
        # - peak_balance: peak_equity (high water mark)
        balance = float(risk_state.daily_starting_balance)
        equity = float(risk_state.current_equity)

        return {
            # Standard fields for RuleContextBuilder
            "balance": balance,
            "equity": equity,
            "initial_balance": balance,
            "peak_balance": float(risk_state.peak_equity),
            "daily_pnl": float(risk_state.daily_pnl),
            "daily_pnl_percent": float(risk_state.daily_pnl_percent),
            "total_drawdown_percent": float(risk_state.total_drawdown_percent),
            # Position tracking - NOT currently tracked in RiskState
            # TODO: Track these in RiskState for position-based rules
            "open_positions_count": 0,
            "total_exposure": 0.0,
            # Additional fields for rules that access context directly
            # (MaxPositionSizeRule, ProfitTargetRule, MinTradingDaysRule)
            "account_balance": balance,
            "requested_lots": order.volume if order else 0.0,
            "current_position_lots": 0.0,  # TODO: Track in RiskState
            "total_pnl_percent": float(risk_state.daily_pnl_percent),  # Approximation
            "trading_days_count": 1,  # TODO: Track in RiskState
        }

    # Delegate read-only properties to underlying adapter
    @property
    def is_connected(self) -> bool:
        """Check if underlying adapter is connected."""
        return self._adapter.is_connected

    def get_pending_order_count(self) -> int:
        """Get count of pending orders waiting for results."""
        return self._adapter.get_pending_order_count()

    # Delegate connection management to underlying adapter
    async def connect(self) -> None:
        """Connect underlying adapter."""
        await self._adapter.connect()

    async def disconnect(self) -> None:
        """Disconnect underlying adapter."""
        await self._adapter.disconnect()

    async def __aenter__(self) -> "ValidatedZmqAdapter":
        """Async context manager entry."""
        await self._adapter.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        """Async context manager exit."""
        await self._adapter.disconnect()
