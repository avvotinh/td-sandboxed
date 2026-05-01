"""Static checks on the Alembic revision chain (story 10.10).

These tests do not connect to a database — they verify that the
revision graph is structurally sound and that each ported revision
contains the SQL we expect. End-to-end ``alembic upgrade head`` on a
real TimescaleDB lives in the integration suite.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory


REPO_ROOT = Path(__file__).resolve().parents[3]
ALEMBIC_INI = REPO_ROOT / "alembic.ini"

# Ordered list of revision IDs as ported from the raw-SQL files.
EXPECTED_CHAIN = [
    "005_state_snapshots",
    "006_trades_strategy_index",
    "007_audit_retention_and_aggregate",
    "008_violations_retention_and_aggregate",
    "009_multi_firm_account_binding",
    "010_rename_ftmo_audit_events",
]


@pytest.fixture(scope="module")
def script_directory() -> ScriptDirectory:
    cfg = Config(str(ALEMBIC_INI))
    cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
    return ScriptDirectory.from_config(cfg)


# -------------------------------------------------------------------------
# Chain integrity
# -------------------------------------------------------------------------


class TestChain:
    def test_head_is_010(self, script_directory: ScriptDirectory) -> None:
        heads = list(script_directory.get_heads())
        assert heads == ["010_rename_ftmo_audit_events"], heads

    def test_chain_in_expected_order(
        self, script_directory: ScriptDirectory
    ) -> None:
        # Walk from base → head; revisions must match EXPECTED_CHAIN exactly.
        revisions = list(script_directory.walk_revisions())
        # walk_revisions returns head → base, reverse for ascending compare.
        chain = [rev.revision for rev in reversed(revisions)]
        assert chain == EXPECTED_CHAIN

    def test_005_has_no_down_revision(
        self, script_directory: ScriptDirectory
    ) -> None:
        rev = script_directory.get_revision("005_state_snapshots")
        assert rev.down_revision is None

    @pytest.mark.parametrize(
        "rev_id,expected_down",
        list(zip(EXPECTED_CHAIN[1:], EXPECTED_CHAIN[:-1])),
    )
    def test_each_revision_points_to_predecessor(
        self,
        script_directory: ScriptDirectory,
        rev_id: str,
        expected_down: str,
    ) -> None:
        rev = script_directory.get_revision(rev_id)
        assert rev.down_revision == expected_down


# -------------------------------------------------------------------------
# Per-revision content
# -------------------------------------------------------------------------


class TestRevisionContent:
    """Spot-check each revision references the right table / DDL.

    Catches accidental rename / merge-conflict drift between the raw-SQL
    file in ``infra/timescaledb/migrations/`` and the Alembic port.
    """

    @pytest.mark.parametrize(
        "rev_id,expected_substrings",
        [
            (
                "005_state_snapshots",
                ["state_snapshots", "create_hypertable", "add_retention_policy"],
            ),
            (
                "006_trades_strategy_index",
                ["idx_trades_strategy", "trades", "strategy_name"],
            ),
            (
                "007_audit_retention_and_aggregate",
                [
                    "audit_logs",
                    "audit_daily_summary",
                    "add_retention_policy",
                    "add_continuous_aggregate_policy",
                    "add_compression_policy",
                ],
            ),
            (
                "008_violations_retention_and_aggregate",
                [
                    "rule_violations",
                    "violation_daily_summary",
                    "add_retention_policy",
                    "add_continuous_aggregate_policy",
                    "add_compression_policy",
                ],
            ),
            (
                "009_multi_firm_account_binding",
                [
                    "firm_id",
                    "product_id",
                    "phase",
                    "rule_overrides",
                    "accounts_firm_binding_consistent",
                    "accounts_rule_overrides_scope",
                    "ix_accounts_firm_product_phase",
                ],
            ),
            (
                "010_rename_ftmo_audit_events",
                ["audit_logs", "ftmo_", "prop_firm_", "REPLACE"],
            ),
        ],
    )
    def test_revision_text_contains(
        self,
        script_directory: ScriptDirectory,
        rev_id: str,
        expected_substrings: list[str],
    ) -> None:
        path = Path(script_directory.get_revision(rev_id).path)
        text = path.read_text(encoding="utf-8")
        for needle in expected_substrings:
            assert needle in text, (
                f"{rev_id} missing expected substring {needle!r}"
            )

    def test_005_downgrade_raises_not_implemented(
        self, script_directory: ScriptDirectory
    ) -> None:
        path = Path(
            script_directory.get_revision("005_state_snapshots").path
        )
        text = path.read_text(encoding="utf-8")
        # Drop of the hypertable would lose audit-trail data; the port
        # explicitly refuses silent downgrade.
        assert "raise NotImplementedError" in text

    def test_010_downgrade_raises_not_implemented(
        self, script_directory: ScriptDirectory
    ) -> None:
        path = Path(
            script_directory.get_revision("010_rename_ftmo_audit_events").path
        )
        text = path.read_text(encoding="utf-8")
        assert "raise NotImplementedError" in text


# -------------------------------------------------------------------------
# Source-of-truth parity with the original raw-SQL files
# -------------------------------------------------------------------------


class TestRawSqlParity:
    """Each Alembic revision must reference the same hypertables /
    materialized views / constraints as its raw-SQL ancestor in
    ``infra/timescaledb/migrations/``. We don't byte-compare (the
    Alembic port adds ``if_not_exists`` guards and minor formatting),
    just check the canonical identifiers survive."""

    @pytest.mark.parametrize(
        "rev_id,sql_file,identifiers",
        [
            (
                "005_state_snapshots",
                "005_state_snapshots.sql",
                ["state_snapshots", "fk_state_snapshots_account"],
            ),
            (
                "006_trades_strategy_index",
                "006_add_trades_strategy_index.sql",
                ["idx_trades_strategy"],
            ),
            (
                "007_audit_retention_and_aggregate",
                "007_audit_retention_and_aggregate.sql",
                ["audit_daily_summary"],
            ),
            (
                "008_violations_retention_and_aggregate",
                "008_violations_retention_and_aggregate.sql",
                ["violation_daily_summary"],
            ),
            (
                "009_multi_firm_account_binding",
                "009_multi_firm_account_binding.sql",
                [
                    "accounts_firm_binding_consistent",
                    "accounts_rule_overrides_scope",
                    "ix_accounts_firm_product_phase",
                ],
            ),
            (
                "010_rename_ftmo_audit_events",
                "010_rename_ftmo_audit_events.sql",
                ["timescaledb_information.chunks"],
            ),
        ],
    )
    def test_identifiers_present_in_both(
        self,
        script_directory: ScriptDirectory,
        rev_id: str,
        sql_file: str,
        identifiers: list[str],
    ) -> None:
        py_path = Path(script_directory.get_revision(rev_id).path)
        py_text = py_path.read_text(encoding="utf-8")

        sql_path = REPO_ROOT.parent.parent / "infra" / "timescaledb" / "migrations" / sql_file
        if not sql_path.exists():  # repo layout differs in CI
            pytest.skip(f"raw SQL file missing at {sql_path}")
        sql_text = sql_path.read_text(encoding="utf-8")

        for ident in identifiers:
            assert ident in sql_text, (
                f"raw SQL {sql_file} unexpectedly missing {ident!r}"
            )
            assert ident in py_text, (
                f"alembic revision {rev_id} missing identifier {ident!r} "
                "from raw SQL — port drift?"
            )


# -------------------------------------------------------------------------
# alembic.ini sanity
# -------------------------------------------------------------------------


class TestAlembicIni:
    def test_script_location_resolves(self) -> None:
        cfg = Config(str(ALEMBIC_INI))
        cfg.set_main_option("script_location", str(REPO_ROOT / "alembic"))
        # Constructing the ScriptDirectory parses every revision.
        ScriptDirectory.from_config(cfg)

    def test_sqlalchemy_url_left_blank_for_env_resolution(self) -> None:
        # The URL is intentionally blank so env.py reads ``DATABASE_URL``.
        text = ALEMBIC_INI.read_text(encoding="utf-8")
        assert re.search(r"^sqlalchemy\.url\s*=\s*$", text, re.MULTILINE), (
            "alembic.ini should leave sqlalchemy.url blank — env.py "
            "resolves it from DATABASE_URL"
        )
