"""Latency SLO integration test for ConsistencyRule (Epic 9 Phase 0, P0.15).

The consistency rule is evaluated on every order in the validate→send hot
path, so its per-call latency directly affects order acknowledgement time.
This test asserts the rule stays well within the 10ms p99 budget across
the three semantic verdicts (ALLOW / WARN / BLOCK) under realistic
``daily_profits_history`` sizes.

Why integration, not unit:
- Exercises the same code path the production hot path will hit (rule
  validate + RuleResult construction including BLOCK metadata dict and
  format-string message). Unit tests cover correctness; this guards the
  *runtime cost* of those same flows.
- Uses 60-day history (matches ``DailyProfitHistory.lookback_days=60``
  default in production) plus a 365-day stress case to confirm headroom.

Methodology:
- Warm-up to amortise interpreter / JIT-style effects (Python doesn't JIT
  but cold-cache effects on first call are real).
- ``ITERATIONS`` repeated calls timed individually with
  ``time.perf_counter_ns`` for nanosecond resolution.
- Assert p99 < SLO; surface mean/p50/p95/p99/max in the failure message
  so a regression is diagnosable from the CI log alone.

CI tolerance:
- The SLO at 10ms is generous against ~µs-scale measured cost on
  developer hardware; CI runners that are 100x slower still pass with
  margin. The threshold is a regression alarm, not a microbenchmark.
"""

from __future__ import annotations

import gc
import statistics
import time
from datetime import date, timedelta

import pytest

from src.rules.base_rule import RuleAction
from src.rules.types.consistency import ConsistencyRule


# Per-call SLO. ConsistencyRule sits inside the order validate hot path;
# 10ms keeps headroom under the broader order-ack budget.
SLO_MS = 10.0

# Sized for stable percentiles without making the test slow.
WARMUP = 200
ITERATIONS = 5_000

# Arbitrary anchor for the synthetic history; the rule does not care which
# calendar date the entries are keyed on — only their count and sign.
_FIXTURE_BASE_DATE = date(2000, 1, 1)


def _build_history(days: int, daily_pnl: float, base: date | None = None) -> dict[date, float]:
    """Return a contiguous ``daily_profits_history`` dict of ``days`` entries.

    All entries are positive so the rule's positive-sum loop runs the full
    length of the dict (worst case for the O(N) iterate inside
    ``_compute_ratio_percent``).
    """
    if base is None:
        base = _FIXTURE_BASE_DATE
    return {base + timedelta(days=i): daily_pnl for i in range(days)}


def _measure(rule: ConsistencyRule, ctx: dict, expected: RuleAction) -> list[float]:
    """Time ``rule.validate(ctx)`` ``ITERATIONS`` times after warmup.

    Returns per-call latencies in milliseconds. Asserts the verdict each
    iteration so a fixture mistake fails the test loudly instead of
    benchmarking the wrong code path.
    """
    for _ in range(WARMUP):
        result = rule.validate(ctx)
        assert result.action == expected

    samples_ms: list[float] = []
    # Suppress cyclic GC across the timing loop so a stochastic GC pause
    # cannot push a single sample into the multi-ms range and flip the
    # p99 assertion on a loaded CI runner. This is the same approach
    # pytest-benchmark uses internally; if the rule genuinely regresses,
    # mean/p50/p95 will all move, not just one outlier.
    gc.collect()
    gc.disable()
    try:
        for _ in range(ITERATIONS):
            t0 = time.perf_counter_ns()
            result = rule.validate(ctx)
            elapsed_ns = time.perf_counter_ns() - t0
            assert result.action == expected
            samples_ms.append(elapsed_ns / 1_000_000.0)
    finally:
        gc.enable()
    return samples_ms


def _percentile(sorted_samples: list[float], pct: float) -> float:
    """Nearest-rank percentile on a presorted sample list."""
    if not sorted_samples:
        raise ValueError("empty samples")
    k = max(0, min(len(sorted_samples) - 1, int(round(pct / 100.0 * len(sorted_samples))) - 1))
    return sorted_samples[k]


def _summary(samples_ms: list[float]) -> dict[str, float]:
    sorted_samples = sorted(samples_ms)
    return {
        "n": float(len(samples_ms)),
        "mean": statistics.fmean(samples_ms),
        "p50": _percentile(sorted_samples, 50),
        "p95": _percentile(sorted_samples, 95),
        "p99": _percentile(sorted_samples, 99),
        "max": sorted_samples[-1],
    }


def _assert_slo(samples_ms: list[float], label: str) -> dict[str, float]:
    s = _summary(samples_ms)
    assert s["p99"] < SLO_MS, (
        f"[{label}] p99 latency {s['p99']:.4f}ms exceeds SLO {SLO_MS}ms — "
        f"mean={s['mean']:.4f}ms p50={s['p50']:.4f}ms p95={s['p95']:.4f}ms "
        f"max={s['max']:.4f}ms (n={int(s['n'])})"
    )
    return s


def _print_summary(label: str, s: dict[str, float]) -> None:
    """Emit a one-line summary via plain ``print``.

    Pytest captures stdout by default and surfaces it in the failure log,
    so the summary appears alongside the assertion message exactly when a
    regression strikes. With ``-s`` it also streams on success for trend
    inspection.
    """
    print(
        f"\n{label:10s} n={int(s['n'])} "
        f"mean={s['mean']:.4f}ms p50={s['p50']:.4f}ms "
        f"p95={s['p95']:.4f}ms p99={s['p99']:.4f}ms max={s['max']:.4f}ms"
    )


@pytest.mark.integration
class TestConsistencyRuleLatency:
    """Per-verdict latency tests over a realistic 60-day history."""

    def test_allow_path_p99_under_slo(self) -> None:
        # Loss day → short-circuits at the first guard, exercises the
        # cheapest path through the rule.
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": -50.0,
            "daily_profits_history": _build_history(days=60, daily_pnl=100.0),
        }
        samples = _measure(rule, ctx, RuleAction.ALLOW)
        _print_summary("ALLOW", _assert_slo(samples, "ALLOW"))

    def test_warn_path_p99_under_slo(self) -> None:
        # 60 prior days × $100 = $6000 positive sum; today $4000 →
        # ratio = 4000 / 10000 = 40% → WARN (lowest threshold).
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 4000.0,
            "daily_profits_history": _build_history(days=60, daily_pnl=100.0),
        }
        samples = _measure(rule, ctx, RuleAction.WARN)
        _print_summary("WARN", _assert_slo(samples, "WARN"))

    def test_block_path_p99_under_slo(self) -> None:
        # 60 prior days × $100 = $6000 positive sum; today $7000 →
        # ratio = 7000 / 13000 ≈ 53.85% → BLOCK. BLOCK is the most
        # expensive path: builds metadata dict + formatted message.
        rule = ConsistencyRule()
        ctx = {
            "current_day_pnl": 7000.0,
            "daily_profits_history": _build_history(days=60, daily_pnl=100.0),
        }
        samples = _measure(rule, ctx, RuleAction.BLOCK)
        _print_summary("BLOCK", _assert_slo(samples, "BLOCK"))


@pytest.mark.integration
class TestConsistencyRuleLatencyExtended:
    """Stress: history beyond the production lookback to expose O(N) headroom.

    Production caps history at ``DailyProfitHistory.lookback_days=60``. A
    365-day fixture is roughly 6× that; if p99 still clears 10ms with that
    much margin, the rule is comfortably future-proof against a longer
    lookback should ops ever raise it.
    """

    def test_block_path_365_days_p99_under_slo(self) -> None:
        rule = ConsistencyRule()
        # 365 × $100 = $36,500 positive sum; today $50,000 →
        # ratio ≈ 57.8% → BLOCK.
        ctx = {
            "current_day_pnl": 50_000.0,
            "daily_profits_history": _build_history(days=365, daily_pnl=100.0),
        }
        samples = _measure(rule, ctx, RuleAction.BLOCK)
        _print_summary("BLOCK-365d", _assert_slo(samples, "BLOCK-365d"))
