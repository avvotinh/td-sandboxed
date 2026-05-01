"""Tests for the migration audit (story 10.11).

Pure-function audit + the typer CLI command. The CLI tests use a
temporary ``configs/accounts.yaml`` written through ``ACCOUNTS_CONFIG``
so the production config is not required.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from src.accounts.audit_rules_source import (
    AccountAuditRow,
    classify_account,
    classify_accounts,
)
from src.accounts.models import AccountConfig, AccountType, MT5Config
from src.cli.accounts import accounts_app


# -------------------------------------------------------------------------
# Fixtures
# -------------------------------------------------------------------------


def _mt5() -> MT5Config:
    return MT5Config(
        server="MT5-Server", login=12345678, password_env="X_PASS"
    )


def _firm_bound(account_id: str = "firm-001") -> AccountConfig:
    return AccountConfig(
        id=account_id,
        name="Firm Bound",
        type=AccountType.PROP_FIRM,
        firm_id="ftmo",
        product_id="challenge",
        phase="evaluation",
        mt5=_mt5(),
        strategy="ma_crossover",
    )


def _personal(account_id: str = "personal-001") -> AccountConfig:
    return AccountConfig(
        id=account_id,
        name="Personal",
        type=AccountType.PERSONAL,
        rules_file="configs/personal.yaml",
        mt5=_mt5(),
        strategy="ma_crossover",
    )


def _demo(account_id: str = "demo-001") -> AccountConfig:
    return AccountConfig(
        id=account_id,
        name="Demo",
        type=AccountType.DEMO,
        mt5=_mt5(),
        strategy="ma_crossover",
    )


# -------------------------------------------------------------------------
# classify_account — single account
# -------------------------------------------------------------------------


class TestClassifyAccount:
    def test_firm_bound(self) -> None:
        row = classify_account(_firm_bound())
        assert row.rules_source == "firm_bound"
        assert row.firm_id == "ftmo"
        assert row.product_id == "challenge"
        assert row.phase == "evaluation"

    def test_personal_rules_file(self) -> None:
        row = classify_account(_personal())
        assert row.rules_source == "personal_rules_file"
        assert row.rules_file == "configs/personal.yaml"

    def test_demo_classified_as_none(self) -> None:
        row = classify_account(_demo())
        assert row.rules_source == "none"

    def test_account_type_propagated(self) -> None:
        assert classify_account(_firm_bound()).account_type == "prop_firm"
        assert classify_account(_personal()).account_type == "personal"
        assert classify_account(_demo()).account_type == "demo"


# -------------------------------------------------------------------------
# classify_accounts — aggregate
# -------------------------------------------------------------------------


class TestClassifyAccounts:
    def test_mixed_roster_aggregates_correctly(self) -> None:
        report = classify_accounts(
            [
                _firm_bound("firm-a"),
                _firm_bound("firm-b"),
                _personal("personal-a"),
                _demo("demo-a"),
            ]
        )
        assert report.counts == {
            "firm_bound": 2,
            "personal_rules_file": 1,
            "none": 1,
        }
        assert report.prop_firm_account_total == 2
        assert report.prop_firm_legacy_count == 0
        assert report.all_prop_firm_accounts_migrated is True

    def test_all_firm_bound_passes_strict_check(self) -> None:
        report = classify_accounts(
            [_firm_bound("a"), _firm_bound("b"), _personal("p")]
        )
        assert report.prop_firm_legacy_count == 0
        assert report.all_prop_firm_accounts_migrated is True

    def test_no_prop_firm_accounts_at_all(self) -> None:
        # Personal + demo only — vacuously "migrated"
        report = classify_accounts([_personal("p"), _demo("d")])
        assert report.prop_firm_account_total == 0
        assert report.prop_firm_legacy_count == 0
        assert report.all_prop_firm_accounts_migrated is True

    def test_empty_roster(self) -> None:
        report = classify_accounts([])
        assert report.rows == ()
        assert all(v == 0 for v in report.counts.values())
        assert report.all_prop_firm_accounts_migrated is True

    def test_row_order_preserved(self) -> None:
        order = ["a", "b", "c"]
        report = classify_accounts(
            [
                _firm_bound(order[0]),
                _personal(order[1]),
                _demo(order[2]),
            ]
        )
        assert [r.account_id for r in report.rows] == order


# -------------------------------------------------------------------------
# Serialisation
# -------------------------------------------------------------------------


class TestSerialisation:
    def test_to_table_row_firm_bound(self) -> None:
        row = classify_account(_firm_bound("acct-1"))
        rendered = row.to_table_row()
        assert rendered == ("acct-1", "prop_firm", "firm_bound", "ftmo/challenge/evaluation")

    def test_to_table_row_personal(self) -> None:
        row = classify_account(_personal("acct-3"))
        assert row.to_table_row() == (
            "acct-3",
            "personal",
            "personal_rules_file",
            "configs/personal.yaml",
        )

    def test_to_table_row_none(self) -> None:
        row = classify_account(_demo("acct-4"))
        assert row.to_table_row() == ("acct-4", "demo", "none", "")

    def test_report_to_dict_round_trips_through_json(self) -> None:
        report = classify_accounts([_firm_bound("a"), _personal("b")])
        payload = json.dumps(report.to_dict())
        decoded = json.loads(payload)
        assert decoded["counts"]["firm_bound"] == 1
        assert decoded["counts"]["personal_rules_file"] == 1
        assert decoded["all_prop_firm_accounts_migrated"] is True
        assert len(decoded["rows"]) == 2


# -------------------------------------------------------------------------
# CLI
# -------------------------------------------------------------------------


def _write_accounts_yaml(
    tmp_path: Path, *, accounts: list[dict[str, Any]]
) -> Path:
    """Write a minimal accounts.yaml; returns the path."""
    cfg = {"accounts": accounts}
    path = tmp_path / "accounts.yaml"
    path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
    return path


def _yaml_account(
    account_id: str,
    *,
    type_: str,
    firm_id: str | None = None,
    product_id: str | None = None,
    phase: str | None = None,
    rules_file: str | None = None,
) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": account_id,
        "name": account_id,
        "type": type_,
        "mt5": {"server": "Test", "login": 12345678, "password_env": "X"},
        "strategy": "ma_crossover",
    }
    if firm_id is not None:
        entry["firm_id"] = firm_id
    if product_id is not None:
        entry["product_id"] = product_id
    if phase is not None:
        entry["phase"] = phase
    if rules_file is not None:
        entry["rules_file"] = rules_file
    return entry


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


class TestCli:
    def test_table_output_lists_every_account(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        cfg = _write_accounts_yaml(
            tmp_path,
            accounts=[
                _yaml_account(
                    "firm-a",
                    type_="prop_firm",
                    firm_id="ftmo",
                    product_id="challenge",
                    phase="evaluation",
                ),
                _yaml_account(
                    "personal-a",
                    type_="personal",
                    rules_file="configs/custom.yaml",
                ),
            ],
        )
        monkeypatch.setenv("ACCOUNTS_CONFIG", str(cfg))

        result = runner.invoke(accounts_app, ["audit-rules-source"])
        assert result.exit_code == 0, result.output
        assert "firm-a" in result.output
        assert "personal-a" in result.output
        assert "firm_bound" in result.output
        assert "personal_rules_file" in result.output

    def test_strict_exits_zero_when_all_firm_bound(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        cfg = _write_accounts_yaml(
            tmp_path,
            accounts=[
                _yaml_account(
                    "firm-a",
                    type_="prop_firm",
                    firm_id="ftmo",
                    product_id="challenge",
                    phase="evaluation",
                ),
            ],
        )
        monkeypatch.setenv("ACCOUNTS_CONFIG", str(cfg))

        result = runner.invoke(
            accounts_app, ["audit-rules-source", "--strict"]
        )
        assert result.exit_code == 0, result.output
        assert "Phase 5 cleanup unblocked" in result.output

    def test_strict_exits_zero_with_only_firm_and_personal_accounts(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        """Story 10.12 — the legacy preset path was removed, so
        ``--strict`` can no longer fail on it. Mixed firm + personal
        rosters all pass.
        """
        cfg = _write_accounts_yaml(
            tmp_path,
            accounts=[
                _yaml_account(
                    "firm-a",
                    type_="prop_firm",
                    firm_id="ftmo",
                    product_id="challenge",
                    phase="evaluation",
                ),
                _yaml_account(
                    "personal-a",
                    type_="personal",
                    rules_file="configs/custom.yaml",
                ),
            ],
        )
        monkeypatch.setenv("ACCOUNTS_CONFIG", str(cfg))

        result = runner.invoke(
            accounts_app, ["audit-rules-source", "--strict"]
        )
        assert result.exit_code == 0, result.output

    def test_json_output_is_valid_json(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        cfg = _write_accounts_yaml(
            tmp_path,
            accounts=[
                _yaml_account(
                    "firm-a",
                    type_="prop_firm",
                    firm_id="ftmo",
                    product_id="challenge",
                    phase="evaluation",
                ),
            ],
        )
        monkeypatch.setenv("ACCOUNTS_CONFIG", str(cfg))

        result = runner.invoke(
            accounts_app, ["audit-rules-source", "--json"]
        )
        assert result.exit_code == 0, result.output
        decoded = json.loads(result.output)
        assert decoded["all_prop_firm_accounts_migrated"] is True
        assert decoded["rows"][0]["rules_source"] == "firm_bound"

    def test_missing_config_exits_one_with_clear_error(
        self, tmp_path: Path, runner: CliRunner, monkeypatch
    ) -> None:
        monkeypatch.setenv("ACCOUNTS_CONFIG", str(tmp_path / "missing.yaml"))
        result = runner.invoke(accounts_app, ["audit-rules-source"])
        assert result.exit_code == 1
        assert "not found" in result.output.lower()


# -------------------------------------------------------------------------
# Frozen-dataclass invariants
# -------------------------------------------------------------------------


class TestImmutability:
    def test_audit_row_frozen(self) -> None:
        from dataclasses import FrozenInstanceError

        row = classify_account(_firm_bound())
        with pytest.raises(FrozenInstanceError):
            row.account_id = "mutated"  # type: ignore[misc]

    def test_audit_row_is_typed_dataclass(self) -> None:
        # AccountAuditRow is the public type; round-trip through dict
        row = AccountAuditRow(
            account_id="x",
            account_type="prop_firm",
            rules_source="firm_bound",
            firm_id="ftmo",
            product_id="challenge",
            phase="evaluation",
        )
        assert row.account_id == "x"
        assert row.rules_source == "firm_bound"
