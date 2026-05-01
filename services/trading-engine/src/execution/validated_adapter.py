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
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Callable

from ..accounts.risk_registry import RiskStateRegistry
from ..accounts.risk_state import RiskState
from ..adapters.zmq_models import Order, OrderResult
from ..orders.order_gateway import OrderGateway
from .exceptions import OrderBlockedError
from .exposure_reservation import ExposureReservation, ReservationResult
from .order_validator import OrderValidator

if TYPE_CHECKING:
    from ..accounts.pnl_registry import PnLTrackerRegistry

logger = logging.getLogger(__name__)


# Callable returning the max-lots ceiling for an account (e.g. from
# MaxPositionSizeRule's effective max). ``None`` ⇒ atomic reservation
# gate is skipped for this order.
MaxLotsProvider = Callable[[str, dict[str, Any]], "Decimal | float | None"]


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
        zmq_adapter: OrderGateway,
        order_validator: OrderValidator,
        risk_registry: RiskStateRegistry,
        pnl_registry: "PnLTrackerRegistry | None" = None,
        exposure_reservation: ExposureReservation | None = None,
        max_lots_provider: MaxLotsProvider | None = None,
    ) -> None:
        """Initialize ValidatedZmqAdapter.

        Args:
            zmq_adapter: Any :class:`OrderGateway` (Epic 9 P0.12). The
                production wiring passes ``ZmqAdapter`` and the parameter
                name is preserved for compatibility; future futures
                gateways implement the same protocol.
            order_validator: OrderValidator for pre-trade validation.
            risk_registry: RiskStateRegistry for fetching account state.
            pnl_registry: Optional PnLTrackerRegistry for position tracking.
            exposure_reservation: Optional :class:`ExposureReservation` for
                the atomic in-flight gate (story 10.4 / D6). When wired
                with a ``max_lots_provider`` it serialises concurrent
                ``send_order_and_wait`` calls so combined exposure cannot
                exceed the cap. Both must be set for the gate to engage.
            max_lots_provider: Callback returning the max-lots ceiling for
                an ``(account_id, account_state)`` pair. Returning ``None``
                disables the gate for that specific order.
        """
        self._adapter: OrderGateway = zmq_adapter
        self._validator = order_validator
        self._risk_registry = risk_registry
        self._pnl_registry = pnl_registry
        self._reservation = exposure_reservation
        self._max_lots_provider = max_lots_provider

    def set_pnl_registry(self, registry: "PnLTrackerRegistry") -> None:
        """Register P&L tracker registry for order execution notifications.

        Args:
            registry: PnLTrackerRegistry instance.
        """
        self._pnl_registry = registry
        logger.info("PnL registry registered with ValidatedZmqAdapter")

    async def send_order(self, order: Order) -> None:
        """Validate and send order to MT5 (fire-and-forget).

        WARNING: This method does NOT track P&L because it doesn't wait for
        the OrderResult. For trades that need P&L tracking, use
        send_order_and_wait() instead.

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

        Note:
            P&L tracking requires OrderResult to create positions. Since this
            method doesn't wait for results, positions won't be tracked.
            Use send_order_and_wait() for proper P&L integration.
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
            OrderBlockedError: If order is blocked by compliance rules
                or by the atomic exposure-reservation gate (story 10.4).
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

        # Atomic exposure-reservation gate (story 10.4). Closes the
        # validate↔send race window: even if two concurrent orders both
        # pass the rule engine, only one can claim the in-flight lots
        # before the other reads the same realized snapshot.
        reservation = await self._try_reserve(order, account_state)

        try:
            order_result = await self._adapter.send_order_and_wait(order, timeout)
        except BaseException:
            # Release on any send failure (timeout, ZMQ error, cancellation).
            await self._release_reservation(order, reservation)
            raise

        logger.debug(
            "Order result received after validation: %s in %.2fms",
            order.order_id,
            result.evaluation_time_ms,
        )

        try:
            # Notify PnL tracker of trade execution for position tracking.
            # Doing this BEFORE release ensures the realized counter is
            # already incremented when the next reservation reads it,
            # closing the gap where reservation drops to 0 but realized
            # has not yet caught up.
            if self._pnl_registry and order_result.is_filled:
                tracker = await self._pnl_registry.get_or_create(order.account_id)
                await tracker.on_trade_executed(order_result, order)
        finally:
            await self._release_reservation(order, reservation)

        return order_result

    async def _try_reserve(
        self,
        order: Order,
        account_state: dict[str, Any],
    ) -> ReservationResult | None:
        """Atomic reservation gate (story 10.4 / D6).

        Returns the :class:`ReservationResult` on success so the caller
        can release later, or ``None`` when the gate is disabled. Raises
        :class:`OrderBlockedError` if the reservation is rejected.
        """
        if self._reservation is None or self._max_lots_provider is None:
            return None

        max_lots = self._max_lots_provider(order.account_id, account_state)
        if max_lots is None:
            return None

        max_lots_dec = Decimal(str(max_lots))
        # The Lua gate caps ``currently_reserved + requested``; subtract
        # the realized open lots so the combined exposure (realized +
        # in-flight) cannot push past the configured ceiling.
        current_position = Decimal(
            str(account_state.get("current_position_lots", 0.0))
        )
        max_total_for_reserve = max_lots_dec - current_position
        requested = Decimal(str(order.volume))

        try:
            reservation = await self._reservation.reserve(
                account_id=order.account_id,
                requested_lots=requested,
                max_total_lots=max_total_for_reserve,
            )
        except Exception:
            # Don't bring the engine down because Redis hiccupped — log,
            # skip the gate, and let the synchronous validator be the
            # only line of defence for this single order.
            logger.exception(
                "ExposureReservation.reserve raised for %s; proceeding without "
                "atomic gate",
                order.order_id,
            )
            return None

        if not reservation.accepted:
            current_total = float(reservation.previous_reserved + current_position)
            logger.warning(
                "Order BLOCKED by atomic exposure gate: %s — requested %.4f "
                "lots, in-flight %.4f, realized %.4f, max %.4f",
                order.order_id,
                float(requested),
                float(reservation.previous_reserved),
                float(current_position),
                float(max_lots_dec),
            )
            raise OrderBlockedError(
                reason=(
                    f"Atomic exposure gate rejected: requested {float(requested):.4f} "
                    f"+ in-flight {float(reservation.previous_reserved):.4f} "
                    f"+ realized {float(current_position):.4f} > max "
                    f"{float(max_lots_dec):.4f} lots"
                ),
                blocked_by_rule="atomic_exposure_reservation",
                current_value=current_total,
                threshold_value=float(max_lots_dec),
            )

        return reservation

    async def _release_reservation(
        self,
        order: Order,
        reservation: ReservationResult | None,
    ) -> None:
        """Release the in-flight reservation; never raises."""
        if self._reservation is None or reservation is None:
            return
        try:
            await self._reservation.release(
                order.account_id,
                Decimal(str(order.volume)),
            )
        except Exception:
            logger.exception(
                "Failed to release exposure reservation for %s — counter may "
                "drift until TTL expires",
                order.order_id,
            )

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

        # Get position data from PnLTrackerRegistry if available
        open_positions_count = 0
        total_exposure = 0.0
        current_position_lots = 0.0

        if self._pnl_registry:
            open_positions_count = self._pnl_registry.get_open_positions_count(account_id)
            total_exposure = float(self._pnl_registry.get_total_exposure(account_id))
            current_position_lots = float(self._pnl_registry.get_total_position_lots(account_id))

        return {
            # Standard fields for RuleContextBuilder
            "balance": balance,
            "equity": equity,
            "initial_balance": balance,
            "peak_balance": float(risk_state.peak_equity),
            "daily_pnl": float(risk_state.daily_pnl),
            "daily_pnl_percent": float(risk_state.daily_pnl_percent),
            "total_drawdown_percent": float(risk_state.total_drawdown_percent),
            # Position tracking from PnLTrackerRegistry
            "open_positions_count": open_positions_count,
            "total_exposure": total_exposure,
            # Additional fields for rules that access context directly
            # (MaxPositionSizeRule, ProfitTargetRule, MinTradingDaysRule)
            "account_balance": balance,
            "requested_lots": order.volume if order else 0.0,
            "current_position_lots": current_position_lots,
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
