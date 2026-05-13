"""Unit tests for BracketScaleOutMixin state machine (Story 13.4).

Table-driven cases per implementation plan §3.1. Trail-tightening
specifics (cases #10, #11) belong to story 13.6 — this file covers the
state-machine transitions and delegation; the mixin's
``_update_trailing_sl`` is a no-op stub here.

Config invariants (#13 ``scale_out_close_fraction in (0, 1)``) are
already covered in ``test_bracket_strategy_mixin.py``
``TestBracketScaleOutConfigInvariants`` (story 13.2) and intentionally
not duplicated here.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.enums import OrderSide

from src.strategies.bracket_scale_out import (
    BracketScaleOutMixin,
    _ScaleOutSetup,
    _ScaleOutTradeState,
)


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> Mock:
    """Stub the BracketStrategyConfig surface the mixin reads."""
    cfg = Mock()
    cfg.scale_out_enabled = True
    cfg.scale_out_r_trigger = Decimal("1.0")
    cfg.scale_out_close_fraction = Decimal("0.5")
    cfg.breakeven_at_r = Decimal("1.0")
    cfg.trailing_enabled = False
    for k, v in overrides.items():
        setattr(cfg, k, v)
    return cfg


class _Host(BracketScaleOutMixin):
    """Test host: stubs the mixin's duck-typed dependencies.

    Calls ``super().__init__()`` so the mixin's own __init__ runs and
    sets ``_scale_state = None`` — keeps the test path honest with
    production initialisation order.
    """

    def __init__(self, config, *, supertrend_trail=None) -> None:
        super().__init__()
        self.config = config
        # Helpers the mixin invokes — all mocked so we can assert
        # call sequences without booting Nautilus.
        self._close_partial = Mock(return_value=Mock(name="Order"))
        self._modify_sl = Mock(return_value=True)
        self._log = Mock()
        # Supertrend trail indicator — only tests in TestTrailUpdate
        # provide a real-ish stub; everywhere else the trail body is
        # bypassed via mock-of-mock on _update_trailing_sl below.
        self._supertrend_trail = supertrend_trail
        # _update_trailing_sl is the real method on the mixin — wrap
        # it so tests can assert delegation while still exercising the
        # body when supertrend_trail is provided. Tests that want to
        # bypass the body entirely can rebind this to ``Mock()``.
        self._update_trailing_sl = Mock(wraps=self._update_trailing_sl)


@pytest.fixture
def host() -> _Host:
    return _Host(_make_config())


@pytest.fixture
def host_long(host: _Host) -> _Host:
    """LONG entry=2000, SL=1990 → risk_per_unit=10 (1R = +10 price)."""
    host._init_scale_state(
        side=OrderSide.BUY,
        entry_price=Decimal("2000"),
        sl_price=Decimal("1990"),
        qty=Decimal("1.0"),
    )
    return host


@pytest.fixture
def host_short(host: _Host) -> _Host:
    """SHORT entry=2000, SL=2010 → risk_per_unit=10 (1R = -10 price)."""
    host._init_scale_state(
        side=OrderSide.SELL,
        entry_price=Decimal("2000"),
        sl_price=Decimal("2010"),
        qty=Decimal("1.0"),
    )
    return host


# ---------------------------------------------------------------------------
# Case 1 — disabled: _init_scale_state must not capture state
# ---------------------------------------------------------------------------


class TestDisabledFlag:
    def test_no_scale_out_when_disabled(self) -> None:
        cfg = _make_config(scale_out_enabled=False)
        host = _Host(cfg)
        host._init_scale_state(
            side=OrderSide.BUY,
            entry_price=Decimal("2000"),
            sl_price=Decimal("1990"),
            qty=Decimal("1.0"),
        )
        assert host._scale_state is None

    def test_evaluate_no_op_when_state_none(self, host: _Host) -> None:
        # Defensive: evaluate called before init must not raise.
        host.evaluate_scale_out(Decimal("2010"))
        host._close_partial.assert_not_called()
        host._modify_sl.assert_not_called()


# ---------------------------------------------------------------------------
# Cases 2-5 — scale-out trigger (long, short, idempotent, below threshold)
# ---------------------------------------------------------------------------


class TestScaleOutTrigger:
    def test_scale_out_triggers_at_1r_long(self, host_long: _Host) -> None:
        host_long.evaluate_scale_out(Decimal("2010"))  # exactly +1R

        host_long._close_partial.assert_called_once_with(Decimal("0.5"))
        assert host_long._scale_state.scaled_out is True

    def test_scale_out_triggers_at_1r_short(self, host_short: _Host) -> None:
        host_short.evaluate_scale_out(Decimal("1990"))  # exactly +1R for SHORT

        host_short._close_partial.assert_called_once_with(Decimal("0.5"))
        assert host_short._scale_state.scaled_out is True

    def test_scale_out_idempotent(self, host_long: _Host) -> None:
        # Five evaluations at the same +1R price — only one partial
        # close should fire.
        for _ in range(5):
            host_long.evaluate_scale_out(Decimal("2010"))

        assert host_long._close_partial.call_count == 1

    def test_scale_out_not_triggered_below_1r_long(
        self, host_long: _Host
    ) -> None:
        # +0.99R = 2009.9; threshold is 1.0R = 2010.
        host_long.evaluate_scale_out(Decimal("2009.9"))

        host_long._close_partial.assert_not_called()
        assert host_long._scale_state.scaled_out is False

    def test_scale_out_not_triggered_below_1r_short(
        self, host_short: _Host
    ) -> None:
        # +0.99R for SHORT = 1990.1.
        host_short.evaluate_scale_out(Decimal("1990.1"))

        host_short._close_partial.assert_not_called()


# ---------------------------------------------------------------------------
# Cases 6-8 — breakeven move (post scale-out, idempotent, None config)
# ---------------------------------------------------------------------------


class TestBreakevenMove:
    def test_breakeven_move_after_scale_out(self, host_long: _Host) -> None:
        # +1R hits both triggers (scale-out + BE) on the same bar.
        host_long.evaluate_scale_out(Decimal("2010"))

        host_long._modify_sl.assert_called_once_with(Decimal("2000"))
        assert host_long._scale_state.breakeven_moved is True

    def test_breakeven_idempotent(self, host_long: _Host) -> None:
        for _ in range(5):
            host_long.evaluate_scale_out(Decimal("2010"))

        assert host_long._modify_sl.call_count == 1

    def test_no_breakeven_when_config_none(self) -> None:
        # breakeven_at_r=None means "scale out, but keep original SL on
        # the remainder" — useful for operators who want partial profit
        # without giving up runner downside protection.
        cfg = _make_config(breakeven_at_r=None)
        host = _Host(cfg)
        host._init_scale_state(
            side=OrderSide.BUY,
            entry_price=Decimal("2000"),
            sl_price=Decimal("1990"),
            qty=Decimal("1.0"),
        )

        host.evaluate_scale_out(Decimal("2010"))

        host._close_partial.assert_called_once()
        host._modify_sl.assert_not_called()
        assert host._scale_state.breakeven_moved is False

    def test_breakeven_below_scale_out_trigger(self) -> None:
        # be_at_r=0.5 < scale_out_r=1.0 — at +0.5R the partial close
        # has not yet fired, so BE must NOT fire either.
        cfg = _make_config(
            scale_out_r_trigger=Decimal("1.0"),
            breakeven_at_r=Decimal("0.5"),
        )
        host = _Host(cfg)
        host._init_scale_state(
            side=OrderSide.BUY,
            entry_price=Decimal("2000"),
            sl_price=Decimal("1990"),
            qty=Decimal("1.0"),
        )

        host.evaluate_scale_out(Decimal("2005"))  # +0.5R

        host._close_partial.assert_not_called()
        host._modify_sl.assert_not_called()


# ---------------------------------------------------------------------------
# Case 9 — trailing only after breakeven (delegation, not body)
# ---------------------------------------------------------------------------


class TestTrailingActivation:
    def test_trailing_not_active_before_breakeven(self) -> None:
        cfg = _make_config(trailing_enabled=True)
        host = _Host(cfg)
        host._init_scale_state(
            side=OrderSide.BUY,
            entry_price=Decimal("2000"),
            sl_price=Decimal("1990"),
            qty=Decimal("1.0"),
        )

        # Below +1R: nothing fires.
        host.evaluate_scale_out(Decimal("2005"))

        assert host._scale_state.trail_active is False
        host._update_trailing_sl.assert_not_called()

    def test_trailing_activates_after_breakeven(self) -> None:
        cfg = _make_config(trailing_enabled=True)
        host = _Host(cfg)
        host._init_scale_state(
            side=OrderSide.BUY,
            entry_price=Decimal("2000"),
            sl_price=Decimal("1990"),
            qty=Decimal("1.0"),
        )

        host.evaluate_scale_out(Decimal("2010"))

        assert host._scale_state.trail_active is True
        # Trail also runs in the same bar that activates it (so the
        # current price is reflected in the trail line right away).
        host._update_trailing_sl.assert_called_once()

    def test_trailing_disabled_by_config(self, host_long: _Host) -> None:
        # trailing_enabled=False (default fixture) — even after BE move,
        # _update_trailing_sl must never be called.
        host_long.evaluate_scale_out(Decimal("2010"))
        host_long.evaluate_scale_out(Decimal("2020"))

        assert host_long._scale_state.trail_active is False
        host_long._update_trailing_sl.assert_not_called()


# ---------------------------------------------------------------------------
# Case 12 — state reset on position close
# ---------------------------------------------------------------------------


class TestStateReset:
    def test_state_reset_on_position_close(self, host_long: _Host) -> None:
        assert host_long._scale_state is not None

        host_long._clear_scale_state()

        assert host_long._scale_state is None

    def test_clear_is_idempotent(self, host: _Host) -> None:
        host._clear_scale_state()
        host._clear_scale_state()
        assert host._scale_state is None


# ---------------------------------------------------------------------------
# Defensive — risk_per_unit edge cases
# ---------------------------------------------------------------------------


class TestRiskPerUnitGuard:
    def test_zero_risk_no_op(self, host: _Host) -> None:
        # Entry == SL is a degenerate config; rather than divide-by-zero,
        # evaluate_scale_out must skip cleanly.
        host._init_scale_state(
            side=OrderSide.BUY,
            entry_price=Decimal("2000"),
            sl_price=Decimal("2000"),
            qty=Decimal("1.0"),
        )

        host.evaluate_scale_out(Decimal("2010"))

        host._close_partial.assert_not_called()
        host._modify_sl.assert_not_called()


# ---------------------------------------------------------------------------
# State dataclass surface
# ---------------------------------------------------------------------------


class TestScaleOutTradeState:
    def test_default_flags_all_false(self) -> None:
        st = _ScaleOutTradeState(
            setup=_ScaleOutSetup(
                entry_price=Decimal("2000"),
                initial_sl=Decimal("1990"),
                initial_qty=Decimal("1.0"),
                side=OrderSide.BUY,
                risk_per_unit=Decimal("10"),
            ),
            current_sl=Decimal("1990"),
        )
        assert st.scaled_out is False
        assert st.breakeven_moved is False
        assert st.trail_active is False
        assert st.current_sl == Decimal("1990")

    def test_setup_is_frozen(self) -> None:
        # Frozen guarantees the captured fields cannot be silently
        # rewritten mid-trade — corruption of risk_per_unit would
        # poison the R-multiple math in evaluate_scale_out.
        from dataclasses import FrozenInstanceError

        setup = _ScaleOutSetup(
            entry_price=Decimal("2000"),
            initial_sl=Decimal("1990"),
            initial_qty=Decimal("1.0"),
            side=OrderSide.BUY,
            risk_per_unit=Decimal("10"),
        )
        with pytest.raises(FrozenInstanceError):
            setup.entry_price = Decimal("9999")  # type: ignore[misc]

    def test_state_capture_via_init(self, host_long: _Host) -> None:
        st = host_long._scale_state
        assert st is not None
        assert st.setup.entry_price == Decimal("2000")
        assert st.setup.initial_sl == Decimal("1990")
        assert st.setup.side == OrderSide.BUY
        assert st.setup.risk_per_unit == Decimal("10")
        assert st.setup.initial_qty == Decimal("1.0")

    def test_current_sl_tracks_initial_sl_at_init(
        self, host_long: _Host
    ) -> None:
        # Story 13.6: current_sl tracks the live SL trigger so the trail
        # body can compare candidate trail lines against the live SL.
        # Until BE / trail moves, current_sl mirrors initial_sl.
        assert host_long._scale_state.current_sl == Decimal("1990")

    def test_current_sl_updates_to_entry_on_breakeven(
        self, host_long: _Host
    ) -> None:
        host_long.evaluate_scale_out(Decimal("2010"))  # +1R fires BE move

        assert host_long._scale_state.breakeven_moved is True
        assert host_long._scale_state.current_sl == Decimal("2000")  # entry


# ---------------------------------------------------------------------------
# Story 13.6 — _update_trailing_sl body (plan §3.1 cases #10, #11)
# ---------------------------------------------------------------------------


def _stub_trail(*, value: float | None, trend: int, initialized: bool = True) -> Mock:
    """Stub the Supertrend trail indicator surface."""
    trail = Mock()
    trail.value = value
    trail.trend = trend
    trail.initialized = initialized
    return trail


def _post_be_state(side: OrderSide) -> _ScaleOutTradeState:
    """Build a state record already past BE move so the trail body runs."""
    if side == OrderSide.BUY:
        setup = _ScaleOutSetup(
            entry_price=Decimal("2000"),
            initial_sl=Decimal("1990"),
            initial_qty=Decimal("1.0"),
            side=OrderSide.BUY,
            risk_per_unit=Decimal("10"),
        )
        current_sl = Decimal("2000")  # at BE
    else:
        setup = _ScaleOutSetup(
            entry_price=Decimal("2000"),
            initial_sl=Decimal("2010"),
            initial_qty=Decimal("1.0"),
            side=OrderSide.SELL,
            risk_per_unit=Decimal("10"),
        )
        current_sl = Decimal("2000")  # at BE
    return _ScaleOutTradeState(
        setup=setup,
        scaled_out=True,
        breakeven_moved=True,
        trail_active=True,
        current_sl=current_sl,
    )


class TestTrailUpdate:
    """Plan §3.1 #10 + #11 — trail tightens-only, never loosens.

    Tests bypass the ``Mock(wraps=...)`` indirection by re-binding the
    real method back onto the host instance.
    """

    def _bind_real_trail_body(self, host: _Host) -> None:
        # Drop the Mock wrap so we exercise the real _update_trailing_sl
        # body. The wrap is set in _Host.__init__ for delegation tests
        # in earlier test classes.
        del host._update_trailing_sl

    def test_skipped_when_trail_indicator_not_initialized(self) -> None:
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=None, trend=0, initialized=False)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)

        host._update_trailing_sl(_post_be_state(OrderSide.BUY))

        host._modify_sl.assert_not_called()

    def test_skipped_when_trail_value_none(self) -> None:
        # Belt-and-braces: even if initialized=True, value=None means
        # the indicator has nothing to give us.
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=None, trend=1, initialized=True)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)

        host._update_trailing_sl(_post_be_state(OrderSide.BUY))

        host._modify_sl.assert_not_called()

    def test_long_tightens_when_trail_above_current_sl(self) -> None:
        # LONG @ 2000 BE'd to 2000. Trail line at 2005 (above BE) →
        # tighten by moving SL up to 2005.
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=2005.0, trend=1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.BUY)

        host._update_trailing_sl(state)

        host._modify_sl.assert_called_once_with(Decimal("2005.0"))
        assert state.current_sl == Decimal("2005.0")

    def test_long_does_not_loosen_when_trail_below_current_sl(self) -> None:
        # Plan §3.1 #11: trail line dropped back below current SL.
        # Skip the modify — never move SL further from price.
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=1995.0, trend=1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.BUY)

        host._update_trailing_sl(state)

        host._modify_sl.assert_not_called()
        assert state.current_sl == Decimal("2000")  # unchanged

    def test_long_skips_when_trail_equal_current_sl(self) -> None:
        # Strict tighten: equal = no-op (saves an unneeded modify call).
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=2000.0, trend=1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.BUY)

        host._update_trailing_sl(state)

        host._modify_sl.assert_not_called()

    def test_long_skips_when_trail_trend_flipped_to_short(self) -> None:
        # Trail Supertrend flipped to downtrend mid-trade. value would
        # be final_upper (above price) — applying it as LONG SL is
        # invalid (would close immediately). Side-check filters it out.
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=2050.0, trend=-1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.BUY)

        host._update_trailing_sl(state)

        host._modify_sl.assert_not_called()

    def test_short_tightens_when_trail_below_current_sl(self) -> None:
        # SHORT @ 2000 BE'd to 2000. Trail line at 1995 (below BE) →
        # tighten by moving SL down to 1995.
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=1995.0, trend=-1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.SELL)

        host._update_trailing_sl(state)

        host._modify_sl.assert_called_once_with(Decimal("1995.0"))
        assert state.current_sl == Decimal("1995.0")

    def test_short_does_not_loosen_when_trail_above_current_sl(self) -> None:
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=2005.0, trend=-1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.SELL)

        host._update_trailing_sl(state)

        host._modify_sl.assert_not_called()
        assert state.current_sl == Decimal("2000")

    def test_short_skips_when_trail_trend_flipped_to_long(self) -> None:
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=1950.0, trend=1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.SELL)

        host._update_trailing_sl(state)

        host._modify_sl.assert_not_called()

    def test_skipped_when_trail_indicator_missing(self) -> None:
        # Defensive: if trailing_enabled was set but the host failed to
        # construct _supertrend_trail (None), skip rather than crash.
        cfg = _make_config(trailing_enabled=True)
        host = _Host(cfg, supertrend_trail=None)
        self._bind_real_trail_body(host)

        host._update_trailing_sl(_post_be_state(OrderSide.BUY))

        host._modify_sl.assert_not_called()

    def test_consecutive_tightens_track_through_state(self) -> None:
        # First bar: trail at 2005 → SL → 2005.
        # Second bar: trail at 2010 → SL → 2010 (further tighten).
        # Third bar: trail back to 2008 → no-op (would loosen).
        cfg = _make_config(trailing_enabled=True)
        trail = _stub_trail(value=2005.0, trend=1)
        host = _Host(cfg, supertrend_trail=trail)
        self._bind_real_trail_body(host)
        state = _post_be_state(OrderSide.BUY)

        host._update_trailing_sl(state)
        assert state.current_sl == Decimal("2005.0")

        trail.value = 2010.0
        host._update_trailing_sl(state)
        assert state.current_sl == Decimal("2010.0")

        trail.value = 2008.0
        host._update_trailing_sl(state)
        assert state.current_sl == Decimal("2010.0")  # unchanged

        assert host._modify_sl.call_count == 2
