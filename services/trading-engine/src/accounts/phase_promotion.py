"""Phase promotion service (Epic 9 Phase 0, task P0.10).

Backs the ``trading-engine accounts promote --account X --phase Y`` CLI.
The two helpers here are pure: validation does not mutate state, and
``build_phase_transition_audit_entry`` returns an :class:`AuditEntry` for
the caller to persist via :class:`AuditService`. Mutating the underlying
``accounts.yaml`` config remains a manual ops step (the audit entry is
the canonical compliance record).

Why no YAML write-back: rewriting YAML loses comments/formatting and
introduces drift between repo state and runtime state. Operators edit
the YAML and restart the engine after the audit entry confirms the
intent; the audit row is the durable record either way.

Story 10.5e3 — :func:`publish_phase_change_event` posts a hot-reload
hint to Redis (``account:phase-changed:{account_id}``) so a running
engine can call :meth:`LiveOrchestrator.reload_account` without
waiting for a manual restart. The publish is best-effort: if Redis is
down or unset, the CLI still completes — the audit row is the
durable record either way.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from ..config.firm_registry import FirmRegistryError
from ..rules.audit_logger import AuditEntry, AuditEventType

if TYPE_CHECKING:
    from ..config.firm_profile import AccountPhase
    from ..config.firm_registry import FirmRegistry
    from ..state.redis_state import RedisStateManager

logger = logging.getLogger(__name__)


# Redis pub/sub channel prefix shared with
# :data:`engine.live_orchestrator.PHASE_CHANGED_CHANNEL_PREFIX`.
# Duplicated here (not imported) so the CLI doesn't pull in the engine
# module — keeps the CLI startup path light and the dependency tree
# one-directional (CLI → accounts → engine, not the reverse).
PHASE_CHANGED_CHANNEL_PREFIX = "account:phase-changed:"


class PhasePromotionError(ValueError):
    """Raised when a phase transition cannot be performed."""


def validate_phase_transition(
    account,
    firm_registry: "FirmRegistry",
    target_phase_id: str,
) -> tuple["AccountPhase", "AccountPhase"]:
    """Validate that ``account`` may transition to ``target_phase_id``.

    Returns ``(from_phase, to_phase)`` on success.

    Raises:
        PhasePromotionError: If the account is not firm-bound, the firm /
            product / phase identifiers do not resolve, the target phase
            equals the current phase, or the transition is not declared
            in the current phase's ``allowed_transitions``.
    """
    firm_id = getattr(account, "firm_id", None)
    product_id = getattr(account, "product_id", None)
    current_phase_id = getattr(account, "phase", None)
    if not firm_id or not product_id or not current_phase_id:
        raise PhasePromotionError(
            f"Account {getattr(account, 'id', '?')!r} is not firm-bound; "
            "cannot promote (set firm_id + product_id + phase first)"
        )

    if target_phase_id == current_phase_id:
        raise PhasePromotionError(
            f"Account {account.id!r} is already in phase {current_phase_id!r}"
        )

    try:
        _firm, _product, current_phase = firm_registry.resolve(
            firm_id, product_id, current_phase_id,
        )
    except FirmRegistryError as exc:
        raise PhasePromotionError(str(exc)) from exc

    try:
        _firm, _product, target_phase = firm_registry.resolve(
            firm_id, product_id, target_phase_id,
        )
    except FirmRegistryError as exc:
        raise PhasePromotionError(str(exc)) from exc

    if target_phase_id not in current_phase.allowed_transitions:
        allowed = ", ".join(current_phase.allowed_transitions) or "(none)"
        raise PhasePromotionError(
            f"Transition {current_phase_id!r} → {target_phase_id!r} "
            f"is not allowed by product {product_id!r}. "
            f"Allowed transitions: {allowed}"
        )

    return current_phase, target_phase


def build_phase_transition_audit_entry(
    *,
    account,
    from_phase: "AccountPhase",
    to_phase: "AccountPhase",
    reason: str,
    actor: str,
    correlation_id: str | None = None,
    timestamp: datetime | None = None,
) -> AuditEntry:
    """Construct an :class:`AuditEntry` recording the promotion intent.

    Per ``database/audit.md``, every audit row carries a correlation_id;
    one is auto-generated when not supplied so callers cannot accidentally
    omit it.
    """
    if not reason or not reason.strip():
        raise PhasePromotionError("reason must be non-empty")
    if not actor or not actor.strip():
        raise PhasePromotionError("actor must be non-empty")

    correlation_id = correlation_id or str(uuid.uuid4())

    return AuditEntry(
        timestamp=timestamp or datetime.now(timezone.utc),
        account_id=account.id,
        event_type=AuditEventType.SYSTEM_EVENT.value,
        event_subtype="phase_transition",
        source="cli",
        level="INFO",
        message=(
            f"Phase transition for {account.id}: "
            f"{from_phase.phase_id} → {to_phase.phase_id} "
            f"(reason: {reason}; correlation_id={correlation_id})"
        ),
        rule_name="",
        rule_result="",
        context={
            "firm_id": account.firm_id,
            "product_id": account.product_id,
            "from_phase": from_phase.phase_id,
            "to_phase": to_phase.phase_id,
            "reason": reason,
            "actor": actor,
            "correlation_id": correlation_id,
        },
    )


async def publish_phase_change_event(
    redis_manager: "RedisStateManager",
    *,
    account_id: str,
    from_phase: "AccountPhase",
    to_phase: "AccountPhase",
    correlation_id: str,
    timestamp: datetime | None = None,
) -> int:
    """Publish a hot-reload hint to ``account:phase-changed:{account_id}``.

    Returns the number of Redis subscribers that received the message
    (Redis ``PUBLISH`` return value). When the engine is offline this
    is ``0`` and the CLI proceeds with the manual-restart flow.

    Raises any exception from Redis — the caller is expected to log +
    continue (publish is best-effort vs the durable audit record).
    """
    payload = json.dumps(
        {
            "account_id": account_id,
            "from_phase": from_phase.phase_id,
            "to_phase": to_phase.phase_id,
            "correlation_id": correlation_id,
            "ts": (timestamp or datetime.now(timezone.utc)).isoformat(),
        },
        separators=(",", ":"),
    )
    channel = f"{PHASE_CHANGED_CHANNEL_PREFIX}{account_id}"
    return int(await redis_manager.client.publish(channel, payload))
