"""Regime audit adapter (Epic 11 story 11.5).

Translates a :class:`RegimeDecision` into the project-wide
:class:`AuditEntry` shape and forwards it to the shared bounded-queue
:class:`AuditWriter` shipped in story 10.3. The adapter is stateless;
state lives entirely in the writer.

The hot path uses ``log_async`` (queued, batched persistence) — the
regime classifier emits one decision per bar (~288/day on M5), well
within the writer's batch capacity, and a per-bar synchronous DB round
trip would dominate latency. Errors propagate to the caller: an audit
failure must abort routing rather than silently dropping the audit row,
which would breach the project's double-entry discipline (see
``.claude/rules/database/audit.md``).

``HIGH_VOLATILITY`` decisions log at ``WARNING`` because they trigger
the global kill-switch; every other state logs at ``INFO``. Regime
decisions are not bound to any single account — they apply to every
strategy subscribed to the same ``BarType`` — so ``account_id`` is
``None``.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Protocol, assert_never, runtime_checkable

from src.regime.decision import RegimeDecision
from src.regime.states import RegimeState
from src.rules.audit_logger import AuditEntry


@runtime_checkable
class _AuditWriter(Protocol):
    """Subset of :class:`AuditWriter` the adapter needs."""

    async def log_async(self, entry: AuditEntry) -> None: ...


def _audit_level_for(state: RegimeState) -> str:
    # Match exhaustively so a future RegimeState member breaks the build
    # rather than silently inheriting "INFO" — a kill-switch-worthy state
    # mis-classified as INFO would slip past audit-log severity filters.
    match state:
        case RegimeState.HIGH_VOLATILITY:
            return "WARNING"
        case (
            RegimeState.TRENDING_UP
            | RegimeState.TRENDING_DOWN
            | RegimeState.RANGING
            | RegimeState.UNKNOWN
        ):
            return "INFO"
        case _:
            assert_never(state)


class RegimeAuditAdapter:
    """Converts ``RegimeDecision`` → ``AuditEntry`` and persists via
    :class:`AuditWriter`."""

    def __init__(self, audit_writer: _AuditWriter) -> None:
        self._writer = audit_writer

    async def log(self, decision: RegimeDecision) -> None:
        entry = self._to_entry(decision)
        await self._writer.log_async(entry)

    @staticmethod
    def _to_entry(decision: RegimeDecision) -> AuditEntry:
        pending = (
            decision.pending_state.value
            if decision.pending_state is not None
            else None
        )
        return AuditEntry(
            timestamp=decision.timestamp,
            account_id=None,
            event_type="regime_decision",
            rule_name="regime_classifier",
            rule_result=decision.current_state.value,
            current_value=decision.confidence,
            threshold_value=None,
            order_id=None,
            context={
                "bar_type": str(decision.bar_type),
                "raw_state": decision.raw_state.value,
                "pending_state": pending,
                "bars_in_pending": decision.bars_in_pending,
                "features": asdict(decision.features),
            },
            event_subtype=None,
            source="regime-classifier",
            level=_audit_level_for(decision.current_state),
            message=(
                f"Regime: {decision.current_state.value} "
                f"(confidence={decision.confidence:.2f})"
            ),
            trade_id=None,
        )


__all__ = ["RegimeAuditAdapter"]
