"""Per-account live-trading session.

Story 10.5a — :class:`LiveAccountSession` owns the per-account state
that :class:`LiveOrchestrator` keeps in its ``dict[str, LiveAccountSession]``.
The session is intentionally a small state machine today; 10.5b/c will
attach the Nautilus ``LiveNode``, ``RedisDataClient``, and
``ZmqExecutionClient`` to each session via :meth:`attach_components`.

Crash isolation contract:
- A failure to ``start()`` flips the session to :attr:`SessionState.FAILED`
  with ``last_error`` populated; :class:`LiveOrchestrator` then pauses
  the affected account through ``AccountManager.pause_account`` and
  continues starting the rest.
- ``stop()`` is idempotent and never raises; the orchestrator can call
  it during graceful shutdown without per-session error handling.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

logger = logging.getLogger(__name__)


class SessionState(str, Enum):
    """Lifecycle states for a :class:`LiveAccountSession`."""

    PENDING = "pending"
    RUNNING = "running"
    FAILED = "failed"
    STOPPED = "stopped"


@dataclass
class LiveAccountSession:
    """Per-account live-trading session state.

    The class is the *only* authoritative record of which accounts the
    engine currently runs live. State transitions are explicit so the
    orchestrator can render an accurate health snapshot without having
    to query Nautilus internals.

    Attributes:
        account_id: Unique account identifier.
        state: Current lifecycle state. Always starts at PENDING.
        last_error: Set when the session enters FAILED.
        components: Bag of attached components (compliance actor,
            ``LiveNode``, ``RedisDataClient``, ``ZmqExecutionClient``).
            Story 10.5a leaves this empty; 10.5b/c populate it via
            :meth:`attach_components`.
    """

    account_id: str
    state: SessionState = SessionState.PENDING
    last_error: str | None = None
    components: dict[str, Any] = field(default_factory=dict)

    @property
    def is_running(self) -> bool:
        return self.state is SessionState.RUNNING

    @property
    def is_failed(self) -> bool:
        return self.state is SessionState.FAILED

    def attach_components(self, **components: Any) -> None:
        """Attach named components onto the session.

        Used by 10.5b/c to plug the Nautilus ``LiveNode``,
        ``RedisDataClient``, ``ZmqExecutionClient``, and the per-account
        ``PropFirmComplianceActor`` once they exist. Reserved for the
        orchestrator — strategies and rules should not reach into the
        session bag.
        """
        self.components.update(components)

    def mark_running(self) -> None:
        """Transition PENDING → RUNNING. Idempotent for already-RUNNING.

        Allow-list: only PENDING and RUNNING. Any future state added to
        :class:`SessionState` requires an explicit decision here so a new
        state cannot silently slip into RUNNING without being audited.
        """
        if self.state is SessionState.RUNNING:
            return
        if self.state is not SessionState.PENDING:
            raise RuntimeError(
                f"Cannot mark session {self.account_id} running from {self.state.value}"
            )
        self.state = SessionState.RUNNING
        self.last_error = None

    def mark_failed(self, error: str) -> None:
        """Transition any state → FAILED with an error string."""
        self.state = SessionState.FAILED
        self.last_error = error
        logger.warning(
            "LiveAccountSession %s marked FAILED: %s", self.account_id, error
        )

    def mark_stopped(self) -> None:
        """Transition any state → STOPPED. Idempotent."""
        self.state = SessionState.STOPPED
