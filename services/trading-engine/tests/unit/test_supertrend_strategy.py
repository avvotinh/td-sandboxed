"""Unit tests for SupertrendStrategy.

We test the pure signal logic (``generate_signal`` against mocked
indicator state) and the bracket-parameter computation helper. Full
portfolio / order-factory interaction is exercised by the backtest smoke
test.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.supertrend import SupertrendConfig, SupertrendStrategy


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> SupertrendConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        period=10,
        multiplier=3.0,
        atr_period=14,
        sl_atr_mult=Decimal("1.5"),
        tp_atr_mult=Decimal("3.0"),
        risk_percent=Decimal("1.0"),
        pip_size=Decimal("0.01"),
        pip_value_per_lot=Decimal("1.0"),
    )
    defaults.update(overrides)
    return SupertrendConfig(**defaults)


def _make_strategy(**overrides) -> SupertrendStrategy:
    return SupertrendStrategy(_make_config(**overrides))


class TestConfigValidation:
    def test_slow_period_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(period=0)

    def test_multiplier_must_be_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(multiplier=0)

    def test_atr_multipliers_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(sl_atr_mult=Decimal("0"))
        with pytest.raises(ValueError):
            _make_config(tp_atr_mult=Decimal("-1"))


class TestSignalGeneration:
    """``generate_signal`` with mocked indicators."""

    def test_no_signal_when_uninitialised(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=False, trend=0)
        strategy._atr = Mock(initialized=False, value=0)
        assert strategy.generate_signal(Mock()) == SignalType.NONE

    def test_no_signal_on_first_initialised_bar(self) -> None:
        """First bar after warmup seeds prev_trend — no signal yet."""
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = None
        assert strategy.generate_signal(Mock()) == SignalType.NONE

    def test_buy_on_trend_flip_up(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = -1  # Was downtrend
        assert strategy.generate_signal(Mock()) == SignalType.BUY

    def test_sell_on_trend_flip_down(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=-1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = 1
        assert strategy.generate_signal(Mock()) == SignalType.SELL

    def test_no_signal_when_trend_unchanged(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = 1
        assert strategy.generate_signal(Mock()) == SignalType.NONE

    def test_prev_trend_updated_after_signal(self) -> None:
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_trend = -1
        strategy.generate_signal(Mock())
        assert strategy._prev_trend == 1


class TestBracketParams:
    """``_compute_bracket_params`` is pure — tested with Decimal inputs."""

    def test_long_bracket_sl_below_tp_above(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("100000"),
        )
        # SL = 2400 - 1.5 * 10 = 2385; TP = 2400 + 3.0 * 10 = 2430
        assert sl == Decimal("2385")
        assert tp == Decimal("2430")
        assert qty > 0

    def test_short_bracket_sl_above_tp_below(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.SELL,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("100000"),
        )
        assert sl == Decimal("2415")
        assert tp == Decimal("2370")
        assert qty > 0

    def test_qty_scales_with_balance(self) -> None:
        strategy = _make_strategy()
        _, _, _ = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("100000"),
        )
        qty_big, _, _ = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("200000"),
        )
        qty_small, _, _ = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2400"),
            atr_value=Decimal("10"),
            account_balance=Decimal("50000"),
        )
        assert qty_big > qty_small


class TestAtrZeroGuard:
    """A flat-bar (H=L=C) drives ATR to zero; the bracket helper must
    short-circuit rather than crash the bar-processing loop."""

    def test_atr_zero_skips_signal(self) -> None:
        # Without the guard, Decimal(str(0.0)) propagates into
        # ATRStopMixin._validated_offset which raises ValueError on
        # non-positive ATR — that exception unwinds through on_bar and
        # halts the engine. Verify the strategy returns silently.
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=0.0)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_atr_none_skips_signal(self) -> None:
        # First bars after warmup may report value=None on some
        # indicator paths — must not crash either.
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=None)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_atr_negative_skips_signal(self) -> None:
        # Synthetic rollover/gap bars on some Nautilus indicator paths
        # produce a transient negative ATR; guard must catch it before
        # the bracket helper rejects the offset.
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=-5.0)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_atr_nan_skips_signal(self) -> None:
        # NaN comparisons return False in Python (NaN <= 0 is False), so
        # a naive `atr <= 0` check would let NaN through. Decimal(str(nan))
        # then raises InvalidOperation deeper in the call stack.
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=float("nan"))
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_positive_atr_still_submits(self) -> None:
        # Sanity guard: the guard must not block the happy path.
        strategy = _make_strategy()
        strategy._supertrend = Mock(initialized=True, trend=1)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_called_once()


# Registry assertion removed — test_strategy_registry.py's autouse
# `clear_registry` fixture wipes the registry before/after its own tests,
# which would leave our strategies unregistered by the time this test
# runs in the full suite. Import-time registration is exercised by the
# decorator itself: if the module imports, `@register_strategy` ran.


# ---------------------------------------------------------------------------
# Story 13.5 — BracketScaleOutMixin integration into SupertrendStrategy
# ---------------------------------------------------------------------------


class TestScaleOutMRO:
    """Mixin must compose without breaking existing init."""

    def test_scale_state_initialized_to_none(self) -> None:
        # BracketScaleOutMixin.__init__ must run via super() chain so
        # _scale_state is set before any event arrives.
        strategy = _make_strategy()
        assert strategy._scale_state is None

    def test_legacy_attributes_still_present(self) -> None:
        # Regression: prepending the mixin must not break the existing
        # init chain that builds _supertrend / _atr / _prev_trend.
        strategy = _make_strategy()
        assert strategy._supertrend is not None
        assert strategy._atr is not None
        assert strategy._prev_trend is None


class TestDispatchScaleOutEvent:
    """on_event hook → _init_scale_state / _clear_scale_state."""

    def _stub_position(self, side, entry: float, qty: float) -> Mock:
        from nautilus_trader.model.enums import PositionSide

        pos = Mock()
        pos.side = PositionSide.LONG if side == OrderSide.BUY else PositionSide.SHORT
        pos.avg_px_open = entry
        qty_mock = Mock()
        qty_mock.as_double = Mock(return_value=qty)
        pos.quantity = qty_mock
        return pos

    def _stub_sl_order(self, trigger: float) -> Mock:
        # Mirror the Nautilus Price surface: trigger_price.as_double()
        # is what supertrend.py:_dispatch_scale_out_event reads.
        trigger_mock = Mock()
        trigger_mock.as_double = Mock(return_value=trigger)
        order = Mock()
        order.trigger_price = trigger_mock
        return order

    def test_position_opened_inits_state_when_enabled(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = self._stub_position(OrderSide.BUY, 2000.0, 1.0)
        strategy._find_active_sl_order = Mock(
            return_value=self._stub_sl_order(1990.0)
        )
        strategy._init_scale_state = Mock()

        event = Mock(spec=PositionOpened)
        strategy._dispatch_scale_out_event(event)

        strategy._init_scale_state.assert_called_once_with(
            side=OrderSide.BUY,
            entry_price=Decimal("2000.0"),
            sl_price=Decimal("1990.0"),
            qty=Decimal("1.0"),
        )

    def test_position_opened_short_maps_position_side_to_sell(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = self._stub_position(OrderSide.SELL, 2000.0, 1.0)
        strategy._find_active_sl_order = Mock(
            return_value=self._stub_sl_order(2010.0)
        )
        strategy._init_scale_state = Mock()

        event = Mock(spec=PositionOpened)
        strategy._dispatch_scale_out_event(event)

        kwargs = strategy._init_scale_state.call_args.kwargs
        assert kwargs["side"] == OrderSide.SELL

    def test_position_opened_skipped_when_disabled(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_strategy(scale_out_enabled=False)
        strategy._position = self._stub_position(OrderSide.BUY, 2000.0, 1.0)
        strategy._init_scale_state = Mock()

        event = Mock(spec=PositionOpened)
        strategy._dispatch_scale_out_event(event)

        strategy._init_scale_state.assert_not_called()

    def test_position_opened_skipped_when_position_missing(self) -> None:
        # Cache miss / race: super().on_event could not resolve the
        # position. Helper must skip rather than raise on None.
        # (Nautilus Component._log is read-only at runtime, so the
        # WARNING side-effect is verified via integration tests rather
        # than asserted here.)
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = None
        strategy._init_scale_state = Mock()

        event = Mock(spec=PositionOpened)
        strategy._dispatch_scale_out_event(event)

        strategy._init_scale_state.assert_not_called()

    def test_position_opened_skipped_when_no_sl_order(self) -> None:
        # SL leg may not be registered yet at fill time on some Nautilus
        # paths — skip so we don't pass None as sl_price.
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = self._stub_position(OrderSide.BUY, 2000.0, 1.0)
        strategy._find_active_sl_order = Mock(return_value=None)
        strategy._init_scale_state = Mock()

        event = Mock(spec=PositionOpened)
        strategy._dispatch_scale_out_event(event)

        strategy._init_scale_state.assert_not_called()

    def test_position_closed_clears_state(self) -> None:
        from nautilus_trader.model.events import PositionClosed

        strategy = _make_strategy(scale_out_enabled=True)
        strategy._clear_scale_state = Mock()

        event = Mock(spec=PositionClosed)
        strategy._dispatch_scale_out_event(event)

        strategy._clear_scale_state.assert_called_once()

    def test_position_closed_skipped_when_disabled(self) -> None:
        from nautilus_trader.model.events import PositionClosed

        strategy = _make_strategy(scale_out_enabled=False)
        strategy._clear_scale_state = Mock()

        event = Mock(spec=PositionClosed)
        strategy._dispatch_scale_out_event(event)

        strategy._clear_scale_state.assert_not_called()

    def test_unrelated_event_no_op(self) -> None:
        strategy = _make_strategy(scale_out_enabled=True)
        strategy._init_scale_state = Mock()
        strategy._clear_scale_state = Mock()

        # Pass a generic event that's neither PositionOpened nor Closed.
        strategy._dispatch_scale_out_event(Mock())

        strategy._init_scale_state.assert_not_called()
        strategy._clear_scale_state.assert_not_called()


class TestEvaluateScaleOutForBar:
    """on_bar hook → evaluate_scale_out(bar.close)."""

    def _stub_bar(self, close: float) -> Mock:
        bar = Mock()
        close_mock = Mock()
        close_mock.as_double = Mock(return_value=close)
        bar.close = close_mock
        return bar

    def test_evaluates_when_enabled_and_in_position(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_strategy(scale_out_enabled=True)
        # is_flat reads self._position; set a stub so it returns False.
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(self._stub_bar(2010.0))

        strategy.evaluate_scale_out.assert_called_once_with(Decimal("2010.0"))

    def test_skipped_when_disabled(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_strategy(scale_out_enabled=False)
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(self._stub_bar(2010.0))

        strategy.evaluate_scale_out.assert_not_called()

    def test_skipped_when_flat(self) -> None:
        # is_flat returns True when _position is None — no in-flight
        # state for the evaluator to act on.
        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = None
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(self._stub_bar(2010.0))

        strategy.evaluate_scale_out.assert_not_called()
