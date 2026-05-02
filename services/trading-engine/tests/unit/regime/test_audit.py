"""Unit tests for ``RegimeAuditAdapter`` (Epic 11 story 11.5).

The adapter translates one ``RegimeDecision`` (from the hysteresis
filter, story 11.4) into an ``AuditEntry`` and forwards it to the
shared :class:`AuditWriter` (story 10.3 path) via ``log_async``. The
audit hop runs **before** the per-account routing dispatch (story 11.7
AC2) so every regime call is captured for FTMO audit, even when the
classifier produces UNKNOWN or the kill-switch fires.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import pytest

from src.regime.audit import RegimeAuditAdapter
from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.states import RegimeState
from src.rules.audit_logger import AuditEntry

BAR_TYPE = "XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL"


class _RecordingAuditWriter:
    """Minimal stand-in matching the AuditWriter.log_async surface.

    ``log_sync`` is recorded only so a regression where the adapter
    accidentally takes the synchronous path would assert visibly — it is
    not part of the ``_AuditWriter`` Protocol the adapter consumes.
    """

    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []
        self.sync_entries: list[AuditEntry] = []

    async def log_async(self, entry: AuditEntry) -> None:
        self.entries.append(entry)

    async def log_sync(self, entry: AuditEntry) -> None:
        self.sync_entries.append(entry)


def _features(**overrides: object) -> RegimeFeatures:
    base: dict[str, Any] = dict(
        adx=30.0,
        plus_di=30.0,
        minus_di=15.0,
        bb_width_pct=0.50,
        realized_vol=0.012,
        ema_slope=0.001,
        is_warmed_up=True,
    )
    base.update(overrides)
    return RegimeFeatures(**base)


def _decision(**overrides: object) -> RegimeDecision:
    base: dict[str, Any] = dict(
        timestamp=datetime(2026, 5, 1, 12, 30, tzinfo=timezone.utc),
        bar_type=BAR_TYPE,
        current_state=RegimeState.TRENDING_UP,
        raw_state=RegimeState.TRENDING_UP,
        pending_state=None,
        bars_in_pending=0,
        features=_features(),
        confidence=0.85,
    )
    base.update(overrides)
    return RegimeDecision(**base)


@pytest.fixture
def writer() -> _RecordingAuditWriter:
    return _RecordingAuditWriter()


@pytest.fixture
def adapter(writer: _RecordingAuditWriter) -> RegimeAuditAdapter:
    return RegimeAuditAdapter(writer)


# ---------------------------------------------------------------------------
# Translation — every RegimeDecision field surfaces in AuditEntry
# ---------------------------------------------------------------------------


class TestTranslation:
    @pytest.mark.asyncio
    async def test_log_uses_log_async(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        # Audit writes batch behind a queue; the regime hot path must
        # never use log_sync (would block per-bar on a DB round trip).
        await adapter.log(_decision())
        assert len(writer.entries) == 1
        assert writer.sync_entries == []

    @pytest.mark.asyncio
    async def test_event_type_and_source_are_fixed(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        await adapter.log(_decision())
        e = writer.entries[0]
        assert e.event_type == "regime_decision"
        assert e.source == "regime-classifier"
        assert e.rule_name == "regime_classifier"

    @pytest.mark.asyncio
    async def test_account_id_is_none(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        # Regime decisions are per-instrument, not per-account: every
        # bound account on the same bar_type sees the same regime state.
        await adapter.log(_decision())
        assert writer.entries[0].account_id is None

    @pytest.mark.asyncio
    async def test_timestamp_passes_through(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        ts = datetime(2026, 5, 2, 6, 15, tzinfo=timezone.utc)
        await adapter.log(_decision(timestamp=ts))
        assert writer.entries[0].timestamp is ts

    @pytest.mark.asyncio
    async def test_rule_result_carries_current_state_value(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        await adapter.log(_decision(current_state=RegimeState.RANGING))
        assert writer.entries[0].rule_result == "ranging"

    @pytest.mark.asyncio
    async def test_current_value_carries_confidence(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        await adapter.log(_decision(confidence=0.42))
        assert writer.entries[0].current_value == pytest.approx(0.42)

    @pytest.mark.asyncio
    async def test_context_carries_routing_inputs(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        d = _decision(
            current_state=RegimeState.TRENDING_UP,
            raw_state=RegimeState.RANGING,
            pending_state=RegimeState.RANGING,
            bars_in_pending=1,
            features=_features(adx=33.5, ema_slope=0.0007),
        )
        await adapter.log(d)
        ctx = writer.entries[0].context
        assert ctx["bar_type"] == BAR_TYPE
        assert ctx["raw_state"] == "ranging"
        assert ctx["pending_state"] == "ranging"
        assert ctx["bars_in_pending"] == 1
        # Feature snapshot must capture every numeric field for replay.
        assert ctx["features"]["adx"] == pytest.approx(33.5)
        assert ctx["features"]["ema_slope"] == pytest.approx(0.0007)
        assert ctx["features"]["is_warmed_up"] is True

    @pytest.mark.asyncio
    async def test_pending_state_none_serialised_as_null(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        # JSON serialisation downstream expects None, not the string
        # "None" — keeping it native preserves NULL columns in the
        # audit_logs hypertable.
        await adapter.log(_decision(pending_state=None))
        assert writer.entries[0].context["pending_state"] is None

    @pytest.mark.asyncio
    async def test_message_is_human_readable(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        await adapter.log(_decision(confidence=0.71))
        msg = writer.entries[0].message
        assert msg is not None
        assert "trending_up" in msg
        assert "0.71" in msg


# ---------------------------------------------------------------------------
# Severity — HIGH_VOLATILITY escalates because routing is blocked
# ---------------------------------------------------------------------------


class TestSeverity:
    @pytest.mark.asyncio
    async def test_high_volatility_logs_at_warning(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        await adapter.log(
            _decision(current_state=RegimeState.HIGH_VOLATILITY)
        )
        assert writer.entries[0].level == "WARNING"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "state",
        [
            RegimeState.TRENDING_UP,
            RegimeState.TRENDING_DOWN,
            RegimeState.RANGING,
            RegimeState.UNKNOWN,
        ],
    )
    async def test_non_kill_switch_states_log_at_info(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
        state: RegimeState,
    ):
        await adapter.log(
            _decision(current_state=state, raw_state=state, confidence=0.5)
        )
        assert writer.entries[0].level == "INFO"


# ---------------------------------------------------------------------------
# Security — context must be safe for audit log persistence
# ---------------------------------------------------------------------------


class TestContextSafety:
    @pytest.mark.asyncio
    async def test_context_contains_no_unexpected_keys(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        # Drift in the context dict shape would silently change audit row
        # semantics — pin the exact key set.
        await adapter.log(_decision())
        ctx = writer.entries[0].context
        assert set(ctx) == {
            "bar_type",
            "raw_state",
            "pending_state",
            "bars_in_pending",
            "features",
        }

    @pytest.mark.asyncio
    async def test_features_dict_uses_primitives_only(
        self,
        adapter: RegimeAuditAdapter,
        writer: _RecordingAuditWriter,
    ):
        # JSON-serialising AuditEntry.context must succeed; no enum or
        # dataclass instances may leak through.
        await adapter.log(_decision())
        ctx = writer.entries[0].context
        # Round-trip through JSON to prove every value is primitive.
        json.dumps(ctx)
        for key, value in ctx["features"].items():
            assert isinstance(value, (int, float, bool)), (
                f"features[{key!r}] = {value!r} is not a primitive"
            )

    @pytest.mark.asyncio
    async def test_writer_exception_propagates(
        self,
        adapter: RegimeAuditAdapter,
    ):
        # Audit failures must surface to the caller — silently swallowing
        # them would let routing proceed without an audit row, breaking
        # FTMO double-entry discipline.
        class BoomWriter:
            async def log_async(self, entry: AuditEntry) -> None:
                raise RuntimeError("db down")

            async def log_sync(self, entry: AuditEntry) -> None:
                raise RuntimeError("db down")

        a = RegimeAuditAdapter(BoomWriter())  # type: ignore[arg-type]
        with pytest.raises(RuntimeError, match="db down"):
            await a.log(_decision())
