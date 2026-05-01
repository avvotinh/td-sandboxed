"""Prop-firm preset loader — backtest-only threshold reader.

The backtest's metrics layer needs prop-firm thresholds (FTMO: daily
loss 5%, max DD 10%, profit target 10%, min trading days 4) for
informational scoring during simulation. Story 10.13 dropped the rule
engine's preset loader and the live ``AccountConfig.prop_firm`` field;
the YAMLs were relocated to :mod:`src.backtesting.presets` for backtest
use only.

Future migration (tracked separately): port these thresholds into
``configs/firms/<firm>.yaml`` so backtest reads from the same source as
live, and delete this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# Default location of the prop-firm rules YAML — backtest-local presets
# directory introduced in story 10.13.
DEFAULT_PROP_FIRM_PRESET_PATH = (
    Path(__file__).resolve().parent / "presets" / "ftmo.yaml"
)


@dataclass(frozen=True)
class PropFirmPreset:
    """Frozen view of prop-firm thresholds needed by backtest metrics.

    Attributes:
        name: Human-readable preset name ("FTMO Challenge", "The5ers Bootstrap").
        daily_loss_pct: Daily-loss block threshold (5.0 = 5%).
        max_drawdown_pct: Trailing max-DD block threshold (10.0 = 10%).
        profit_target_pct: Informational profit target (10.0 = 10%).
        min_trading_days: Minimum trading days required.
        max_position_lots: Base max lot cap before account scaling.
    """

    name: str
    daily_loss_pct: float
    max_drawdown_pct: float
    profit_target_pct: float
    min_trading_days: int
    max_position_lots: float


def load_prop_firm_preset(path: Path | None = None) -> PropFirmPreset:
    """Parse a prop-firm preset YAML into a frozen :class:`PropFirmPreset`.

    Args:
        path: Override preset file. Defaults to
            ``src/backtesting/presets/ftmo.yaml``.

    Raises:
        FileNotFoundError: Preset file missing.
        ValueError: Required rule types absent from the YAML.
    """
    resolved = Path(path) if path is not None else DEFAULT_PROP_FIRM_PRESET_PATH
    if not resolved.exists():
        raise FileNotFoundError(f"Prop-firm preset not found: {resolved}")

    data: dict[str, Any] = yaml.safe_load(resolved.read_text())
    rules = {r["type"]: r for r in data.get("rules", [])}

    def _require(rule_type: str) -> dict[str, Any]:
        rule = rules.get(rule_type)
        if rule is None:
            raise ValueError(f"{resolved}: missing required rule type {rule_type!r}")
        return rule

    daily = _require("daily_loss_limit")
    dd = _require("max_drawdown")
    profit = _require("profit_target")
    min_days = _require("min_trading_days")
    max_pos = _require("max_position_size")

    return PropFirmPreset(
        name=data.get("name", "Prop Firm"),
        daily_loss_pct=float(daily["threshold_percent"]),
        max_drawdown_pct=float(dd["threshold_percent"]),
        profit_target_pct=float(profit["threshold_percent"]),
        min_trading_days=int(min_days.get("required_days", 4)),
        max_position_lots=float(max_pos.get("max_lots", 100.0)),
    )
