"""Unit tests for DonchianBreakoutStrategy.

Signal logic tested with mocked Donchian + ATR indicators. The critical
invariant: breakouts compare close to the **prior** bar's band, not the
current bar's — otherwise the current bar always sits inside its own
channel and no signal ever fires.
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import OrderSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.donchian_breakout import (
    DonchianBreakoutConfig,
    DonchianBreakoutStrategy,
)


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> DonchianBreakoutConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-HOUR-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        channel_period=20,
        atr_period=14,
        sl_atr_mult=Decimal("2.0"),
        tp_atr_mult=Decimal("4.0"),
        risk_percent=Decimal("1.0"),
        pip_size=Decimal("0.01"),
        pip_value_per_lot=Decimal("1.0"),
    )
    defaults.update(overrides)
    return DonchianBreakoutConfig(**defaults)


def _make_strategy(**overrides) -> DonchianBreakoutStrategy:
    return DonchianBreakoutStrategy(_make_config(**overrides))


def _mock_bar(close: float) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


class TestConfigValidation:
    def test_channel_period_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(channel_period=0)

    def test_atr_period_positive(self) -> None:
        with pytest.raises(ValueError):
            _make_config(atr_period=-1)


class TestSignalGeneration:
    def test_no_signal_until_initialised(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=False, upper=0, lower=0)
        strategy._atr = Mock(initialized=False, value=0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_no_signal_on_first_bar_seeds_prior(self) -> None:
        """First initialised bar just caches prior band — no signal yet."""
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = None
        strategy._prev_lower = None
        assert strategy.generate_signal(_mock_bar(2405)) == SignalType.NONE

    def test_breakout_up_triggers_buy(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2418.0
        strategy._prev_lower = 2380.0
        # Close 2420 > prior upper 2418 → breakout long
        assert strategy.generate_signal(_mock_bar(2420)) == SignalType.BUY

    def test_breakout_down_triggers_sell(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2378.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        # Close 2378 < prior lower 2380 → breakout short
        assert strategy.generate_signal(_mock_bar(2378)) == SignalType.SELL

    def test_inside_channel_no_signal(self) -> None:
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_equal_to_prior_upper_does_not_trigger(self) -> None:
        """Strict > comparison — close == prior upper is inside, not out."""
        strategy = _make_strategy()
        strategy._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        assert strategy.generate_signal(_mock_bar(2420)) == SignalType.NONE

    def test_uses_prior_band_not_current(self) -> None:
        """Regression: if we use current upper, close can never exceed it."""
        strategy = _make_strategy()
        # Simulate: the current bar's close pushed the Donchian upper out.
        # Current upper = 2430 (includes the current bar). Prior = 2420.
        # Close = 2425. Should still signal BUY (above prior 2420).
        strategy._donchian = Mock(initialized=True, upper=2430.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._prev_upper = 2420.0
        strategy._prev_lower = 2380.0
        assert strategy.generate_signal(_mock_bar(2425)) == SignalType.BUY


class TestBracketParams:
    def test_long_bracket(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.BUY,
            entry_price=Decimal("2420"),
            atr_value=Decimal("5"),
            account_balance=Decimal("100000"),
        )
        # sl = 2420 - 2.0 * 5 = 2410; tp = 2420 + 4.0 * 5 = 2440
        assert sl == Decimal("2410")
        assert tp == Decimal("2440")
        assert qty > 0

    def test_short_bracket(self) -> None:
        strategy = _make_strategy()
        qty, sl, tp = strategy._compute_bracket_params(
            side=OrderSide.SELL,
            entry_price=Decimal("2378"),
            atr_value=Decimal("5"),
            account_balance=Decimal("100000"),
        )
        assert sl == Decimal("2388")
        assert tp == Decimal("2358")
        assert qty > 0


class TestAtrZeroGuard:
    """A flat-bar (H=L=C) collapses ATR to zero; the bracket helper must
    short-circuit rather than crash the bar-processing loop. Mirrors the
    Supertrend / Bollinger / RSI guard added under story 12.8.
    """

    @pytest.mark.parametrize("bad_atr", [0.0, None, -5.0, float("nan")])
    def test_unsafe_atr_skips_bracket_submission(self, bad_atr) -> None:
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=bad_atr)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_positive_atr_still_submits(self) -> None:
        """Sanity: the guard does not over-trigger on healthy ATR."""
        strategy = _make_strategy()
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_called_once()


# Registry verified by successful import (decorator registered at load).


# ---------------------------------------------------------------------------
# Story 13.10 — BracketScaleOutMixin integration into DonchianBreakoutStrategy
# ---------------------------------------------------------------------------


class TestScaleOutMRO:
    """Mixin composes into Donchian's MRO without breaking existing init."""

    def test_scale_state_initialized_to_none(self) -> None:
        # BracketScaleOutMixin.__init__ must run via super() chain so
        # _scale_state is set before any event arrives.
        strategy = _make_strategy()
        assert strategy._scale_state is None

    def test_legacy_attributes_still_present(self) -> None:
        # Regression: prepending the mixin must not break the existing
        # init chain that builds _donchian / _atr / _prev_upper / _prev_lower.
        strategy = _make_strategy()
        assert strategy._donchian is not None
        assert strategy._atr is not None
        assert strategy._prev_upper is None
        assert strategy._prev_lower is None


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
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = None
        strategy._init_scale_state = Mock()

        event = Mock(spec=PositionOpened)
        strategy._dispatch_scale_out_event(event)

        strategy._init_scale_state.assert_not_called()

    def test_position_opened_skipped_when_no_sl_order(self) -> None:
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

        strategy._dispatch_scale_out_event(Mock())

        strategy._init_scale_state.assert_not_called()
        strategy._clear_scale_state.assert_not_called()


class TestEvaluateScaleOutForBar:
    """on_bar hook → evaluate_scale_out(bar.close)."""

    def test_evaluates_when_enabled_and_in_position(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_strategy(scale_out_enabled=True)
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy._scale_state = Mock(name="ScaleOutTradeState")
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))

        strategy.evaluate_scale_out.assert_called_once_with(Decimal("2010.0"))

    def test_init_retry_when_state_none(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_strategy(scale_out_enabled=True)
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy._scale_state = None
        strategy._try_init_scale_state = Mock()
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))

        strategy._try_init_scale_state.assert_called_once()
        strategy.evaluate_scale_out.assert_not_called()

    def test_skipped_when_disabled(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_strategy(scale_out_enabled=False)
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))

        strategy.evaluate_scale_out.assert_not_called()

    def test_skipped_when_flat(self) -> None:
        strategy = _make_strategy(scale_out_enabled=True)
        strategy._position = None
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))

        strategy.evaluate_scale_out.assert_not_called()


class TestTrailIndicatorWiring:
    """``_supertrend_trail`` only constructed when trailing_enabled."""

    def test_trail_indicator_created_when_enabled(self) -> None:
        strategy = _make_strategy(
            scale_out_enabled=True,
            trailing_enabled=True,
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
        )

        from src.indicators.supertrend import Supertrend

        assert isinstance(strategy._supertrend_trail, Supertrend)
        assert strategy._supertrend_trail.period == 7
        assert strategy._supertrend_trail.multiplier == 2.1

    def test_trail_indicator_none_when_disabled(self) -> None:
        # Default: trailing_enabled=False — skip the indicator overhead.
        strategy = _make_strategy()

        assert strategy._supertrend_trail is None

    def test_signal_indicators_unaffected_by_trail(self) -> None:
        # Regression: prepending the trail indicator must not affect
        # the signal-line Donchian or ATR.
        strategy = _make_strategy(
            scale_out_enabled=True,
            trailing_enabled=True,
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
        )
        assert strategy._donchian is not None
        assert strategy._atr is not None
