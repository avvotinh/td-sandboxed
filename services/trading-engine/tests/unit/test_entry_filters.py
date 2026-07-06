"""Unit tests for Track 5.1 entry filters (redesign plan 2026-07-02).

Four config-gated, default-OFF entry-quality changes:

* **ADX gate** (``adx_gate_min``): trend entries (supertrend, donchian)
  blocked unless ADX(``adx_gate_period``) is initialised and >= the
  threshold. Targets the "breakout/flip in chop" failure mode.
* **Session filter** (``session_filter_tz``): out-of-session bars either
  force-flatten (trend policy) or only block fresh entries while letting
  exit logic run (MR policy).
* **Donchian crossing semantics** (``entry_on_cross_only``): enter only
  on the FIRST bar of a breakout episode — kills re-entry churn when the
  close rides outside the channel for many bars.
* **MR re-cross entry** (``entry_mode="recross"``): enter on the snap-back
  bar (prev close outside the band, current close back inside, RSI still
  extreme) instead of catching the falling knife on the pierce bar.

All tests drive ``generate_signal`` with mocked indicators, mirroring the
existing per-strategy test files.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.donchian_breakout import (
    DonchianBreakoutConfig,
    DonchianBreakoutStrategy,
)
from src.strategies.mean_reversion import (
    MeanReversionConfig,
    MeanReversionStrategy,
)
from src.strategies.supertrend import SupertrendConfig, SupertrendStrategy


pytestmark = pytest.mark.unit


def _ts_ns(iso_utc: str) -> int:
    """UTC ISO string → epoch nanoseconds (Bar.ts_init shape)."""
    dt = datetime.fromisoformat(iso_utc).replace(tzinfo=UTC)
    return int(dt.timestamp()) * 1_000_000_000

# 2024-01-15 is a Monday; America/New_York is EST (UTC-5) in January.
_IN_SESSION_NS = _ts_ns("2024-01-15T15:00:00")   # 10:00 NY — inside 07:00-16:00
_OUT_SESSION_NS = _ts_ns("2024-01-15T23:00:00")  # 18:00 NY — outside


def _mock_bar(close: float, ts_init: int = _IN_SESSION_NS) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    bar.ts_init = ts_init
    return bar


_SESSION_FIELDS = dict(
    session_filter_tz="America/New_York",
    session_filter_open_hour=7,
    session_filter_open_minute=0,
    session_filter_close_hour=16,
    session_filter_close_minute=0,
)


def _donchian(**overrides) -> DonchianBreakoutStrategy:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-HOUR-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
    )
    defaults.update(overrides)
    strategy = DonchianBreakoutStrategy(DonchianBreakoutConfig(**defaults))
    strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
    strategy._atr = Mock(initialized=True, value=5.0)
    strategy._prev_upper = 2418.0
    strategy._prev_lower = 2380.0
    return strategy


def _supertrend(**overrides) -> SupertrendStrategy:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-HOUR-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
    )
    defaults.update(overrides)
    strategy = SupertrendStrategy(SupertrendConfig(**defaults))
    strategy._supertrend = Mock(initialized=True, trend=1)
    strategy._atr = Mock(initialized=True, value=5.0)
    strategy._prev_trend = -1  # flip -1 → +1 pending: raw signal is BUY
    return strategy


def _mean_reversion(**overrides) -> MeanReversionStrategy:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-HOUR-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
    )
    defaults.update(overrides)
    strategy = MeanReversionStrategy(MeanReversionConfig(**defaults))
    strategy._bb = Mock(
        initialized=True, upper=2420.0, middle=2400.0, lower=2380.0
    )
    strategy._rsi = Mock(initialized=True, value=0.2)  # oversold zone
    strategy._atr = Mock(initialized=True, value=5.0)
    return strategy


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_defaults_off_are_valid(self) -> None:
        strategy = _donchian()
        assert strategy.config.adx_gate_min is None
        assert strategy.config.session_filter_tz is None

    @pytest.mark.parametrize("bad", [Decimal("0"), Decimal("-25")])
    def test_adx_gate_min_must_be_positive_when_set(self, bad: Decimal) -> None:
        with pytest.raises(ValueError, match="adx_gate_min"):
            _donchian(adx_gate_min=bad)

    def test_adx_gate_period_must_be_positive(self) -> None:
        with pytest.raises(ValueError, match="adx_gate_period"):
            _donchian(adx_gate_min=Decimal("25"), adx_gate_period=0)

    def test_unknown_session_tz_fails_fast(self) -> None:
        with pytest.raises(ValueError, match="session_filter_tz"):
            _donchian(**{**_SESSION_FIELDS, "session_filter_tz": "Mars/Olympus"})

    @pytest.mark.parametrize(
        "field, value",
        [
            ("session_filter_open_hour", 24),
            ("session_filter_open_minute", 60),
            ("session_filter_close_hour", -1),
            ("session_filter_close_minute", 99),
        ],
    )
    def test_session_window_bounds_validated(self, field: str, value: int) -> None:
        with pytest.raises(ValueError, match=field):
            _donchian(**{**_SESSION_FIELDS, field: value})

    def test_session_bounds_ignored_when_filter_off(self) -> None:
        # tz=None disables the filter; stale window fields must not raise
        # (mirrors the scale-out staged-YAML validation philosophy).
        strategy = _donchian(session_filter_open_hour=24)
        assert strategy.config.session_filter_tz is None

    def test_bad_exit_policy_rejected(self) -> None:
        with pytest.raises(ValueError, match="session_filter_exit_policy"):
            _donchian(
                **_SESSION_FIELDS, session_filter_exit_policy="hold_and_pray"
            )


# ---------------------------------------------------------------------------
# ADX gate
# ---------------------------------------------------------------------------


class TestAdxGate:
    def test_gate_off_creates_no_indicator(self) -> None:
        assert _donchian()._entry_adx is None
        assert _supertrend()._entry_adx is None

    def test_gate_on_creates_indicator_with_period(self) -> None:
        strategy = _donchian(adx_gate_min=Decimal("25"), adx_gate_period=14)
        assert strategy._entry_adx is not None
        assert strategy._entry_adx.period == 14

    def test_donchian_blocked_below_threshold(self) -> None:
        strategy = _donchian(adx_gate_min=Decimal("25"))
        strategy._entry_adx = Mock(initialized=True, value=18.0)
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.NONE

    def test_donchian_blocked_while_adx_warming_up(self) -> None:
        strategy = _donchian(adx_gate_min=Decimal("25"))
        strategy._entry_adx = Mock(initialized=False, value=None)
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.NONE

    def test_donchian_passes_at_threshold(self) -> None:
        strategy = _donchian(adx_gate_min=Decimal("25"))
        strategy._entry_adx = Mock(initialized=True, value=25.0)
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY

    def test_supertrend_blocked_below_threshold(self) -> None:
        strategy = _supertrend(adx_gate_min=Decimal("25"))
        strategy._entry_adx = Mock(initialized=True, value=10.0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_supertrend_passes_above_threshold(self) -> None:
        strategy = _supertrend(adx_gate_min=Decimal("25"))
        strategy._entry_adx = Mock(initialized=True, value=32.0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.BUY

    def test_supertrend_flip_state_still_advances_when_blocked(self) -> None:
        """A blocked flip must not re-fire when ADX later recovers —
        _prev_trend advances even though the signal is suppressed."""
        strategy = _supertrend(adx_gate_min=Decimal("25"))
        strategy._entry_adx = Mock(initialized=True, value=10.0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE
        # ADX recovers on the next bar, trend unchanged → no stale entry.
        strategy._entry_adx = Mock(initialized=True, value=30.0)
        assert strategy.generate_signal(_mock_bar(2401)) == SignalType.NONE

    def test_gate_off_signal_unaffected(self) -> None:
        assert _donchian().generate_signal(_mock_bar(2425)) == SignalType.BUY


# ---------------------------------------------------------------------------
# Session filter
# ---------------------------------------------------------------------------


class TestSessionFilterTrend:
    """Trend policy (default): force-flatten outside the window."""

    def test_filter_off_trades_any_hour(self) -> None:
        strategy = _donchian()
        bar = _mock_bar(2425, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.BUY

    def test_in_session_signal_passes(self) -> None:
        strategy = _donchian(**_SESSION_FIELDS)
        bar = _mock_bar(2425, ts_init=_IN_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.BUY

    def test_out_of_session_entry_blocked(self) -> None:
        strategy = _donchian(**_SESSION_FIELDS)
        bar = _mock_bar(2425, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.NONE

    def test_out_of_session_open_position_flattened(self) -> None:
        strategy = _donchian(**_SESSION_FIELDS)
        strategy._position = Mock(side=PositionSide.LONG)
        bar = _mock_bar(2400, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.CLOSE

    def test_supertrend_out_of_session_flattened(self) -> None:
        strategy = _supertrend(**_SESSION_FIELDS)
        strategy._position = Mock(side=PositionSide.LONG)
        bar = _mock_bar(2400, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.CLOSE


class TestSessionFilterBlockEntryPolicy:
    """MR policy: block fresh entries, let exit logic manage open trades."""

    def test_out_of_session_entry_blocked_when_flat(self) -> None:
        strategy = _mean_reversion(
            **_SESSION_FIELDS, session_filter_exit_policy="block_entry"
        )
        # close below lower band + RSI oversold = valid pierce entry setup
        bar = _mock_bar(2375, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.NONE

    def test_out_of_session_exit_logic_still_runs(self) -> None:
        strategy = _mean_reversion(
            **_SESSION_FIELDS, session_filter_exit_policy="block_entry"
        )
        strategy._position = Mock(side=PositionSide.LONG)
        # close reverted to middle band → the MR exit must still fire
        bar = _mock_bar(2401, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.CLOSE

    def test_out_of_session_no_flatten_before_target(self) -> None:
        strategy = _mean_reversion(
            **_SESSION_FIELDS, session_filter_exit_policy="block_entry"
        )
        strategy._position = Mock(side=PositionSide.LONG)
        # below middle band: reversion not complete — hold, don't flatten
        bar = _mock_bar(2390, ts_init=_OUT_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.NONE

    def test_in_session_entry_passes(self) -> None:
        strategy = _mean_reversion(
            **_SESSION_FIELDS, session_filter_exit_policy="block_entry"
        )
        bar = _mock_bar(2375, ts_init=_IN_SESSION_NS)
        assert strategy.generate_signal(bar) == SignalType.BUY


# ---------------------------------------------------------------------------
# Donchian crossing semantics
# ---------------------------------------------------------------------------


class TestDonchianCrossingSemantics:
    def test_default_level_triggered_reenters(self) -> None:
        """Legacy behaviour: every bar outside the channel signals."""
        strategy = _donchian()
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY
        strategy._prev_upper = 2418.0  # keep prior band pinned
        assert strategy.generate_signal(_mock_bar(2426)) == SignalType.BUY

    def test_cross_only_fires_on_first_breakout_bar(self) -> None:
        strategy = _donchian(entry_on_cross_only=True)
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY

    def test_cross_only_suppresses_consecutive_breakout_bars(self) -> None:
        strategy = _donchian(entry_on_cross_only=True)
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY
        strategy._prev_upper = 2418.0
        assert strategy.generate_signal(_mock_bar(2426)) == SignalType.NONE
        strategy._prev_upper = 2418.0
        assert strategy.generate_signal(_mock_bar(2427)) == SignalType.NONE

    def test_cross_only_rearms_after_close_back_inside(self) -> None:
        strategy = _donchian(entry_on_cross_only=True)
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY
        strategy._prev_upper = 2418.0
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE  # back in
        strategy._prev_upper = 2418.0
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY  # new episode

    def test_cross_only_applies_to_short_side(self) -> None:
        strategy = _donchian(entry_on_cross_only=True)
        strategy._prev_lower = 2382.0
        assert strategy.generate_signal(_mock_bar(2378)) == SignalType.SELL
        strategy._prev_upper = 2418.0
        strategy._prev_lower = 2382.0
        assert strategy.generate_signal(_mock_bar(2377)) == SignalType.NONE


# ---------------------------------------------------------------------------
# Mean-reversion re-cross entry
# ---------------------------------------------------------------------------


class TestMeanReversionRecross:
    def test_bad_entry_mode_rejected(self) -> None:
        with pytest.raises(ValueError, match="entry_mode"):
            _mean_reversion(entry_mode="yolo")

    def test_default_pierce_mode_unchanged(self) -> None:
        strategy = _mean_reversion()
        assert strategy.generate_signal(_mock_bar(2375)) == SignalType.BUY

    def test_recross_pierce_bar_does_not_enter(self) -> None:
        """The falling-knife bar (close outside band) must NOT enter."""
        strategy = _mean_reversion(entry_mode="recross")
        assert strategy.generate_signal(_mock_bar(2375)) == SignalType.NONE

    def test_recross_snapback_bar_enters_long(self) -> None:
        strategy = _mean_reversion(entry_mode="recross")
        assert strategy.generate_signal(_mock_bar(2375)) == SignalType.NONE  # pierce
        assert strategy.generate_signal(_mock_bar(2385)) == SignalType.BUY   # snap back

    def test_recross_requires_rsi_still_extreme(self) -> None:
        strategy = _mean_reversion(entry_mode="recross")
        assert strategy.generate_signal(_mock_bar(2375)) == SignalType.NONE
        strategy._rsi = Mock(initialized=True, value=0.5)  # RSI recovered
        assert strategy.generate_signal(_mock_bar(2385)) == SignalType.NONE

    def test_recross_short_side(self) -> None:
        strategy = _mean_reversion(entry_mode="recross")
        strategy._rsi = Mock(initialized=True, value=0.8)  # overbought
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.NONE  # pierce up
        assert strategy.generate_signal(_mock_bar(2415)) == SignalType.SELL  # snap back

    def test_recross_no_entry_when_never_pierced(self) -> None:
        strategy = _mean_reversion(entry_mode="recross")
        assert strategy.generate_signal(_mock_bar(2390)) == SignalType.NONE
        assert strategy.generate_signal(_mock_bar(2385)) == SignalType.NONE


# ---------------------------------------------------------------------------
# Session gate × rolling-reference freshness (review fix)
# ---------------------------------------------------------------------------


class TestSessionGateStateFreshness:
    """Rolling references (band/close snapshots, episode flags) must
    advance on session-gated bars too — the first in-session bar after a
    gap compares against the true prior bar, not a frozen pre-gap value."""

    def test_donchian_band_refs_advance_on_gated_bar(self) -> None:
        strategy = _donchian(**_SESSION_FIELDS)
        strategy._donchian = Mock(initialized=True, upper=2430.0, lower=2390.0)
        strategy.generate_signal(_mock_bar(2400, ts_init=_OUT_SESSION_NS))
        assert strategy._prev_upper == 2430.0
        assert strategy._prev_lower == 2390.0

    def test_donchian_cross_only_episode_spans_session_gap(self) -> None:
        """A breakout episode that began on a gated bar must not read as
        'first breakout bar' at session open."""
        strategy = _donchian(**_SESSION_FIELDS, entry_on_cross_only=True)
        gated = strategy.generate_signal(_mock_bar(2425, ts_init=_OUT_SESSION_NS))
        assert gated == SignalType.NONE  # out-of-session: no entry, episode arms
        strategy._prev_upper = 2418.0  # keep prior band pinned
        opened = strategy.generate_signal(_mock_bar(2426, ts_init=_IN_SESSION_NS))
        assert opened == SignalType.NONE  # still the same (overnight) episode

    def test_mr_recross_prev_close_advances_on_gated_bar(self) -> None:
        strategy = _mean_reversion(
            **_SESSION_FIELDS,
            session_filter_exit_policy="block_entry",
            entry_mode="recross",
        )
        # Pierce lands on a gated bar: entry blocked, but the reference
        # must advance …
        pierce = strategy.generate_signal(_mock_bar(2375, ts_init=_OUT_SESSION_NS))
        assert pierce == SignalType.NONE
        # … so the in-session snap-back bar sees the true previous close.
        snap = strategy.generate_signal(_mock_bar(2385, ts_init=_IN_SESSION_NS))
        assert snap == SignalType.BUY
