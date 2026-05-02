"""Telegram-triggered emergency-stop kill-switch.

Story 10.7 (D7#4) — the Telegram bot publishes an ``emergency:stop``
JSON payload to Redis Pub/Sub. The previous engine code only flipped
``_running = False``: positions stayed open across the trading-engine
restart, and an account that held a losing position over the FTMO
daily-reset boundary would breach the daily-loss rule even though the
operator already issued a stop.

This handler upgrades that path to a full **flat-positions** kill-switch:

1. Subscribe to ``emergency:stop`` on the shared Redis client.
2. On a stop command:
   - Audit-log the trigger synchronously (story 10.3 — audit-row first).
   - For every active account: query open positions via the
     :class:`OrderGateway`, send an opposite-side market order per
     position, then pause the account.
   - Audit-log completion with stats.
   - Publish ``emergency:stop_confirmation`` so the Telegram bot can
     render a "X positions closed across Y accounts" message.

The whole pipeline runs in a background task started by
:meth:`start`; :meth:`stop` cancels it cleanly.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

from ..orders.close_order_builder import build_close_order

if TYPE_CHECKING:
    from ..accounts.account_manager import AccountManager
    from ..adapters.zmq_models import MT5Position
    from ..audit.audit_service import AuditService
    from ..orders.order_gateway import OrderGateway
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


# Pubsub channels — match the Telegram bot's publisher
# (services/notification/internal/telegram/bot.go:296).
EMERGENCY_STOP_CHANNEL = "emergency:stop"
EMERGENCY_STOP_CONFIRMATION_CHANNEL = "emergency:stop_confirmation"

# Default per-position close timeout — keep the whole stop sequence
# bounded even if mt5-bridge is sluggish.
DEFAULT_CLOSE_TIMEOUT_SECONDS = 5.0
DEFAULT_QUERY_POSITIONS_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True)
class EmergencyStopResult:
    """Statistics for one emergency-stop run, included in the confirmation."""

    accounts_processed: int
    positions_closed: int
    accounts_paused: int
    failures: tuple[tuple[str, str], ...] = field(default_factory=tuple)
    started_at: str = ""
    completed_at: str = ""

    def to_payload(self, *, command: dict[str, Any]) -> str:
        """Serialise to JSON for the ``emergency:stop_confirmation`` channel."""
        return json.dumps(
            {
                "type": "emergency_stop_confirmation",
                "accounts_processed": self.accounts_processed,
                "positions_closed": self.positions_closed,
                "accounts_paused": self.accounts_paused,
                "failures": [list(f) for f in self.failures],
                "started_at": self.started_at,
                "completed_at": self.completed_at,
                "originating_command": command,
            },
            separators=(",", ":"),
        )


class EmergencyStopHandler:
    """Subscribes to ``emergency:stop`` and flats every active account.

    Args:
        redis_manager: Shared :class:`RedisStateManager`. Both the
            pub/sub subscription and the confirmation publish use its
            connected client.
        account_manager: Source of active accounts + ``pause_account``.
        zmq_adapter: :class:`OrderGateway` plus
            ``query_positions(account_id)``. The protocol-typed gateway
            covers ``send_order_and_wait``; the position query lives on
            the concrete :class:`ZmqAdapter` today.
        audit_service: Audit pipeline. ``log_system_event_sync`` is
            mandatory for the trigger + completion rows (story 10.3).
        close_timeout_seconds: Per-position close timeout.
        query_positions_timeout_seconds: Position-query timeout.
    """

    def __init__(
        self,
        *,
        redis_manager: "RedisStateManager",
        account_manager: "AccountManager",
        zmq_adapter: "OrderGateway",
        audit_service: "AuditService",
        close_timeout_seconds: float = DEFAULT_CLOSE_TIMEOUT_SECONDS,
        query_positions_timeout_seconds: float = (
            DEFAULT_QUERY_POSITIONS_TIMEOUT_SECONDS
        ),
    ) -> None:
        self._redis = redis_manager
        self._account_manager = account_manager
        self._zmq = zmq_adapter
        self._audit = audit_service
        self._close_timeout = close_timeout_seconds
        self._query_timeout = query_positions_timeout_seconds
        self._pubsub: object | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def is_running(self) -> bool:
        return self._running

    async def start(self) -> None:
        """Subscribe + spawn the listener task. Idempotent."""
        if self._running:
            return
        self._running = True
        pubsub = self._redis.client.pubsub()
        await pubsub.subscribe(EMERGENCY_STOP_CHANNEL)
        self._pubsub = pubsub
        self._listener_task = asyncio.create_task(
            self._listen_loop(),
            name="emergency_stop_listener",
        )
        logger.info(
            "EmergencyStopHandler subscribed to %s", EMERGENCY_STOP_CHANNEL
        )

    async def stop(self) -> None:
        """Cancel the listener and unsubscribe. Idempotent."""
        if not self._running:
            return
        self._running = False

        if self._listener_task is not None:
            self._listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._listener_task
            self._listener_task = None

        if self._pubsub is not None:
            try:
                await self._pubsub.unsubscribe()
                close = getattr(self._pubsub, "aclose", None) or getattr(
                    self._pubsub, "close", None
                )
                if close is not None:
                    result = close()
                    if asyncio.iscoroutine(result):
                        await result
            except Exception:
                logger.exception(
                    "EmergencyStopHandler failed to close pubsub cleanly"
                )
            self._pubsub = None

    async def _listen_loop(self) -> None:
        assert self._pubsub is not None
        async for message in self._pubsub.listen():
            mtype = message.get("type") if isinstance(message, dict) else None
            if mtype != "message":
                continue
            data = message.get("data")
            if data is None:
                continue
            try:
                payload = self._parse_payload(data)
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning(
                    "EmergencyStopHandler: malformed payload — %s", exc
                )
                continue
            try:
                await self._handle_stop(payload)
            except Exception:
                logger.exception(
                    "EmergencyStopHandler: handle_stop raised — engine "
                    "remains alive but accounts may not be flat"
                )

    @staticmethod
    def _parse_payload(raw: object) -> dict[str, Any]:
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8")
        if not isinstance(raw, str):
            raise ValueError(f"Expected str/bytes payload, got {type(raw)!r}")
        decoded = json.loads(raw)
        if not isinstance(decoded, dict):
            raise ValueError(f"Expected dict payload, got {type(decoded)!r}")
        return decoded

    async def _handle_stop(self, command: dict[str, Any]) -> None:
        """Execute the flat-positions sequence. Public for tests."""
        await self._handle_stop_command(command)

    async def _handle_stop_command(self, command: dict[str, Any]) -> None:
        started_at = datetime.now(timezone.utc).isoformat()

        # Audit-row first (double-entry, story 10.3).
        try:
            await self._audit.log_system_event_sync(
                event_subtype="emergency_stop_triggered",
                message="Emergency stop received from Telegram",
                level="WARNING",
                context={"command": command},
            )
        except Exception:
            logger.exception("Failed to record emergency_stop_triggered audit")

        active_accounts = list(self._account_manager.get_active_account_ids())
        positions_closed = 0
        accounts_paused = 0
        failures: list[tuple[str, str]] = []

        for account_id in active_accounts:
            closed, error = await self._flatten_account(account_id)
            positions_closed += closed
            if error is not None:
                failures.append((account_id, error))
                # Still attempt to pause — the goal is "no new trades".
            try:
                await self._account_manager.pause_account(account_id)
                accounts_paused += 1
            except Exception as exc:
                logger.warning(
                    "EmergencyStopHandler: failed to pause %s — %s",
                    account_id,
                    exc,
                )
                failures.append((account_id, f"pause failed: {exc!r}"))

        completed_at = datetime.now(timezone.utc).isoformat()
        result = EmergencyStopResult(
            accounts_processed=len(active_accounts),
            positions_closed=positions_closed,
            accounts_paused=accounts_paused,
            failures=tuple(failures),
            started_at=started_at,
            completed_at=completed_at,
        )

        # Audit-row completion.
        try:
            await self._audit.log_system_event_sync(
                event_subtype="emergency_stop_complete",
                message=(
                    f"Emergency stop complete: closed {positions_closed} "
                    f"position(s), paused {accounts_paused}/{len(active_accounts)} "
                    "account(s)"
                ),
                level="WARNING" if failures else "INFO",
                context={
                    "accounts_processed": result.accounts_processed,
                    "positions_closed": result.positions_closed,
                    "accounts_paused": result.accounts_paused,
                    "failures": [list(f) for f in result.failures],
                },
            )
        except Exception:
            logger.exception("Failed to record emergency_stop_complete audit")

        # Publish confirmation back for Telegram. Best-effort.
        try:
            await self._redis.client.publish(
                EMERGENCY_STOP_CONFIRMATION_CHANNEL,
                result.to_payload(command=command),
            )
        except Exception:
            logger.exception(
                "EmergencyStopHandler: failed to publish confirmation"
            )

    async def _flatten_account(
        self, account_id: str
    ) -> tuple[int, str | None]:
        """Close every open position for ``account_id``.

        Returns ``(positions_closed, error)``. ``error`` is set when
        position query or any close raises; closing continues for the
        rest of the positions either way.
        """
        try:
            positions: list[MT5Position] = await self._zmq.query_positions(
                account_id, timeout=self._query_timeout
            )
        except Exception as exc:
            logger.exception(
                "EmergencyStopHandler: query_positions failed for %s",
                account_id,
            )
            return 0, f"query_positions failed: {exc!r}"

        closed = 0
        for position in positions:
            try:
                close_order = build_close_order(
                    position, account_id=account_id
                )
            except ValueError as exc:
                logger.warning(
                    "EmergencyStopHandler: skipping position %s on %s — %s",
                    getattr(position, "ticket", "?"),
                    account_id,
                    exc,
                )
                continue
            try:
                await self._zmq.send_order_and_wait(
                    close_order, timeout=self._close_timeout
                )
                closed += 1
            except Exception:
                logger.exception(
                    "EmergencyStopHandler: close failed for ticket %s on %s",
                    getattr(position, "ticket", "?"),
                    account_id,
                )

        return closed, None
