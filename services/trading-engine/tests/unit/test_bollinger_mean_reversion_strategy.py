"""Unit tests for BollingerMeanReversionStrategy."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import BarType
from nautilus_trader.model.enums import PositionSide
from nautilus_trader.model.identifiers import InstrumentId

from src.orders.signal import SignalType
from src.strategies.bollinger_mean_reversion import (
    BollingerMeanReversionConfig,
    BollingerMeanReversionStrategy,
)


pytestmark = pytest.mark.unit


def _make_config() -> BollingerMeanReversionConfig:
    return BollingerMeanReversionConfig(
        instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
        bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
        trade_size=Decimal("0.1"),
        period=20,
        num_std=2.0,
        atr_period=14,
    )


def _make_strategy() -> BollingerMeanReversionStrategy:
    return BollingerMeanReversionStrategy(_make_config())


def _mock_bar(close: float) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    return bar


class TestConfigValidation:
    def test_period_positive(self) -> None:
        with pytest.raises(ValueError):
            BollingerMeanReversionConfig(
                instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
                bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
                period=0, num_std=2.0,
            )

    def test_num_std_positive(self) -> None:
        with pytest.raises(ValueError):
            BollingerMeanReversionConfig(
                instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
                bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
                period=20, num_std=-1.0,
            )

    def test_num_std_upper_bound(self) -> None:
        # num_std=20 silently produces zero-trade backtests; reject so a
        # misconfigured YAML preset surfaces at import, not at run time.
        with pytest.raises(ValueError, match="num_std"):
            BollingerMeanReversionConfig(
                instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
                bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
                period=20, num_std=20.0,
            )

    def test_parent_validation_propagates(self) -> None:
        # super().__post_init__() must run first so BracketStrategyConfig
        # invariants (sl < tp, positive risk_percent, etc.) catch
        # misconfigurations before the child's own checks.
        with pytest.raises(ValueError, match="sl_atr_mult"):
            BollingerMeanReversionConfig(
                instrument_id=InstrumentId.from_str("XAUUSD.BROKER"),
                bar_type=BarType.from_str("XAUUSD.BROKER-15-MINUTE-LAST-EXTERNAL"),
                sl_atr_mult=Decimal("3.0"),
                tp_atr_mult=Decimal("1.0"),
            )


class TestSignalGeneration:
    def test_no_signal_before_init(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=False, upper=0, middle=0, lower=0)
        strategy._atr = Mock(initialized=False, value=0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_lower_band_touch_triggers_buy(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        assert strategy.generate_signal(_mock_bar(2379)) == SignalType.BUY

    def test_upper_band_touch_triggers_sell(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        assert strategy.generate_signal(_mock_bar(2421)) == SignalType.SELL

    def test_inside_bands_no_signal(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_long_exits_at_middle(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.CLOSE

    def test_short_exits_at_middle(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        strategy._atr = Mock(initialized=True, value=5.0)
        position = Mock()
        position.side = PositionSide.SHORT
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.CLOSE


class TestSqueezeGuard:
    """Zero-width Bollinger band must not silently produce zero trades."""

    def test_zero_width_band_returns_none(self) -> None:
        # Pure flatline → upper == lower == middle. The lower-band entry
        # condition can never fire; without the guard the strategy would
        # idle, looking like "no signal" rather than "broken state".
        strategy = _make_strategy()
        strategy._bb = Mock(
            initialized=True, upper=2400.0, middle=2400.0, lower=2400.0
        )
        strategy._atr = Mock(initialized=True, value=5.0)
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE

    def test_collapsed_band_does_not_trigger_close(self) -> None:
        # Even with an open long, a collapsed band should NOT trigger
        # the middle-cross close — the close target itself is undefined.
        strategy = _make_strategy()
        strategy._bb = Mock(
            initialized=True, upper=2400.0, middle=2400.0, lower=2400.0
        )
        strategy._atr = Mock(initialized=True, value=5.0)
        position = Mock()
        position.side = PositionSide.LONG
        strategy._position = position
        assert strategy.generate_signal(_mock_bar(2400)) == SignalType.NONE


class TestBollingerAtrZeroGuard:
    """Mirror of Supertrend's ATR safety guard: _execute_signal must
    skip on non-positive / non-finite ATR rather than crashing the
    bar-processing loop via ATRStopMixin._validated_offset."""

    @pytest.mark.parametrize(
        "bad_atr", [0.0, None, -5.0, float("nan"), float("inf")]
    )
    def test_unsafe_atr_skips_bracket_submission(self, bad_atr) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(
            initialized=True, upper=2420.0, middle=2400.0, lower=2380.0
        )
        strategy._atr = Mock(initialized=True, value=bad_atr)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_not_called()

    def test_positive_atr_still_submits(self) -> None:
        strategy = _make_strategy()
        strategy._bb = Mock(
            initialized=True, upper=2420.0, middle=2400.0, lower=2380.0
        )
        strategy._atr = Mock(initialized=True, value=5.0)
        strategy._submit_bracket_for_entry = Mock()
        strategy._execute_signal(SignalType.BUY)
        strategy._submit_bracket_for_entry.assert_called_once()


# Registry verified by successful import (decorator registered at load).
