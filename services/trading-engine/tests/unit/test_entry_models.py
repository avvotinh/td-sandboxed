"""Unit tests for the ported entry models (roadmap task 3.3).

Two things are under test here.

**The two-phase contract.** ``update`` advances rolling state on every
bar; ``evaluate`` decides only for bars that survive the host's gates.
The invariant that matters is what happens to a *gated* bar: its state
upkeep must still run, or the first bar after a session gap compares
against a frozen pre-gap snapshot. Each model gets a test that drives
``update`` without ``evaluate`` and asserts the next bar behaves as if
the gated bar had been seen — because it was.

**No lookahead.** ``TestNoLookahead`` asserts the API shape that makes
reaching forward impossible — ``evaluate`` takes no bar — and that no
model retains a sequence of bars, which is the only way one could get
hold of a future bar. It deliberately does *not* rest on comparing
prefix runs to the full run; that comparison was measured against a
deliberately cheating model and caught nothing. See the class docstring.
"""

from __future__ import annotations

import inspect
import math
from collections.abc import Callable
from unittest.mock import Mock

import pytest
from nautilus_trader.model.data import Bar

from src.kernel.entries import (
    DonchianCrossEntry,
    EntryModel,
    EntrySide,
    MeanReversionBandEntry,
    SupertrendFlipEntry,
)
from src.lab.recorder.indicator_recorder import IndicatorRecorder


pytestmark = pytest.mark.unit


def _mock_bar(close: float) -> Mock:
    bar = Mock()
    bar.close = Mock()
    bar.close.as_double = Mock(return_value=close)
    bar.ts_init = 0
    return bar


class TestDonchianCrossEntry:
    def _armed(self, **overrides) -> DonchianCrossEntry:
        """A model whose channel sits at a fixed 2380–2420, no warmup."""
        model = DonchianCrossEntry(**{"channel_period": 20, **overrides})
        model._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        return model

    def test_seed_bar_has_no_prior_band_to_cross(self) -> None:
        model = self._armed()
        assert model.update(_mock_bar(2500.0)) is True
        assert model.evaluate() is None

    def test_close_above_prior_upper_is_a_long(self) -> None:
        model = self._armed()
        model.update(_mock_bar(2400.0))  # seed the prior band
        model.update(_mock_bar(2430.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.LONG
        assert intent.reason == "donchian_upper_cross"

    def test_close_below_prior_lower_is_a_short(self) -> None:
        model = self._armed()
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2370.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.SHORT
        assert intent.reason == "donchian_lower_cross"

    def test_close_inside_the_channel_is_no_entry(self) -> None:
        model = self._armed()
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2410.0))
        assert model.evaluate() is None

    def test_level_trigger_re_fires_every_bar_outside(self) -> None:
        model = self._armed(entry_on_cross_only=False)
        model.update(_mock_bar(2400.0))
        for close in (2430.0, 2431.0, 2432.0):
            model.update(_mock_bar(close))
            assert model.evaluate() is not None

    def test_edge_trigger_fires_only_on_the_first_bar(self) -> None:
        model = self._armed(entry_on_cross_only=True)
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2430.0))
        assert model.evaluate() is not None
        model.update(_mock_bar(2431.0))
        assert model.evaluate() is None

    def test_edge_trigger_rearms_after_price_returns_inside(self) -> None:
        model = self._armed(entry_on_cross_only=True)
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2430.0))
        assert model.evaluate() is not None
        model.update(_mock_bar(2400.0))  # back inside — episode ends
        assert model.evaluate() is None
        model.update(_mock_bar(2430.0))  # new episode
        assert model.evaluate() is not None

    def test_gated_bar_still_arms_the_edge_trigger(self) -> None:
        """The invariant the two-phase split exists for.

        A breakout that a session gate throws away must still close the
        episode. Otherwise the first bar after the gap reads as "first
        breakout bar" and the edge trigger fires on a stale episode.
        """
        model = self._armed(entry_on_cross_only=True)
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2430.0))  # gated: update runs, evaluate does not
        model.update(_mock_bar(2431.0))
        assert model.evaluate() is None

    def test_reset_clears_band_and_episode_state(self) -> None:
        model = self._armed(entry_on_cross_only=True)
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2430.0))
        model.reset()
        model._donchian = Mock(initialized=True, upper=2420.0, lower=2380.0)
        # Post-reset the first bar is a seed again, not a continuation.
        model.update(_mock_bar(2430.0))
        assert model.evaluate() is None

    def test_evaluate_without_update_is_no_entry(self) -> None:
        assert self._armed().evaluate() is None


class TestSupertrendFlipEntry:
    def _armed(self, trend: int) -> SupertrendFlipEntry:
        model = SupertrendFlipEntry(period=10, multiplier=3.0)
        model._supertrend = Mock(initialized=True, trend=trend, value=2400.0)
        return model

    def test_first_bar_only_seeds(self) -> None:
        model = self._armed(trend=1)
        model.update(_mock_bar(2400.0))
        assert model.evaluate() is None

    def test_flip_up_is_a_long(self) -> None:
        model = self._armed(trend=-1)
        model.update(_mock_bar(2400.0))
        model._supertrend.trend = 1
        model.update(_mock_bar(2401.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.LONG
        assert intent.reason == "supertrend_flip_up"

    def test_flip_down_is_a_short(self) -> None:
        model = self._armed(trend=1)
        model.update(_mock_bar(2400.0))
        model._supertrend.trend = -1
        model.update(_mock_bar(2399.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.SHORT
        assert intent.reason == "supertrend_flip_down"

    def test_trend_continuation_is_no_entry(self) -> None:
        model = self._armed(trend=1)
        model.update(_mock_bar(2400.0))
        model.update(_mock_bar(2401.0))
        assert model.evaluate() is None

    def test_undirected_trend_is_no_entry(self) -> None:
        # A 0 trend is neither side; the model must not guess one.
        model = self._armed(trend=1)
        model.update(_mock_bar(2400.0))
        model._supertrend.trend = 0
        model.update(_mock_bar(2400.0))
        assert model.evaluate() is None

    def test_gated_flip_does_not_re_fire_on_the_next_bar(self) -> None:
        model = self._armed(trend=-1)
        model.update(_mock_bar(2400.0))
        model._supertrend.trend = 1
        model.update(_mock_bar(2401.0))  # gated: the flip is consumed here
        model.update(_mock_bar(2402.0))
        assert model.evaluate() is None

    def test_reset_clears_the_trend_reference(self) -> None:
        model = self._armed(trend=-1)
        model.update(_mock_bar(2400.0))
        model.reset()
        model._supertrend = Mock(initialized=True, trend=1, value=2400.0)
        model.update(_mock_bar(2401.0))
        assert model.evaluate() is None  # seed again, not a flip


class TestMeanReversionBandEntry:
    def _armed(self, *, rsi: float, **overrides) -> MeanReversionBandEntry:
        defaults = dict(
            bb_period=20,
            num_std=2.0,
            rsi_period=14,
            oversold=0.3,
            overbought=0.7,
        )
        defaults.update(overrides)
        model = MeanReversionBandEntry(**defaults)
        model._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        model._rsi = Mock(initialized=True, value=rsi)
        return model

    def test_rejects_an_unknown_entry_mode(self) -> None:
        with pytest.raises(ValueError, match="entry_mode"):
            MeanReversionBandEntry(
                bb_period=20,
                num_std=2.0,
                rsi_period=14,
                oversold=0.3,
                overbought=0.7,
                entry_mode="yolo",
            )

    def test_pierce_needs_both_band_and_rsi(self) -> None:
        model = self._armed(rsi=0.5)  # band pierced, RSI not extreme
        model.update(_mock_bar(2370.0))
        assert model.evaluate() is None

    def test_pierce_long_on_lower_band_with_oversold_rsi(self) -> None:
        model = self._armed(rsi=0.2)
        model.update(_mock_bar(2370.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.LONG
        assert intent.reason == "bb_lower_pierce_rsi_oversold"

    def test_pierce_short_on_upper_band_with_overbought_rsi(self) -> None:
        model = self._armed(rsi=0.8)
        model.update(_mock_bar(2430.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.SHORT
        assert intent.reason == "bb_upper_pierce_rsi_overbought"

    def test_recross_ignores_the_pierce_bar_itself(self) -> None:
        model = self._armed(rsi=0.2, entry_mode="recross")
        model.update(_mock_bar(2370.0))
        assert model.evaluate() is None

    def test_recross_enters_on_the_snap_back_bar(self) -> None:
        model = self._armed(rsi=0.2, entry_mode="recross")
        model.update(_mock_bar(2370.0))  # pierce
        model.update(_mock_bar(2385.0))  # back inside the band
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.LONG
        assert intent.reason == "bb_lower_recross_rsi_oversold"

    def test_recross_short_on_the_snap_back_from_above(self) -> None:
        model = self._armed(rsi=0.8, entry_mode="recross")
        model.update(_mock_bar(2430.0))
        model.update(_mock_bar(2415.0))
        intent = model.evaluate()
        assert intent is not None
        assert intent.side is EntrySide.SHORT
        assert intent.reason == "bb_upper_recross_rsi_overbought"

    def test_gated_pierce_still_arms_the_snap_back(self) -> None:
        model = self._armed(rsi=0.2, entry_mode="recross")
        model.update(_mock_bar(2370.0))  # gated: update runs, evaluate does not
        model.update(_mock_bar(2385.0))
        assert model.evaluate() is not None

    def test_collapsed_band_is_an_unusable_bar(self) -> None:
        model = self._armed(rsi=0.2)
        model._bb = Mock(initialized=True, upper=2400.0, middle=2400.0, lower=2400.0)
        assert model.update(_mock_bar(2370.0)) is False
        assert model.evaluate() is None

    def test_collapsed_band_leaves_the_recross_reference_untouched(self) -> None:
        """A degenerate bar must not overwrite a real prior pierce.

        Pins the contract, not a reachable scenario. With a real
        ``BollingerBands`` this sequence cannot occur: ``upper == lower``
        needs the last ``bb_period`` typical prices identical, which
        forces the prior bar's window to be near-degenerate too, so the
        prior close cannot have been outside its own band. It is
        constructed by swapping the indicator mid-sequence, and it earns
        its place by pinning what ``update() -> False`` promises — frozen
        references — rather than by modelling real market data.
        """
        model = self._armed(rsi=0.2, entry_mode="recross")
        model.update(_mock_bar(2370.0))  # real pierce
        collapsed = Mock(initialized=True, upper=2400.0, middle=2400.0, lower=2400.0)
        good = model._bb
        model._bb = collapsed
        assert model.update(_mock_bar(2399.0)) is False
        model._bb = good
        model.update(_mock_bar(2385.0))
        # The pierce two bars back still counts — the collapsed bar was
        # skipped whole, not recorded as "close was inside the band".
        assert model.evaluate() is not None

    def test_middle_exposes_the_exit_target(self) -> None:
        assert self._armed(rsi=0.5).middle == 2400.0

    def test_reset_clears_the_snap_back_reference(self) -> None:
        model = self._armed(rsi=0.2, entry_mode="recross")
        model.update(_mock_bar(2370.0))
        model.reset()
        model._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        model._rsi = Mock(initialized=True, value=0.2)
        model.update(_mock_bar(2385.0))
        assert model.evaluate() is None


class TestExportIndicators:
    """Series the models write into Contract v2.

    Guarded because the keys, titles, colours and panes here are part of
    the exported result JSON — the chart viewer reads them by name, and
    the P3 parity gate hashes the whole ``indicators`` section, so a
    silent rename would either break the viewer or blow the gate.
    """

    def _recorder(self) -> IndicatorRecorder:
        return IndicatorRecorder()

    def test_donchian_records_three_bands(self) -> None:
        model = DonchianCrossEntry(channel_period=20)
        model._donchian = Mock(
            initialized=True, upper=2420.0, lower=2380.0, middle=2400.0
        )
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2400.0), recorder)
        series = {s.key: s for s in recorder.to_series()}
        assert set(series) == {"donchian_upper", "donchian_lower", "donchian_middle"}
        assert all(s.pane == "overlay" for s in series.values())
        assert series["donchian_upper"].points[0][1] == 2420.0
        assert series["donchian_lower"].points[0][1] == 2380.0

    def test_donchian_survives_an_indicator_without_a_middle_band(self) -> None:
        # The getattr guard: a future indicator swap that drops `middle`
        # must degrade to an empty series, not raise mid-backtest.
        model = DonchianCrossEntry(channel_period=20)
        model._donchian = Mock(spec=["initialized", "upper", "lower", "reset"])
        model._donchian.initialized = True
        model._donchian.upper = 2420.0
        model._donchian.lower = 2380.0
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2400.0), recorder)
        series = {s.key: s for s in recorder.to_series()}
        assert series["donchian_middle"].points == ()

    def test_donchian_records_nothing_before_warmup(self) -> None:
        model = DonchianCrossEntry(channel_period=20)
        model._donchian = Mock(initialized=False, upper=0.0, lower=0.0, middle=0.0)
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2400.0), recorder)
        assert recorder.to_series() == ()

    def test_supertrend_splits_the_line_by_direction(self) -> None:
        model = SupertrendFlipEntry(period=10, multiplier=3.0)
        model._supertrend = Mock(initialized=True, trend=1, value=2390.0)
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2400.0), recorder)
        series = {s.key: s for s in recorder.to_series()}
        # Both series exist; only the active direction carries a point,
        # which is what gives the chart its two-colour line.
        assert series["supertrend_up"].points[0][1] == 2390.0
        assert series["supertrend_down"].points == ()

    def test_supertrend_records_nothing_without_a_value(self) -> None:
        model = SupertrendFlipEntry(period=10, multiplier=3.0)
        model._supertrend = Mock(initialized=True, trend=1, value=None)
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2400.0), recorder)
        assert recorder.to_series() == ()

    def test_mr_records_bands_and_an_rsi_pane_with_levels(self) -> None:
        model = MeanReversionBandEntry(
            bb_period=20, num_std=2.0, rsi_period=14, oversold=0.3, overbought=0.7
        )
        model._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        model._rsi = Mock(initialized=True, value=0.25)
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2370.0), recorder)
        series = {s.key: s for s in recorder.to_series()}
        assert set(series) == {"bb_upper", "bb_middle", "bb_lower", "rsi"}
        assert series["rsi"].pane == "rsi"
        assert series["rsi"].title == "RSI (14)"
        # Levels drive the oversold/overbought guides on the RSI pane.
        assert series["rsi"].levels == (0.3, 0.7)

    def test_mr_records_bands_while_rsi_is_still_warming_up(self) -> None:
        model = MeanReversionBandEntry(
            bb_period=20, num_std=2.0, rsi_period=14, oversold=0.3, overbought=0.7
        )
        model._bb = Mock(initialized=True, upper=2420.0, middle=2400.0, lower=2380.0)
        model._rsi = Mock(initialized=False, value=None)
        recorder = self._recorder()
        model.export_indicators(_mock_bar(2400.0), recorder)
        assert {s.key for s in recorder.to_series()} == {
            "bb_upper",
            "bb_middle",
            "bb_lower",
        }

    def test_registration_is_idempotent_across_bars(self) -> None:
        model = DonchianCrossEntry(channel_period=20)
        model._donchian = Mock(
            initialized=True, upper=2420.0, lower=2380.0, middle=2400.0
        )
        recorder = self._recorder()
        for i in range(3):
            bar = _mock_bar(2400.0)
            bar.ts_init = i * 60_000_000_000
            model.export_indicators(bar, recorder)
        series = {s.key: s for s in recorder.to_series()}
        assert len(series) == 3
        assert len(series["donchian_upper"].points) == 3


def _synthetic_closes(n: int) -> list[float]:
    """A deterministic two-frequency wave that crosses bands both ways."""
    return [
        2400.0 + 40.0 * math.sin(i / 7.0) + 15.0 * math.sin(i / 2.3) for i in range(n)
    ]


def _drive(model: EntryModel, bars: list[Bar]) -> list[str | None]:
    """Run a model over bars the way a strategy would; collect reasons."""
    reasons: list[str | None] = []
    for bar in bars:
        for indicator in model.indicators():
            indicator.handle_bar(bar)
        if not model.ready or not model.update(bar):
            reasons.append(None)
            continue
        intent = model.evaluate()
        reasons.append(intent.reason if intent is not None else None)
    return reasons


def _models() -> list[Callable[[], EntryModel]]:
    return [
        lambda: DonchianCrossEntry(channel_period=20),
        lambda: DonchianCrossEntry(channel_period=20, entry_on_cross_only=True),
        lambda: SupertrendFlipEntry(period=10, multiplier=3.0),
        lambda: MeanReversionBandEntry(
            bb_period=20, num_std=2.0, rsi_period=14, oversold=0.3, overbought=0.7
        ),
        lambda: MeanReversionBandEntry(
            bb_period=20,
            num_std=2.0,
            rsi_period=14,
            oversold=0.3,
            overbought=0.7,
            entry_mode="recross",
        ),
    ]


class TestNoLookahead:
    """Every decision must depend on bars ≤ t and nothing after.

    Required by ``.claude/rules/common/sandboxed-domain.md``.

    **What actually enforces this is the API shape, not a data test.**
    ``update()`` is handed one bar and ``evaluate()`` is handed nothing,
    so at bar *t* no future bar exists inside the model to read. That is
    a structural guarantee, and the tests that matter here are the ones
    that keep the structure intact.

    A prefix-comparison test — run the model over ``bars[:k]``, compare
    against the full run — looks like the obvious check and is very
    nearly worthless. This was measured, not assumed: a deliberately
    cheating model that reads ``series[i + 1]`` from a sequence captured
    at construction is **not** caught by comparing prefixes at three
    cuts, nor at all 180 boundaries. Inside the prefix both runs see the
    same bars, and at the boundary the cheat has no next bar either, so
    the outputs agree. The only route by which a model could obtain a
    future bar is to hold a sequence of them, so that is what
    ``test_model_holds_no_bar_sequence`` looks for — and it does catch
    the cheating model that the prefix comparison misses.

    The determinism sweep is kept below, described as what it is: a
    guard that the models stay streaming and stateless-across-runs, not
    a proof of anything about lookahead.
    """

    def test_evaluate_takes_no_bar(self) -> None:
        """The structural invariant: a model cannot be handed a future bar.

        If ``evaluate`` ever grows a bar (or series) parameter, the whole
        anti-lookahead argument above collapses and this must be
        rethought rather than re-approved.
        """
        for factory in _models():
            params = list(inspect.signature(factory().evaluate).parameters)
            assert params == [], f"evaluate() must take no arguments, got {params}"

    def test_update_takes_exactly_one_bar(self) -> None:
        for factory in _models():
            params = list(inspect.signature(factory().update).parameters)
            assert params == ["bar"], f"update() must take one bar, got {params}"

    @pytest.mark.parametrize("factory", _models())
    def test_model_holds_no_bar_sequence(
        self, factory: Callable[[], EntryModel], bars: list[Bar]
    ) -> None:
        """No model may retain a sequence of bars.

        Buffering bars is the only way a model could ever reach a future
        one, so retaining a list of them is the thing to forbid — this is
        the check that actually catches an oracle, where the prefix
        comparison does not. Holding *scalars* derived from past bars
        (``_prev_close``, ``_prev_upper``) is the normal, causal case and
        stays allowed.
        """
        model = factory()
        _drive(model, bars)
        for name, value in vars(model).items():
            if isinstance(value, (list, tuple, set, dict)):
                contents = value.values() if isinstance(value, dict) else value
                assert not any(isinstance(item, Bar) for item in contents), (
                    f"{type(model).__name__}.{name} retains Bar objects — "
                    "a model that buffers bars can reach a future one"
                )

    @pytest.fixture
    def bars(self, bar_series: Callable[..., list[Bar]]) -> list[Bar]:
        closes = _synthetic_closes(180)
        return bar_series(
            open=[closes[max(i - 1, 0)] for i in range(len(closes))],
            high=[c + 3.0 for c in closes],
            low=[c - 3.0 for c in closes],
            close=closes,
        )

    @pytest.mark.parametrize("factory", _models())
    def test_series_actually_produces_entries(
        self, factory: Callable[[], EntryModel], bars: list[Bar]
    ) -> None:
        # Guards the tests below from passing vacuously on a series that
        # never triggers anything.
        assert any(r is not None for r in _drive(factory(), bars))

    @pytest.mark.parametrize("factory", _models())
    def test_decisions_are_streaming_and_repeatable(
        self, factory: Callable[[], EntryModel], bars: list[Bar]
    ) -> None:
        """A prefix run decides the same as the full run for shared bars.

        NOT a lookahead proof — see the class docstring; a cheating model
        passes this. What it does pin is that a model's answer for bar
        *t* does not depend on how many bars follow it, which is what
        would break if someone introduced whole-series normalisation or
        made a model's warmup depend on the dataset length. Cheap, and it
        would have caught a real class of mistake.
        """
        full = _drive(factory(), bars)
        for length in (40, 90, 140):
            assert _drive(factory(), bars[:length]) == full[:length]
