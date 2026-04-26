"""Prop-firm preset loader — single source of truth for backtest thresholds.

Rule-engine rules (Epic 4) and backtest metrics (Epic 8) both need the
same prop-firm thresholds (e.g. FTMO: daily loss 5%, max DD 10%, profit
target 10%, min trading days 4). Having the two code paths carry their
own hard-coded defaults silently diverges from the live rule engine —
per ``.claude/rules/common/sandboxed-domain.md`` these thresholds MUST
come from the preset YAML. This module loads the preset once and exposes
a frozen :class:`PropFirmPreset` that both layers can read.

Design:
- Input YAML: ``src/rules/presets/<firm>.yaml`` (default: ``ftmo.yaml``).
- Only the numeric thresholds are extracted here. Full rule construction
  stays in the rule engine's :mod:`src.rules.preset_loader` to avoid
  duplicating validation logic.

Epic 9 note: this preset-oriented loader coexists with the new
:class:`FirmRegistry` (Epic 9 P0.2) during migration. Once P0.11 finishes
moving presets into ``configs/firms/*.yaml``, this module becomes a thin
adapter over the firm profile's product thresholds.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


# Default location of the prop-firm rules YAML relative to the repo root.
DEFAULT_PROP_FIRM_PRESET_PATH = (
    Path(__file__).resolve().parent.parent / "rules" / "presets" / "ftmo.yaml"
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
            ``src/rules/presets/ftmo.yaml``.

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
