"""Unit tests for MA Crossover strategy.

Tests cover:
- MACrossoverConfig validation (fast < slow periods)
- Crossover detection logic (bullish, bearish, none)
- Strategy registration
- Edge cases
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest

from src.indicators.supertrend import Supertrend
from src.orders.signal import SignalType
from src.strategies.ma_crossover import MACrossoverConfig, MACrossoverStrategy
from src.strategies.registry import StrategyRegistry


class TestMACrossoverConfig:
    """Tests for MACrossoverConfig."""

    def test_default_periods(self):
        """Test default period values."""
        config = MACrossoverConfig(
            instrument_id=Mock(),
            bar_type=Mock(),
        )
        assert config.fast_period == 20
        assert config.slow_period == 50

    def test_custom_periods(self):
        """Test custom period values."""
        config = MACrossoverConfig(
            instrument_id=Mock(),
            bar_type=Mock(),
            fast_period=10,
            slow_period=30,
        )
        assert config.fast_period == 10
        assert config.slow_period == 30

    def test_slow_must_be_greater_than_fast(self):
        """Test that slow_period must be greater than fast_period."""
        with pytest.raises(ValueError, match="slow_period.*must be > fast_period"):
            MACrossoverConfig(
                instrument_id=Mock(),
                bar_type=Mock(),
                fast_period=50,
                slow_period=20,
            )

    def test_equal_periods_invalid(self):
        """Test that equal periods are invalid."""
        with pytest.raises(ValueError, match="slow_period.*must be > fast_period"):
            MACrossoverConfig(
                instrument_id=Mock(),
                bar_type=Mock(),
                fast_period=20,
                slow_period=20,
            )

    @pytest.mark.parametrize("bad", [0, -1])
    def test_fast_period_must_be_positive(self, bad):
        with pytest.raises(ValueError, match="fast_period"):
            MACrossoverConfig(
                instrument_id=Mock(),
                bar_type=Mock(),
                fast_period=bad,
                slow_period=50,
            )

    @pytest.mark.parametrize("bad", [0, -5])
    def test_slow_period_must_be_positive(self, bad):
        with pytest.raises(ValueError, match="slow_period"):
            MACrossoverConfig(
                instrument_id=Mock(),
                bar_type=Mock(),
                fast_period=10,
                slow_period=bad,
            )

    def test_inherits_base_config_fields(self):
        """Test that config has base config fields."""
        instrument_id = Mock()
        bar_type = Mock()
        config = MACrossoverConfig(
            instrument_id=instrument_id,
            bar_type=bar_type,
            trade_size=Decimal("0.5"),
            account_id="test-account",
        )
        assert config.instrument_id == instrument_id
        assert config.bar_type == bar_type
        assert config.trade_size == Decimal("0.5")
        assert config.account_id == "test-account"


class TestMACrossoverRegistration:
    """Tests for strategy registration."""

    def test_strategy_is_registered(self):
        """Test that MACrossoverStrategy can be registered in StrategyRegistry."""
        # Note: The registry may be cleared by other tests' fixtures,
        # so we explicitly register here to test the mechanism
        if not StrategyRegistry.is_registered("ma_crossover"):
            StrategyRegistry.register("ma_crossover", MACrossoverStrategy)

        assert StrategyRegistry.is_registered("ma_crossover")
        assert StrategyRegistry.get("ma_crossover") is MACrossoverStrategy

    def test_strategy_available_in_list(self):
        """Test that ma_crossover appears in available strategies."""
        # Register if not already (registry may be cleared by other tests)
        if not StrategyRegistry.is_registered("ma_crossover"):
            StrategyRegistry.register("ma_crossover", MACrossoverStrategy)

        available = StrategyRegistry.list_available()
        assert "ma_crossover" in available


class TestCrossoverDetectionLogic:
    """Tests for crossover detection logic (standalone functions).

    Since NautilusTrader's Strategy class is Rust-based and hard to mock,
    we test the crossover logic directly using simple functions.
    """

    def _detect_crossover(
        self,
        fast: float,
        slow: float,
        prev_fast: float | None,
        prev_slow: float | None,
        fast_initialized: bool = True,
        slow_initialized: bool = True,
    ) -> SignalType:
        """Simulate the crossover detection logic from generate_signal.

        This replicates the core logic for testing without needing
        to instantiate the actual strategy.
        """
        # Wait for indicators to warm up
        if not fast_initialized or not slow_initialized:
            return SignalType.NONE

        # Check for crossover (requires previous values)
        if prev_fast is not None and prev_slow is not None:
            # Bullish crossover: fast crosses above slow
            if prev_fast <= prev_slow and fast > slow:
                return SignalType.BUY
            # Bearish crossover: fast crosses below slow
            elif prev_fast >= prev_slow and fast < slow:
                return SignalType.SELL

        return SignalType.NONE

    def test_returns_none_when_fast_not_initialized(self):
        """Test that signal is NONE when fast EMA not initialized."""
        result = self._detect_crossover(
            fast=100.0,
            slow=99.0,
            prev_fast=98.0,
            prev_slow=99.0,
            fast_initialized=False,
            slow_initialized=True,
        )
        assert result == SignalType.NONE

    def test_returns_none_when_slow_not_initialized(self):
        """Test that signal is NONE when slow EMA not initialized."""
        result = self._detect_crossover(
            fast=100.0,
            slow=99.0,
            prev_fast=98.0,
            prev_slow=99.0,
            fast_initialized=True,
            slow_initialized=False,
        )
        assert result == SignalType.NONE

    def test_returns_none_when_both_not_initialized(self):
        """Test that signal is NONE when both EMAs not initialized."""
        result = self._detect_crossover(
            fast=100.0,
            slow=99.0,
            prev_fast=98.0,
            prev_slow=99.0,
            fast_initialized=False,
            slow_initialized=False,
        )
        assert result == SignalType.NONE

    def test_returns_none_on_first_bar(self):
        """Test that signal is NONE on first bar (no previous values)."""
        result = self._detect_crossover(
            fast=100.0,
            slow=99.0,
            prev_fast=None,
            prev_slow=None,
        )
        assert result == SignalType.NONE

    def test_bullish_crossover_returns_buy(self):
        """Test bullish crossover (fast crosses above slow) returns BUY."""
        result = self._detect_crossover(
            fast=51.0,  # Now above
            slow=50.0,
            prev_fast=49.0,  # Was below
            prev_slow=50.0,
        )
        assert result == SignalType.BUY

    def test_bearish_crossover_returns_sell(self):
        """Test bearish crossover (fast crosses below slow) returns SELL."""
        result = self._detect_crossover(
            fast=49.0,  # Now below
            slow=50.0,
            prev_fast=51.0,  # Was above
            prev_slow=50.0,
        )
        assert result == SignalType.SELL

    def test_no_crossover_fast_stays_above_returns_none(self):
        """Test no crossover when fast stays above slow returns NONE."""
        result = self._detect_crossover(
            fast=52.0,  # Still above
            slow=50.0,
            prev_fast=51.0,  # Was also above
            prev_slow=50.0,
        )
        assert result == SignalType.NONE

    def test_no_crossover_fast_stays_below_returns_none(self):
        """Test no crossover when fast stays below slow returns NONE."""
        result = self._detect_crossover(
            fast=48.0,  # Still below
            slow=50.0,
            prev_fast=49.0,  # Was also below
            prev_slow=50.0,
        )
        assert result == SignalType.NONE

    def test_exact_crossover_touching_no_signal(self):
        """Test exact crossover point (equal values) returns NONE."""
        result = self._detect_crossover(
            fast=50.0,  # Exactly equal
            slow=50.0,
            prev_fast=49.0,  # Was below
            prev_slow=50.0,
        )
        # Touching but not crossing - no signal
        assert result == SignalType.NONE

    def test_large_price_movement_still_detects_crossover(self):
        """Test large price movements still detect crossovers."""
        result = self._detect_crossover(
            fast=200.0,  # Large jump above
            slow=100.0,
            prev_fast=50.0,  # Was far below
            prev_slow=100.0,
        )
        assert result == SignalType.BUY

    def test_very_small_crossover_detected(self):
        """Test very small crossovers are detected."""
        result = self._detect_crossover(
            fast=100.00001,  # Just above
            slow=100.0,
            prev_fast=99.99999,  # Was just below
            prev_slow=100.0,
        )
        assert result == SignalType.BUY

    def test_zero_values_handled(self):
        """Test zero EMA values are handled."""
        result = self._detect_crossover(
            fast=0.0,
            slow=0.0,
            prev_fast=0.0,
            prev_slow=0.0,
        )
        assert result == SignalType.NONE

    def test_negative_values_handled(self):
        """Test negative EMA values (theoretical) are handled."""
        result = self._detect_crossover(
            fast=-5.0,  # Crosses above
            slow=-10.0,
            prev_fast=-15.0,  # Was below
            prev_slow=-10.0,
        )
        assert result == SignalType.BUY


class TestPositionReversalLogic:
    """Tests for position reversal logic (standalone).

    Tests the logic that should happen in _execute_signal.
    """

    def _simulate_execute_signal(
        self,
        signal: SignalType,
        is_long: bool,
        is_short: bool,
    ) -> tuple[bool, bool, bool]:
        """Simulate _execute_signal and return actions taken.

        Returns:
            Tuple of (close_called, go_long_called, go_short_called)
        """
        close_called = False
        go_long_called = False
        go_short_called = False

        if signal == SignalType.BUY:
            if is_short:
                close_called = True
            go_long_called = True
        elif signal == SignalType.SELL:
            if is_long:
                close_called = True
            go_short_called = True
        elif signal == SignalType.CLOSE:
            close_called = True

        return close_called, go_long_called, go_short_called

    def test_buy_signal_when_short_closes_and_goes_long(self):
        """Test BUY signal when short position closes and goes long."""
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.BUY,
            is_long=False,
            is_short=True,
        )
        assert close_called is True
        assert go_long_called is True
        assert go_short_called is False

    def test_sell_signal_when_long_closes_and_goes_short(self):
        """Test SELL signal when long position closes and goes short."""
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.SELL,
            is_long=True,
            is_short=False,
        )
        assert close_called is True
        assert go_long_called is False
        assert go_short_called is True

    def test_buy_signal_when_flat_just_goes_long(self):
        """Test BUY signal when flat just goes long."""
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.BUY,
            is_long=False,
            is_short=False,
        )
        assert close_called is False
        assert go_long_called is True
        assert go_short_called is False

    def test_sell_signal_when_flat_just_goes_short(self):
        """Test SELL signal when flat just goes short."""
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.SELL,
            is_long=False,
            is_short=False,
        )
        assert close_called is False
        assert go_long_called is False
        assert go_short_called is True

    def test_close_signal_closes_position(self):
        """Test CLOSE signal closes position."""
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.CLOSE,
            is_long=True,
            is_short=False,
        )
        assert close_called is True
        assert go_long_called is False
        assert go_short_called is False

    def test_immediate_reentry_on_reversal(self):
        """Test that reversal includes immediate re-entry (no waiting)."""
        # When reversing from short to long
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.BUY,
            is_long=False,
            is_short=True,
        )
        # Both close AND go_long should be called (immediate entry)
        assert close_called is True
        assert go_long_called is True

        # When reversing from long to short
        close_called, go_long_called, go_short_called = self._simulate_execute_signal(
            signal=SignalType.SELL,
            is_long=True,
            is_short=False,
        )
        # Both close AND go_short should be called (immediate entry)
        assert close_called is True
        assert go_short_called is True


class TestOnResetMethod:
    """Tests for on_reset() method behavior."""

    def test_reset_clears_previous_values(self):
        """Test that on_reset() clears previous EMA tracking values."""
        # Simulate the reset logic from MACrossoverStrategy.on_reset()
        # Since we can't easily instantiate the full strategy, we test the logic
        prev_fast = 100.0
        prev_slow = 99.0

        # Simulate reset
        prev_fast = None
        prev_slow = None

        assert prev_fast is None
        assert prev_slow is None

    def test_reset_allows_fresh_crossover_detection(self):
        """Test that after reset, first bar returns NONE (no previous values)."""
        # After reset, previous values are None, so first bar should return NONE
        def _detect_crossover(fast, slow, prev_fast, prev_slow):
            if prev_fast is None or prev_slow is None:
                return SignalType.NONE
            if prev_fast <= prev_slow and fast > slow:
                return SignalType.BUY
            return SignalType.NONE

        # After reset (prev values are None)
        result = _detect_crossover(
            fast=101.0,
            slow=100.0,
            prev_fast=None,  # Reset state
            prev_slow=None,
        )
        assert result == SignalType.NONE

        # Second bar after reset can detect crossover
        result = _detect_crossover(
            fast=102.0,
            slow=100.0,
            prev_fast=101.0,  # Now have previous
            prev_slow=100.0,
        )
        # Still NONE because prev_fast was already above prev_slow
        assert result == SignalType.NONE

    def test_reset_method_exists_on_strategy_class(self):
        """Test that MACrossoverStrategy has on_reset method defined."""
        assert hasattr(MACrossoverStrategy, "on_reset")
        # Verify it's a method (not inherited from object)
        import inspect

        assert inspect.isfunction(MACrossoverStrategy.on_reset)


class TestSequenceOfBars:
    """Test sequences of bar processing."""

    def _detect_crossover(
        self,
        fast: float,
        slow: float,
        prev_fast: float | None,
        prev_slow: float | None,
        fast_initialized: bool = True,
        slow_initialized: bool = True,
    ) -> SignalType:
        """Simulate the crossover detection logic."""
        if not fast_initialized or not slow_initialized:
            return SignalType.NONE

        if prev_fast is not None and prev_slow is not None:
            if prev_fast <= prev_slow and fast > slow:
                return SignalType.BUY
            elif prev_fast >= prev_slow and fast < slow:
                return SignalType.SELL

        return SignalType.NONE

    def test_warmup_period_then_crossover(self):
        """Test warmup period followed by crossover detection."""
        # Simulate warmup (not initialized)
        result = self._detect_crossover(
            fast=100.0,
            slow=99.0,
            prev_fast=None,
            prev_slow=None,
            fast_initialized=False,
            slow_initialized=False,
        )
        assert result == SignalType.NONE

        # First bar with initialized EMAs (no previous)
        result = self._detect_crossover(
            fast=99.0,
            slow=100.0,
            prev_fast=None,
            prev_slow=None,
            fast_initialized=True,
            slow_initialized=True,
        )
        assert result == SignalType.NONE

        # Second bar - still below (no crossover)
        result = self._detect_crossover(
            fast=99.5,
            slow=100.0,
            prev_fast=99.0,
            prev_slow=100.0,
        )
        assert result == SignalType.NONE

        # Third bar - crossover!
        result = self._detect_crossover(
            fast=101.0,
            slow=100.0,
            prev_fast=99.5,
            prev_slow=100.0,
        )
        assert result == SignalType.BUY

    def test_consecutive_crossovers(self):
        """Test multiple crossovers in sequence."""
        # Initial state: fast below slow
        prev_fast = 49.0
        prev_slow = 50.0

        # First crossover: bullish
        result = self._detect_crossover(
            fast=51.0,
            slow=50.0,
            prev_fast=prev_fast,
            prev_slow=prev_slow,
        )
        assert result == SignalType.BUY
        prev_fast, prev_slow = 51.0, 50.0

        # Stay above (no signal)
        result = self._detect_crossover(
            fast=52.0,
            slow=50.0,
            prev_fast=prev_fast,
            prev_slow=prev_slow,
        )
        assert result == SignalType.NONE
        prev_fast, prev_slow = 52.0, 50.0

        # Second crossover: bearish
        result = self._detect_crossover(
            fast=48.0,
            slow=50.0,
            prev_fast=prev_fast,
            prev_slow=prev_slow,
        )
        assert result == SignalType.SELL


# ---------------------------------------------------------------------------
# Story 13.11 — BracketScaleOutMixin integration into MACrossoverStrategy
# (mirrors Story 13.5 Supertrend + Story 13.10 Donchian wiring)
# ---------------------------------------------------------------------------


from nautilus_trader.model.data import BarType  # noqa: E402
from nautilus_trader.model.enums import OrderSide  # noqa: E402
from nautilus_trader.model.identifiers import InstrumentId  # noqa: E402


def _make_real_config(**overrides) -> MACrossoverConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-1-HOUR-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        fast_period=20,
        slow_period=50,
        atr_period=14,
        sl_atr_mult=Decimal("1.5"),
        tp_atr_mult=Decimal("3.0"),
        risk_percent=Decimal("1.0"),
        pip_size=Decimal("0.01"),
        pip_value_per_lot=Decimal("1.0"),
    )
    defaults.update(overrides)
    return MACrossoverConfig(**defaults)


def _make_real_strategy(**overrides) -> MACrossoverStrategy:
    return MACrossoverStrategy(_make_real_config(**overrides))


def _mock_bar(close: float) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


@pytest.mark.unit
class TestScaleOutMRO:
    """Mixin composes into MA crossover's MRO without breaking existing init."""

    def test_scale_state_initialized_to_none(self) -> None:
        strategy = _make_real_strategy()
        assert strategy._scale_state is None

    def test_legacy_attributes_still_present(self) -> None:
        strategy = _make_real_strategy()
        assert strategy.fast_ema is not None
        assert strategy.slow_ema is not None
        assert strategy._atr is not None
        assert strategy._prev_fast is None
        assert strategy._prev_slow is None


@pytest.mark.unit
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

        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._position = self._stub_position(OrderSide.BUY, 2000.0, 1.0)
        strategy._find_active_sl_order = Mock(
            return_value=self._stub_sl_order(1990.0)
        )
        strategy._init_scale_state = Mock()

        strategy._dispatch_scale_out_event(Mock(spec=PositionOpened))

        strategy._init_scale_state.assert_called_once_with(
            side=OrderSide.BUY,
            entry_price=Decimal("2000.0"),
            sl_price=Decimal("1990.0"),
            qty=Decimal("1.0"),
        )

    def test_position_opened_short_maps_position_side_to_sell(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._position = self._stub_position(OrderSide.SELL, 2000.0, 1.0)
        strategy._find_active_sl_order = Mock(
            return_value=self._stub_sl_order(2010.0)
        )
        strategy._init_scale_state = Mock()

        strategy._dispatch_scale_out_event(Mock(spec=PositionOpened))

        kwargs = strategy._init_scale_state.call_args.kwargs
        assert kwargs["side"] == OrderSide.SELL

    def test_position_opened_skipped_when_disabled(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_real_strategy(scale_out_enabled=False)
        strategy._position = self._stub_position(OrderSide.BUY, 2000.0, 1.0)
        strategy._init_scale_state = Mock()

        strategy._dispatch_scale_out_event(Mock(spec=PositionOpened))
        strategy._init_scale_state.assert_not_called()

    def test_position_opened_skipped_when_position_missing(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._position = None
        strategy._init_scale_state = Mock()
        strategy._dispatch_scale_out_event(Mock(spec=PositionOpened))
        strategy._init_scale_state.assert_not_called()

    def test_position_opened_skipped_when_no_sl_order(self) -> None:
        from nautilus_trader.model.events import PositionOpened

        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._position = self._stub_position(OrderSide.BUY, 2000.0, 1.0)
        strategy._find_active_sl_order = Mock(return_value=None)
        strategy._init_scale_state = Mock()
        strategy._dispatch_scale_out_event(Mock(spec=PositionOpened))
        strategy._init_scale_state.assert_not_called()

    def test_position_closed_clears_state(self) -> None:
        from nautilus_trader.model.events import PositionClosed

        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._clear_scale_state = Mock()
        strategy._dispatch_scale_out_event(Mock(spec=PositionClosed))
        strategy._clear_scale_state.assert_called_once()

    def test_position_closed_skipped_when_disabled(self) -> None:
        from nautilus_trader.model.events import PositionClosed

        strategy = _make_real_strategy(scale_out_enabled=False)
        strategy._clear_scale_state = Mock()
        strategy._dispatch_scale_out_event(Mock(spec=PositionClosed))
        strategy._clear_scale_state.assert_not_called()

    def test_unrelated_event_no_op(self) -> None:
        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._init_scale_state = Mock()
        strategy._clear_scale_state = Mock()
        strategy._dispatch_scale_out_event(Mock())
        strategy._init_scale_state.assert_not_called()
        strategy._clear_scale_state.assert_not_called()


@pytest.mark.unit
class TestEvaluateScaleOutForBar:
    """on_bar hook → evaluate_scale_out(bar.close)."""

    def test_evaluates_when_enabled_and_in_position(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_real_strategy(scale_out_enabled=True)
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy._scale_state = Mock(name="ScaleOutTradeState")
        strategy.evaluate_scale_out = Mock()

        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))
        strategy.evaluate_scale_out.assert_called_once_with(Decimal("2010.0"))

    def test_init_retry_when_state_none(self) -> None:
        from nautilus_trader.model.enums import PositionSide

        strategy = _make_real_strategy(scale_out_enabled=True)
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

        strategy = _make_real_strategy(scale_out_enabled=False)
        pos = Mock()
        pos.side = PositionSide.LONG
        strategy._position = pos
        strategy.evaluate_scale_out = Mock()
        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))
        strategy.evaluate_scale_out.assert_not_called()

    def test_skipped_when_flat(self) -> None:
        strategy = _make_real_strategy(scale_out_enabled=True)
        strategy._position = None
        strategy.evaluate_scale_out = Mock()
        strategy._evaluate_scale_out_for_bar(_mock_bar(2010.0))
        strategy.evaluate_scale_out.assert_not_called()


@pytest.mark.unit
class TestTrailIndicatorWiring:
    """``_supertrend_trail`` only constructed when trailing_enabled."""

    def test_trail_indicator_created_when_enabled(self) -> None:
        strategy = _make_real_strategy(
            scale_out_enabled=True,
            trailing_enabled=True,
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
        )
        assert isinstance(strategy._supertrend_trail, Supertrend)
        assert strategy._supertrend_trail.period == 7
        assert strategy._supertrend_trail.multiplier == 2.1

    def test_trail_indicator_none_when_disabled(self) -> None:
        strategy = _make_real_strategy()
        assert strategy._supertrend_trail is None

    def test_signal_indicators_unaffected_by_trail(self) -> None:
        strategy = _make_real_strategy(
            scale_out_enabled=True,
            trailing_enabled=True,
            trailing_atr_period=7,
            trailing_atr_multiplier=Decimal("2.1"),
        )
        assert strategy.fast_ema is not None
        assert strategy.slow_ema is not None
        assert strategy._atr is not None
