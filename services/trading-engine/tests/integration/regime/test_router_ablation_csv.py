"""Story 12.9 — E2E router ablation harness driven by CSV fixtures.

Companion to ``test_router_e2e.py``. The sister file exercises hysteresis
and audit accounting with a scripted feature stream; this file pivots
to the strategy review §"Land during" #5 ask: "regime rejection actually
filters bars" — the ablation contract.

Coverage in one parametrized test:

* 4 CSV fixtures under ``fixtures/``, one per ``RegimeState`` the live
  router can produce post-warmup. Each fixture is the canonical feature
  vector that the rule-based classifier maps to that state — kept as a
  single-row CSV so the regime-engineering intent is visible at a glance
  and tweakable without code changes.

* 2 real production strategies — ``donchian_breakout`` (TRENDING_UP/DOWN)
  and ``bollinger_mean_reversion`` (RANGING). Their declared regimes are
  read from the live ``StrategyRegistry`` (decorator side-effect on
  module import), so a regime-list change in either strategy file would
  automatically retune the assertion table — the test stays pinned to
  intent, not to a hand-copied frozenset.

* The "ablation harness" assertion: per scenario, the strategy whose
  regime allow-list excludes the classified state must receive **zero**
  bars from the inner router. Existing ``test_router_e2e.py`` measures
  positive dispatch counts; only an explicit zero-on-the-other-side
  check proves the gate has teeth.

* HIGH_VOLATILITY exercises the global kill-switch — regardless of any
  strategy's allow-list, both strategies receive zero bars.

UNKNOWN is intentionally not covered: the rule-based classifier never
emits it post-warmup (only the ``None`` extractor sentinel does, and
warmup behaviour is already pinned by
``test_warmup_period_blocks_audit_and_dispatch`` in the sister file).

The CSV feature values are coupled to the threshold constants in
``_thresholds()`` below — moving any threshold without retuning the
fixture rows will silently change which regime each row classifies
into. Each fixture file carries an inline comment naming the boundary
it is meant to clear.
"""

from __future__ import annotations

import csv
import importlib
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from unittest.mock import Mock

import pytest

import src.strategies.bollinger_mean_reversion as _bollinger_module
import src.strategies.donchian_breakout as _donchian_module
from src.config.firm_profile import RegimeThresholds
from src.regime.audit import RegimeAuditAdapter
from src.regime.classifier import RuleBasedRegimeClassifier
from src.regime.features import RegimeFeatures
from src.regime.hysteresis import HysteresisFilter
from src.rules.audit_logger import AuditEntry
from src.strategies.regime_routing import RegimeAwareRouter
from src.strategies.registry import StrategyRegistry

FIXTURES = Path(__file__).parent / "fixtures"
M5_BAR_TYPE = "XAUUSD.BROKER-5-MINUTE-LAST-EXTERNAL"


@pytest.fixture(autouse=True)
def _ensure_strategies_registered():
    """Other unit suites (notably ``tests/unit/strategies/test_regime_aware_router.py``)
    call ``StrategyRegistry.clear()`` and never re-populate. Module-level
    imports do not re-trigger the ``@register_strategy`` decorator on a
    cleared registry because Python caches the module. Unregister both
    names first (idempotent) then reload the modules so the decorator
    side-effects re-fire — registry now matches the production wiring
    regardless of suite ordering.
    """
    StrategyRegistry.unregister("donchian_breakout")
    StrategyRegistry.unregister("bollinger_mean_reversion")
    importlib.reload(_donchian_module)
    importlib.reload(_bollinger_module)
    yield



WARMUP_BARS = 50
SEGMENT_BARS = 100
# After warmup, hysteresis needs `confirmation_bars` matching outputs
# before the new state becomes effective. With 100 identical post-warmup
# rows and confirmation_bars=2, the allowed strategy receives the last
# 98 bars of the segment (range tolerates one off-by-one if the upstream
# rule changes).
EXPECTED_ALLOWED_MIN, EXPECTED_ALLOWED_MAX = 95, 100


# ---------------------------------------------------------------------------
# Test doubles — mirror the in-tree pattern from test_router_e2e.py so the
# two integration files stay readable side by side.
# ---------------------------------------------------------------------------


class _ScriptedExtractor:
    def __init__(self, sequence: list[RegimeFeatures | None]) -> None:
        self._sequence = list(sequence)
        self._idx = 0

    def update(self, bar: Any) -> RegimeFeatures | None:
        if self._idx >= len(self._sequence):
            raise AssertionError("Scripted extractor exhausted")
        out = self._sequence[self._idx]
        self._idx += 1
        return out


class _RecordingInner:
    def __init__(self, accounts: list[Any]) -> None:
        self._accounts = accounts
        self.dispatches: list[tuple[Any, Any]] = []

    @property
    def bound_accounts(self) -> list[Any]:
        return list(self._accounts)

    def _route_bar_to_account(self, account: Any, bar: Any) -> None:
        self.dispatches.append((account, bar))

    def route_tick(self, tick: Any) -> None:
        pass

    async def route_tick_async(self, tick: Any) -> None:
        pass


class _RecordingAuditWriter:
    def __init__(self) -> None:
        self.entries: list[AuditEntry] = []

    async def log_async(self, entry: AuditEntry) -> None:
        self.entries.append(entry)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _thresholds() -> RegimeThresholds:
    return RegimeThresholds(
        adx_trend_min=25.0,
        adx_strong_trend=40.0,
        bb_width_low_pct=0.30,
        bb_width_high_pct=0.80,
        realized_vol_high=0.025,
        ema_slope_trend_threshold=0.0005,
    )


def _bar(minute: int) -> Mock:
    bar = Mock()
    bar.bar_type = M5_BAR_TYPE
    bar.ts_event = datetime(2026, 5, 1, 12, 0, tzinfo=timezone.utc) + timedelta(
        minutes=5 * minute
    )
    bar.symbol = "XAUUSD"
    return bar


def _account(strategy_name: str) -> Mock:
    a = Mock()
    a.strategy = strategy_name
    return a


def _load_features(csv_path: Path) -> RegimeFeatures:
    """Read the canonical single-row feature fixture.

    Skips ``#`` comment lines so each fixture can carry an inline note
    documenting which threshold boundary the row is meant to clear.
    """
    with csv_path.open() as f:
        non_comment = (line for line in f if not line.lstrip().startswith("#"))
        rows = list(csv.DictReader(non_comment))
    assert len(rows) == 1, (
        f"{csv_path.name} must hold exactly one feature row "
        f"(the canonical fixture for that regime); got {len(rows)}"
    )
    row = rows[0]
    return RegimeFeatures(
        adx=float(row["adx"]),
        plus_di=float(row["plus_di"]),
        minus_di=float(row["minus_di"]),
        bb_width_pct=float(row["bb_width_pct"]),
        realized_vol=float(row["realized_vol"]),
        ema_slope=float(row["ema_slope"]),
        is_warmed_up=row["is_warmed_up"].strip().lower() == "true",
    )


def _build_router(
    sequence: list[RegimeFeatures | None],
    accounts: list[Any],
) -> tuple[RegimeAwareRouter, _RecordingInner, _RecordingAuditWriter]:
    inner = _RecordingInner(accounts)
    extractor = _ScriptedExtractor(sequence)
    classifier = RuleBasedRegimeClassifier(_thresholds())
    hysteresis = {
        M5_BAR_TYPE: HysteresisFilter(
            bar_type=M5_BAR_TYPE,
            confirmation_bars=2,
            thresholds=_thresholds(),
        )
    }
    writer = _RecordingAuditWriter()
    audit = RegimeAuditAdapter(writer)
    # Pull the regime allow-lists straight from the production registry
    # so the test pins to declared intent rather than a hand-copied set.
    strategy_regime_map = {
        "donchian_breakout": StrategyRegistry.get_regimes("donchian_breakout"),
        "bollinger_mean_reversion": StrategyRegistry.get_regimes(
            "bollinger_mean_reversion"
        ),
    }
    router = RegimeAwareRouter(
        inner=inner,  # type: ignore[arg-type]
        classifier=classifier,
        feature_extractors={M5_BAR_TYPE: extractor},  # type: ignore[arg-type]
        hysteresis=hysteresis,
        audit=audit,
        strategy_regime_map=strategy_regime_map,
    )
    return router, inner, writer


# ---------------------------------------------------------------------------
# Ablation matrix — story 12.9
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "fixture_name, allowed_strategy, blocked_strategy",
    [
        ("trending_up.csv", "donchian_breakout", "bollinger_mean_reversion"),
        ("trending_down.csv", "donchian_breakout", "bollinger_mean_reversion"),
        ("ranging.csv", "bollinger_mean_reversion", "donchian_breakout"),
    ],
)
async def test_csv_fixture_routes_to_allowed_only(
    fixture_name: str, allowed_strategy: str, blocked_strategy: str
) -> None:
    """Ablation harness: the strategy whose declared regimes match the
    classified state receives bars; the other strategy receives ZERO.
    """
    feature = _load_features(FIXTURES / fixture_name)
    sequence: list[RegimeFeatures | None] = (
        [None] * WARMUP_BARS + [feature] * SEGMENT_BARS
    )

    allowed = _account(allowed_strategy)
    blocked = _account(blocked_strategy)
    router, inner, writer = _build_router(
        sequence=sequence, accounts=[allowed, blocked]
    )

    for i in range(len(sequence)):
        await router.route_bar_async(_bar(i))

    allowed_dispatches = [d for d in inner.dispatches if d[0] is allowed]
    blocked_dispatches = [d for d in inner.dispatches if d[0] is blocked]

    assert (
        EXPECTED_ALLOWED_MIN
        <= len(allowed_dispatches)
        <= EXPECTED_ALLOWED_MAX
    ), (
        f"{allowed_strategy} should receive most of the {SEGMENT_BARS}-bar "
        f"segment after hysteresis confirmation; got {len(allowed_dispatches)}"
    )
    assert blocked_dispatches == [], (
        f"{blocked_strategy} should receive zero bars when the regime is "
        f"outside its allow-list (ablation gate has no teeth otherwise)"
    )

    # Audit row count = bars after warmup (hysteresis stamps every
    # post-warmup decision regardless of dispatch outcome).
    assert len(writer.entries) == SEGMENT_BARS


@pytest.mark.asyncio
async def test_high_volatility_kills_every_strategy() -> None:
    """HIGH_VOLATILITY is the global kill-switch — bypasses the per-strategy
    allow-list. Both strategies in the ablation matrix must receive zero
    bars even though donchian's allow-list omits HIGH_VOL only by accident
    (it's a TRENDING-only strategy) and bollinger's omits it deliberately.
    """
    feature = _load_features(FIXTURES / "high_volatility.csv")
    sequence: list[RegimeFeatures | None] = (
        [None] * WARMUP_BARS + [feature] * SEGMENT_BARS
    )
    donchian = _account("donchian_breakout")
    bollinger = _account("bollinger_mean_reversion")
    router, inner, writer = _build_router(
        sequence=sequence, accounts=[donchian, bollinger]
    )
    for i in range(len(sequence)):
        await router.route_bar_async(_bar(i))

    assert inner.dispatches == [], (
        "HIGH_VOLATILITY must short-circuit dispatch for every account "
        "before per-strategy filtering runs"
    )
    # The audit hop still fires — kill-switch is a routing decision, not
    # an audit suppression.
    assert len(writer.entries) == SEGMENT_BARS
    last = writer.entries[-1]
    assert last.rule_result == "high_volatility"
