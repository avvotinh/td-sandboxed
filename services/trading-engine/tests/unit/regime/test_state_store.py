"""Unit tests for RegimeStateStore + RegimeSnapshot (Epic 15 story 15.2)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.regime.decision import RegimeDecision
from src.regime.features import RegimeFeatures
from src.regime.state_store import RegimeSnapshot, RegimeStateStore
from src.regime.states import RegimeState


def _features() -> RegimeFeatures:
    return RegimeFeatures(
        adx=25.0, plus_di=22.0, minus_di=11.0, bb_width_pct=0.5,
        realized_vol=0.1, ema_slope=0.001, is_warmed_up=True,
    )


def _decision(
    bar_type: str,
    state: RegimeState,
    *,
    confidence: float = 0.8,
    ts: datetime | None = None,
) -> RegimeDecision:
    return RegimeDecision(
        timestamp=ts or datetime(2025, 6, 1, 12, 0, tzinfo=UTC),
        bar_type=bar_type,
        current_state=state,
        raw_state=state,
        pending_state=None,
        bars_in_pending=0,
        features=_features(),
        confidence=confidence,
    )


@pytest.mark.unit
class TestRegimeStateStore:
    def test_publish_then_current_round_trips(self) -> None:
        store = RegimeStateStore()
        store.publish(_decision("XAUUSD.M5", RegimeState.TRENDING_UP, confidence=0.9))
        snap = store.current("XAUUSD.M5")
        assert isinstance(snap, RegimeSnapshot)
        assert snap.bar_type == "XAUUSD.M5"
        assert snap.current_state == RegimeState.TRENDING_UP
        assert snap.confidence == 0.9
        assert snap.features.adx == 25.0

    def test_unknown_bar_type_returns_none(self) -> None:
        # "No confirmed regime" — strategies suppress entry on this.
        assert RegimeStateStore().current("NEVER.PUBLISHED") is None

    def test_per_bar_type_isolation(self) -> None:
        store = RegimeStateStore()
        store.publish(_decision("XAUUSD.M5", RegimeState.TRENDING_UP))
        store.publish(_decision("XAUUSD.M15", RegimeState.RANGING))
        assert store.current("XAUUSD.M5").current_state == RegimeState.TRENDING_UP
        assert store.current("XAUUSD.M15").current_state == RegimeState.RANGING

    def test_publish_replaces_not_mutates(self) -> None:
        store = RegimeStateStore()
        store.publish(_decision("XAUUSD.M5", RegimeState.RANGING))
        first = store.current("XAUUSD.M5")
        store.publish(_decision("XAUUSD.M5", RegimeState.HIGH_VOLATILITY))
        second = store.current("XAUUSD.M5")
        assert second.current_state == RegimeState.HIGH_VOLATILITY
        # the earlier snapshot object is unchanged (frozen, replaced not mutated)
        assert first.current_state == RegimeState.RANGING
        assert first is not second

    def test_snapshot_is_frozen(self) -> None:
        store = RegimeStateStore()
        store.publish(_decision("XAUUSD.M5", RegimeState.TRENDING_DOWN))
        snap = store.current("XAUUSD.M5")
        with pytest.raises((AttributeError, TypeError)):
            snap.current_state = RegimeState.RANGING  # type: ignore[misc]
