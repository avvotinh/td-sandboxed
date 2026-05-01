"""Structural guard for the strategy ↔ ValidatedZmqAdapter validation gate.

Story 10.6 (D7#2) — every order from a strategy must flow through the
Nautilus ``submit_order`` / ``submit_order_list`` seam so the live
execution client (story 10.5c :class:`ZmqExecutionClient`) gets to
validate it through :class:`ValidatedZmqAdapter` (rule engine + 10.4
atomic exposure gate). The two construction primitives we centralise:

- ``order_factory.bracket(...)`` — bracket OrderList builder. Strategies
  build brackets through :meth:`BaseStrategy._submit_bracket_via_factory`;
  no strategy is allowed to call ``order_factory.bracket`` directly.
- ``submit_order_list(...)`` — the Nautilus seam that hands an OrderList
  to the engine. Same single seam in ``BaseStrategy``.

A direct ``order_factory.market(...)`` + ``submit_order(...)`` is fine —
that path already routes through ``submit_order`` which the validated
adapter intercepts.

These tests parse every ``src/strategies/**/*.py`` file with the AST
module so they are robust against formatting changes; only an actual
new ``order_factory.bracket`` call site (or a new ``submit_order_list``
caller) outside the documented seam will trigger a failure.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
STRATEGIES_DIR = REPO_ROOT / "src" / "strategies"

# Files allowed to call the centralised construction primitives. Adding
# a new entry here is a deliberate architectural decision and should be
# called out in code review.
SEAM_FILES = {
    str((STRATEGIES_DIR / "base_strategy.py").resolve()),
}


def _strategy_py_files() -> list[Path]:
    return sorted(
        p
        for p in STRATEGIES_DIR.rglob("*.py")
        if "__pycache__" not in p.parts
    )


def _attribute_calls(tree: ast.AST, attr_name: str) -> list[ast.Call]:
    """Return every ``ast.Call`` whose function is ``<...>.<attr_name>``."""
    matches: list[ast.Call] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == attr_name:
            matches.append(node)
    return matches


def _name_calls(tree: ast.AST, name: str) -> list[ast.Call]:
    """Return every bare ``name(...)`` call (no ``self.`` / ``obj.`` prefix)."""
    matches: list[ast.Call] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if node.func.id == name:
                matches.append(node)
    return matches


def _attribute_chain_contains(node: ast.AST, name: str) -> bool:
    """Walk an ``ast.Attribute`` chain and return True if any segment matches.

    Example: ``self.order_factory.bracket`` resolves to chain
    ``[bracket, order_factory, self]``. Used to ensure the ``.bracket``
    call is anchored on ``order_factory`` rather than some unrelated
    attribute that happens to share the name.
    """
    cur: ast.AST | None = node
    while cur is not None:
        if isinstance(cur, ast.Attribute):
            if cur.attr == name:
                return True
            cur = cur.value
        elif isinstance(cur, ast.Name):
            return cur.id == name
        else:
            return False
    return False


# -------------------------------------------------------------------------
# order_factory.bracket gate
# -------------------------------------------------------------------------


class TestBracketSeam:
    """``self.order_factory.bracket(...)`` must live in ``base_strategy.py`` only."""

    def test_seam_file_contains_exactly_one_bracket_call(self) -> None:
        seam = STRATEGIES_DIR / "base_strategy.py"
        tree = ast.parse(seam.read_text(encoding="utf-8"))
        calls = _attribute_calls(tree, "bracket")
        # One canonical call inside _submit_bracket_via_factory.
        assert len(calls) == 1, (
            f"{seam.name} should contain exactly one ``.bracket(...)`` call "
            f"(the validation seam); found {len(calls)}"
        )

    def test_no_strategy_outside_seam_calls_order_factory_bracket(self) -> None:
        offenders: list[str] = []
        for path in _strategy_py_files():
            if str(path.resolve()) in SEAM_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _attribute_calls(tree, "bracket"):
                # Narrow further: ignore unrelated ``.bracket`` attributes
                # that aren't under ``order_factory`` (today none exist,
                # but be defensive).
                func = call.func
                # ``func`` is ``ast.Attribute(attr='bracket')``; check the
                # value's chain ends in 'order_factory' to avoid false
                # positives on string ``.bracket`` etc.
                if _attribute_chain_contains(func, "order_factory"):
                    offenders.append(
                        f"{path.relative_to(REPO_ROOT)}:{call.lineno}"
                    )

        assert not offenders, (
            "Strategies must not call ``order_factory.bracket`` directly — "
            "use ``BaseStrategy._submit_bracket_order`` so the live "
            "execution client (story 10.5c) gets to validate every "
            "bracket. Offenders:\n  " + "\n  ".join(offenders)
        )


# -------------------------------------------------------------------------
# submit_order_list gate
# -------------------------------------------------------------------------


class TestSubmitOrderListSeam:
    """``submit_order_list(...)`` must live in ``base_strategy.py`` only."""

    def test_no_strategy_outside_seam_calls_submit_order_list(self) -> None:
        offenders: list[str] = []
        for path in _strategy_py_files():
            if str(path.resolve()) in SEAM_FILES:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"))
            attr_calls = _attribute_calls(tree, "submit_order_list")
            bare_calls = _name_calls(tree, "submit_order_list")
            for call in attr_calls + bare_calls:
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno}"
                )

        assert not offenders, (
            "Strategies must not call ``submit_order_list`` directly — "
            "the centralised seam in ``base_strategy.py`` keeps the "
            "validation gate auditable. Offenders:\n  "
            + "\n  ".join(offenders)
        )


# -------------------------------------------------------------------------
# submit_order is allowed but only via Nautilus's standard seam
# -------------------------------------------------------------------------


class TestSubmitOrderUsage:
    """``submit_order`` is the Nautilus seam the live exec client wraps;
    we only flag the (hypothetical) anti-pattern of strategies calling
    the venue / exec engine directly."""

    @pytest.mark.parametrize(
        "forbidden",
        [
            "exec_engine",       # Nautilus internal — strategies must not touch
            "_send",             # would bypass the public seam
            "send_order_and_wait",  # the validated adapter's own method
        ],
    )
    def test_strategies_dont_reach_into_low_level_apis(
        self, forbidden: str
    ) -> None:
        offenders: list[str] = []
        for path in _strategy_py_files():
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for call in _attribute_calls(tree, forbidden):
                offenders.append(
                    f"{path.relative_to(REPO_ROOT)}:{call.lineno}"
                )
        assert not offenders, (
            f"Strategies must not call ``.{forbidden}(...)`` — use the "
            "Nautilus ``submit_order`` / ``submit_order_list`` seam so "
            "the live execution client validates the order. "
            f"Offenders:\n  " + "\n  ".join(offenders)
        )


# -------------------------------------------------------------------------
# Audit roster — every concrete strategy is on the right side
# -------------------------------------------------------------------------


class TestStrategyRoster:
    """Concrete strategies' submission paths land in one of two buckets:
    bracket via ``_submit_bracket_for_entry`` or simple market via the
    parent ``_go_long`` / ``_go_short``. Failing this means a new
    strategy was added without aligning it with the gate; audit it."""

    EXPECTED_BRACKET_STRATEGIES = {
        "supertrend.py",
        "donchian_breakout.py",
        "rsi_mean_reversion.py",
        "bollinger_mean_reversion.py",
        "orb.py",
    }

    EXPECTED_NON_BRACKET_STRATEGIES = {
        "ma_crossover.py",
    }

    def test_bracket_strategies_use_mixin_helper(self) -> None:
        """Every bracket strategy goes through ``_submit_bracket_for_entry``."""
        for fname in self.EXPECTED_BRACKET_STRATEGIES:
            path = STRATEGIES_DIR / fname
            text = path.read_text(encoding="utf-8")
            assert "_submit_bracket_for_entry" in text, (
                f"{fname} should route entries through "
                "``_submit_bracket_for_entry`` (BracketStrategyMixin)"
            )

    def test_non_bracket_strategies_use_submit_order(self) -> None:
        """Strategies without ATR brackets use the simpler submit_order path."""
        for fname in self.EXPECTED_NON_BRACKET_STRATEGIES:
            path = STRATEGIES_DIR / fname
            tree = ast.parse(path.read_text(encoding="utf-8"))
            # At least one ``self.submit_order(order)`` call.
            calls = _attribute_calls(tree, "submit_order")
            assert calls, (
                f"{fname} should submit orders via ``self.submit_order(...)``"
            )
