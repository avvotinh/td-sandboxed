"""Unit tests for EquityRecorderActor (Contract v2 P1, gap G2).

The actor is exercised via its public methods (``record_equity``,
``on_bar`` with a patched equity read) — the same pattern as the
``PropFirmComplianceActor`` tests, since the Nautilus ``Actor`` base is
Cython and its ``portfolio`` attribute cannot be mocked directly. No
prop-firm actor or rule engine is involved anywhere in this module —
that decoupling is the point of the recorder.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.common.actor import Actor
from nautilus_trader.common.config import ActorConfig

from src.lab.recorder.equity_recorder import (
    EquityRecorderActor,
    EquityRecorderActorConfig,
)

pytestmark = pytest.mark.unit


def _make_actor() -> EquityRecorderActor:
    """Actor on the unit-test path: no bar_type, no venue."""
    return EquityRecorderActor(
        config=EquityRecorderActorConfig(initial_balance=Decimal("100000"))
    )


class TestActorShape:
    def test_is_nautilus_actor(self) -> None:
        assert isinstance(_make_actor(), Actor)

    def test_config_is_actor_config(self) -> None:
        assert issubclass(EquityRecorderActorConfig, ActorConfig)


class TestRecordEquity:
    def test_curve_accumulates_in_order(self) -> None:
        actor = _make_actor()
        ts0 = datetime(2026, 1, 1, tzinfo=UTC)
        actor.record_equity(ts=ts0, equity=Decimal("100000"))
        actor.record_equity(
            ts=ts0 + timedelta(minutes=5), equity=Decimal("100500")
        )
        assert actor.equity_curve == [
            (ts0, Decimal("100000")),
            (ts0 + timedelta(minutes=5), Decimal("100500")),
        ]

    def test_equity_curve_returns_defensive_copy(self) -> None:
        actor = _make_actor()
        actor.record_equity(
            ts=datetime(2026, 1, 1, tzinfo=UTC), equity=Decimal("100000")
        )
        actor.equity_curve.clear()
        assert len(actor.equity_curve) == 1


class TestOnBar:
    def test_records_one_point_per_bar(self) -> None:
        """on_bar reads equity and appends with the bar's UTC timestamp."""
        actor = _make_actor()
        equities = iter([Decimal("100000"), Decimal("100250")])
        actor._read_equity = lambda: next(equities)  # type: ignore[method-assign]

        ts_ns = 1_700_000_000_000_000_000
        actor.on_bar(Mock(ts_init=ts_ns))
        actor.on_bar(Mock(ts_init=ts_ns + 300_000_000_000))

        curve = actor.equity_curve
        assert [equity for _, equity in curve] == [
            Decimal("100000"),
            Decimal("100250"),
        ]
        assert curve[0][0] == datetime.fromtimestamp(
            ts_ns // 1_000_000_000, tz=UTC
        )
        assert all(ts.tzinfo is not None for ts, _ in curve)

    def test_none_equity_skips_the_bar(self) -> None:
        """Warm-up ``None`` reads must not append placeholder points."""
        actor = _make_actor()
        actor._read_equity = lambda: None  # type: ignore[method-assign]
        actor.on_bar(Mock(ts_init=1_700_000_000_000_000_000))
        assert actor.equity_curve == []

    def test_no_venue_is_noop(self) -> None:
        """Unit-test path (venue=None): _read_equity yields None → no-op."""
        actor = _make_actor()
        actor.on_bar(Mock(ts_init=1_700_000_000_000_000_000))
        assert actor.equity_curve == []
