"""Audit accounts' rule-source assignment for Phase 5 cleanup gating.

Story 10.11 — :func:`classify_accounts` walks every account in
``configs/accounts.yaml`` and reports how its rules are sourced. Phase 5
(stories 10.12–10.14) drops the legacy ``prop_firm`` field, the legacy
preset YAML loader, and the legacy ``prop_firm_id`` schema; that work
cannot land while any production account still uses the legacy preset
path. This audit produces the per-account roster + aggregate that ops
sign off on before Phase 5 unlocks.

Output labels are stable contract:

- ``firm_bound``         — Epic 9+ ``firm_id`` + ``product_id`` + ``phase``.
- ``preset_legacy``      — legacy ``prop_firm`` field.
- ``personal_rules_file``— ``rules_file`` (custom rules path).
- ``none``               — demo / no rules.

Pure function — no Redis, no database. CLI wraps it.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Literal

from ..rules.assignment import RuleAssignment

if False:  # for type checkers — avoids the import cycle on src.accounts.models
    from .models import AccountConfig


RulesSource = Literal[
    "firm_bound",
    "preset_legacy",
    "personal_rules_file",
    "none",
]


# RuleAssignment.assignment_type → public-facing audit label.
_LABEL_BY_ASSIGNMENT_TYPE: dict[str, RulesSource] = {
    "firm": "firm_bound",
    "preset": "preset_legacy",
    "personal": "personal_rules_file",
    "none": "none",
}


@dataclass(frozen=True)
class AccountAuditRow:
    """One account's classification row.

    Attributes:
        account_id: ``AccountConfig.id``.
        account_type: Raw ``AccountConfig.type`` value (``prop_firm`` /
            ``personal`` / ``demo``).
        rules_source: Public audit label (see :data:`RulesSource`).
        firm_id: Set only when ``rules_source == "firm_bound"``.
        product_id: Set only when ``rules_source == "firm_bound"``.
        phase: Set only when ``rules_source == "firm_bound"``.
        preset_name: Set only when ``rules_source == "preset_legacy"``.
        rules_file: Set only when ``rules_source == "personal_rules_file"``.
    """

    account_id: str
    account_type: str
    rules_source: RulesSource
    firm_id: str | None = None
    product_id: str | None = None
    phase: str | None = None
    preset_name: str | None = None
    rules_file: str | None = None

    def to_table_row(self) -> tuple[str, str, str, str]:
        """Render as a 4-column table row: id / type / source / detail."""
        if self.rules_source == "firm_bound":
            detail = f"{self.firm_id}/{self.product_id}/{self.phase}"
        elif self.rules_source == "preset_legacy":
            detail = self.preset_name or ""
        elif self.rules_source == "personal_rules_file":
            detail = self.rules_file or ""
        else:
            detail = ""
        return (
            self.account_id,
            self.account_type,
            self.rules_source,
            detail,
        )

    def to_dict(self) -> dict:
        """Render as a JSON-serialisable dict."""
        return {
            "account_id": self.account_id,
            "account_type": self.account_type,
            "rules_source": self.rules_source,
            "firm_id": self.firm_id,
            "product_id": self.product_id,
            "phase": self.phase,
            "preset_name": self.preset_name,
            "rules_file": self.rules_file,
        }


@dataclass(frozen=True)
class RulesSourceAuditReport:
    """Per-account rows + aggregate counts.

    Attributes:
        rows: One :class:`AccountAuditRow` per account, in input order.
        counts: Aggregate count per :data:`RulesSource` label.
        prop_firm_account_total: Number of ``AccountType.PROP_FIRM`` rows
            in the report. Used by ``--strict`` to decide pass / fail.
        prop_firm_legacy_count: Number of prop-firm accounts whose
            ``rules_source`` is still ``preset_legacy``. Phase 5 may not
            land while this is non-zero.
    """

    rows: tuple[AccountAuditRow, ...]
    counts: dict[RulesSource, int]
    prop_firm_account_total: int
    prop_firm_legacy_count: int

    @property
    def all_prop_firm_accounts_migrated(self) -> bool:
        """True when zero prop-firm accounts remain on the legacy path."""
        return self.prop_firm_legacy_count == 0

    def to_dict(self) -> dict:
        """Render as a JSON-serialisable dict."""
        return {
            "rows": [r.to_dict() for r in self.rows],
            "counts": dict(self.counts),
            "prop_firm_account_total": self.prop_firm_account_total,
            "prop_firm_legacy_count": self.prop_firm_legacy_count,
            "all_prop_firm_accounts_migrated": self.all_prop_firm_accounts_migrated,
        }


def classify_account(account: "AccountConfig") -> AccountAuditRow:
    """Classify a single account's rule source.

    Delegates to :class:`RuleAssignment.from_account_config` so the
    audit and the runtime resolver agree on every edge case (firm
    binding precedence, demo accounts, etc.).
    """
    assignment = RuleAssignment.from_account_config(account)
    label = _LABEL_BY_ASSIGNMENT_TYPE[assignment.assignment_type]
    return AccountAuditRow(
        account_id=account.id,
        account_type=account.type.value if hasattr(account.type, "value") else str(account.type),
        rules_source=label,
        firm_id=assignment.firm_id,
        product_id=assignment.product_id,
        phase=assignment.phase,
        preset_name=assignment.preset_name,
        rules_file=assignment.rules_file,
    )


def classify_accounts(
    accounts: Iterable["AccountConfig"],
) -> RulesSourceAuditReport:
    """Classify a collection of accounts; return the full audit report."""
    from .models import AccountType

    rows: list[AccountAuditRow] = []
    counts: dict[RulesSource, int] = {
        "firm_bound": 0,
        "preset_legacy": 0,
        "personal_rules_file": 0,
        "none": 0,
    }
    prop_firm_total = 0
    prop_firm_legacy = 0

    for account in accounts:
        row = classify_account(account)
        rows.append(row)
        counts[row.rules_source] += 1
        if account.type == AccountType.PROP_FIRM:
            prop_firm_total += 1
            if row.rules_source == "preset_legacy":
                prop_firm_legacy += 1

    return RulesSourceAuditReport(
        rows=tuple(rows),
        counts=counts,
        prop_firm_account_total=prop_firm_total,
        prop_firm_legacy_count=prop_firm_legacy,
    )
