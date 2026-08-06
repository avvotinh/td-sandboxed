"""Unit tests for the consolidated MeanReversionStrategy (Track 2.1).

The strategy replaces the archived ``rsi_mean_reversion`` and
``bollinger_mean_reversion`` pair with ONE confluence signal: enter only
when the close pierces a Bollinger band AND the RSI sits in the matching
extreme zone. Exit at the middle band (the mean-reversion target).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.kernel.strategies.mean_reversion import (
    MeanReversionConfig,
    MeanReversionStrategy,
)


pytestmark = pytest.mark.unit


def _make_config(**overrides) -> MeanReversionConfig:
    defaults = dict(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        bb_period=20,
        num_std=2.0,
        rsi_period=14,
        oversold=0.3,
        overbought=0.7,
        atr_period=14,
    )
    defaults.update(overrides)
    return MeanReversionConfig(**defaults)


def _make_strategy(**overrides) -> MeanReversionStrategy:
    return MeanReversionStrategy(_make_config(**overrides))


def _mock_bar(close: float) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


def _arm(
    strategy: MeanReversionStrategy,
    *,
    rsi: float,
    upper: float = 2420.0,
    middle: float = 2400.0,
    lower: float = 2380.0,
    atr: float = 5.0,
) -> None:
    """Put both indicators in an initialised, deterministic state."""
    strategy._bb = Mock(initialized=True, upper=upper, middle=middle, lower=lower)
    strategy._rsi = Mock(initialized=True, value=rsi)
    strategy._atr = Mock(initialized=True, value=atr)


class TestConfigValidation:
    def test_bb_period_positive(self) -> None:
        with pytest.raises(ValueError, match="bb_period"):
            _make_config(bb_period=0)

    def test_rsi_period_positive(self) -> None:
        with pytest.raises(ValueError, match="rsi_period"):
            _make_config(rsi_period=-1)

    def test_num_std_positive(self) -> None:
        with pytest.raises(ValueError, match="num_std"):
            _make_config(num_std=-1.0)

    def test_num_std_upper_bound(self) -> None:
        # num_std=20 silently produces zero-trade backtests; reject so a
        # misconfigured YAML preset surfaces at construction.
        with pytest.raises(ValueError, match="num_std"):
            _make_config(num_std=20.0)

    def test_rsi_thresholds_ordered(self) -> None:
        with pytest.raises(ValueError, match="oversold"):
            _make_config(oversold=0.7, overbought=0.3)

    def test_rsi_thresholds_within_unit_interval(self) -> None:
        with pytest.raises(ValueError, match="oversold"):
            _make_config(oversold=-0.1)
        with pytest.raises(ValueError, match="oversold"):
            _make_config(overbought=1.1)

    def test_parent_validation_propagates(self) -> None:
        with pytest.raises(ValueError, match="sl_atr_mult"):
            _make_config(
                sl_atr_mult=Decimal("3.0"), tp_atr_mult=Decimal("1.0")
            )

    def test_mr_default_brackets(self) -> None:
        cfg = _make_config()
        assert cfg.sl_atr_mult == Decimal("1.0")
        assert cfg.tp_atr_mult == Decimal("2.0")


class TestConfluenceEntry:
    """Entry requires BOTH the band pierce and the RSI extreme."""

    def test_no_signal_before_init(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=False)
        strategy._rsi = Mock(initialized=False)
        strategy._atr = Mock(initialized=False)
        assert strategy.generate_signal(_mock_bar(2379)) == SignalType.NONE

    def test_lower_band_plus_oversold_rsi_buys(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25)
        assert strategy.generate_signal(_mock_bar(2379)) == SignalType.BUY

    def test_lower_band_without_rsi_extreme_stays_flat(self) -> None:
        # The whole point of the merge: a band touch alone (old Bollinger
        # MR entry) is no longer sufficient.
        strategy = _make_strategy()
        _arm(strategy, rsi=0.45)
        assert strategy.generate_signal(_mock_bar(2379)) == SignalType.NONE

    def test_oversold_rsi_without_band_touch_stays_flat(self) -> None:
        # Symmetric: an RSI extreme alone (old RSI MR entry) is no longer
        # sufficient either.
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_upper_band_plus_overbought_rsi_sells(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.75)
        assert strategy.generate_signal(_mock_bar(2421)) == SignalType.SELL

    def test_upper_band_without_rsi_extreme_stays_flat(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.55)
        assert strategy.generate_signal(_mock_bar(2421)) == SignalType.NONE

    def test_threshold_boundaries_are_inclusive(self) -> None:
        # RSI exactly AT the threshold counts as the extreme zone —
        # consistent with the old RSI MR "was <= oversold" semantics.
        strategy = _make_strategy()
        _arm(strategy, rsi=0.3)
        assert strategy.generate_signal(_mock_bar(2379)) == SignalType.BUY
        _arm(strategy, rsi=0.7)
        assert strategy.generate_signal(_mock_bar(2421)) == SignalType.SELL

    def test_no_new_entry_while_position_open(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25)
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        # Close 2379 < lower with oversold RSI — but we're already long
        # and NOT at the exit target, so nothing fires.
        assert strategy.generate_signal(_mock_bar(2379)) == SignalType.NONE


class TestMiddleBandExit:
    def test_long_exits_at_middle(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.5)
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.CLOSE

    def test_short_exits_at_middle(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.5)
        position = Mock()
        position.side = PositionSide.SHORT
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.CLOSE

    def test_exit_has_priority_over_entry(self) -> None:
        # Same-bar race: short at the middle band while the lower band +
        # oversold RSI would signal BUY — the CLOSE must win.
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25, lower=2401.0)
        position = Mock()
        position.side = PositionSide.SHORT
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.CLOSE


class TestSqueezeGuard:
    """Zero-width Bollinger band must not silently produce zero trades."""

    def test_zero_width_band_returns_none(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25, upper=2400.0, middle=2400.0, lower=2400.0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_collapsed_band_does_not_trigger_close(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.5, upper=2400.0, middle=2400.0, lower=2400.0)
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE


class TestAtrZeroGuard:
    """_execute_signal must skip on non-positive / non-finite ATR rather
    than crashing the bar loop via ATRStopMixin._validated_offset."""

    @pytest.mark.parametrize(
        "bad_atr", [0.0, None, -5.0, float("nan"), float("inf")]
    )
    def test_unsafe_atr_skips_bracket_submission(self, bad_atr) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25, atr=bad_atr)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_positive_atr_still_submits(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.25)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_called_once()

    def test_close_signal_bypasses_atr_guard(self) -> None:
        strategy = _make_strategy()
        _arm(strategy, rsi=0.5, atr=0.0)
        strategy._close_position = Mock()
        strategy._execute_signal(SignalType.CLOSE)
        strategy._close_position.assert_called_once()


class TestRosterRegistration:
    @pytest.fixture(autouse=True)
    def _ensure_registered(self):
        """Re-fire the ``@register_strategy`` decorators.

        Other suites call ``StrategyRegistry.clear()`` without
        repopulating; a cached module import will not re-run the
        decorator on a cleared registry (same fixture pattern as
        ``test_regime_actor_ablation_csv.py``).
        """
        import importlib

        import src.kernel.strategies.bollinger_mean_reversion as _bollinger
        import src.kernel.strategies.ma_crossover as _ma
        import src.kernel.strategies.mean_reversion as _mr
        import src.kernel.strategies.rsi_mean_reversion as _rsi

        from src.kernel.strategies.registry import StrategyRegistry

        for name, module in [
            ("mean_reversion", _mr),
            ("rsi_mean_reversion", _rsi),
            ("bollinger_mean_reversion", _bollinger),
            ("ma_crossover", _ma),
        ]:
            StrategyRegistry.unregister(name)
            importlib.reload(module)
        yield

    def test_registered_for_ranging(self) -> None:
        from src.kernel.regime.states import RegimeState
        from src.kernel.strategies.registry import StrategyRegistry

        assert StrategyRegistry.is_registered("mean_reversion")
        assert StrategyRegistry.get_regimes("mean_reversion") == frozenset(
            {RegimeState.RANGING}
        )

    def test_supersedes_archived_mr_pair(self) -> None:
        # Track 2.1/2.2 roster contract: the old MR pair stays registered
        # (for A/B re-runs) but never routes; ma_crossover is likewise
        # archived (edge shown to be an artifact of the missing SL).
        from src.kernel.strategies.registry import StrategyRegistry

        assert StrategyRegistry.get_regimes("rsi_mean_reversion") == frozenset()
        assert StrategyRegistry.get_regimes("bollinger_mean_reversion") == frozenset()
        assert StrategyRegistry.get_regimes("ma_crossover") == frozenset()
