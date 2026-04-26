"""Tests for CLI accounts commands using Typer testing utilities."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


@pytest.fixture
def mock_account_manager():
    """Create a mock AccountManager."""
    manager = MagicMock()
    manager.start_account = AsyncMock()
    manager.stop_account = AsyncMock()
    manager.pause_account = AsyncMock()
    manager.resume_account = AsyncMock()
    manager.get_account_status = AsyncMock(return_value="active")
    manager.get_all_statuses = AsyncMock(
        return_value={
            "test-001": "active",
            "test-002": "paused",
        }
    )
    manager._validate_account_exists = MagicMock()
    manager.close = AsyncMock()
    return manager


@pytest.fixture
def mock_get_account_manager(mock_account_manager):
    """Patch _get_account_manager to return mock."""
    with patch(
        "src.cli.accounts._get_account_manager",
        return_value=mock_account_manager,
    ):
        yield mock_account_manager


class TestAccountsHelp:
    """Tests for accounts help command."""

    def test_accounts_help(self):
        """Test accounts --help shows subcommands."""
        result = runner.invoke(app, ["accounts", "--help"])
        assert result.exit_code == 0
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "pause" in result.stdout
        assert "resume" in result.stdout
        assert "status" in result.stdout


class TestAccountsStart:
    """Tests for accounts start command."""

    def test_start_account_success(self, mock_get_account_manager):
        """Test starting account successfully."""
        result = runner.invoke(app, ["accounts", "start", "test-001"])

        assert result.exit_code == 0
        assert "started" in result.stdout
        mock_get_account_manager.start_account.assert_called_once()

    def test_start_account_error(self, mock_get_account_manager):
        """Test starting account with error."""
        mock_get_account_manager.start_account.side_effect = ValueError(
            "Cannot transition"
        )

        result = runner.invoke(app, ["accounts", "start", "test-001"])

        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_start_requires_account_id(self):
        """Test start requires account_id argument."""
        result = runner.invoke(app, ["accounts", "start"])
        assert result.exit_code != 0


class TestAccountsStop:
    """Tests for accounts stop command."""

    def test_stop_account_with_force(self, mock_get_account_manager):
        """Test stopping account with --force flag."""
        result = runner.invoke(app, ["accounts", "stop", "test-001", "--force"])

        assert result.exit_code == 0
        assert "stopped" in result.stdout
        mock_get_account_manager.stop_account.assert_called_once()

    def test_stop_account_confirms(self, mock_get_account_manager):
        """Test stopping account prompts for confirmation."""
        result = runner.invoke(app, ["accounts", "stop", "test-001"], input="y\n")

        assert result.exit_code == 0
        mock_get_account_manager.stop_account.assert_called_once()

    def test_stop_account_abort(self, mock_get_account_manager):
        """Test stopping account can be aborted."""
        result = runner.invoke(app, ["accounts", "stop", "test-001"], input="n\n")

        assert result.exit_code == 1  # Aborted
        mock_get_account_manager.stop_account.assert_not_called()

    def test_stop_account_error(self, mock_get_account_manager):
        """Test stopping account with error."""
        mock_get_account_manager.stop_account.side_effect = ValueError(
            "Account not found"
        )

        result = runner.invoke(app, ["accounts", "stop", "test-001", "-f"])

        assert result.exit_code == 1
        assert "Error" in result.stdout


class TestAccountsPause:
    """Tests for accounts pause command."""

    def test_pause_account_success(self, mock_get_account_manager):
        """Test pausing account successfully."""
        result = runner.invoke(app, ["accounts", "pause", "test-001"])

        assert result.exit_code == 0
        assert "paused" in result.stdout
        mock_get_account_manager.pause_account.assert_called_once()

    def test_pause_account_error(self, mock_get_account_manager):
        """Test pausing account with error."""
        mock_get_account_manager.pause_account.side_effect = ValueError(
            "Cannot transition"
        )

        result = runner.invoke(app, ["accounts", "pause", "test-001"])

        assert result.exit_code == 1
        assert "Error" in result.stdout


class TestAccountsResume:
    """Tests for accounts resume command."""

    def test_resume_account_success(self, mock_get_account_manager):
        """Test resuming account successfully."""
        result = runner.invoke(app, ["accounts", "resume", "test-001"])

        assert result.exit_code == 0
        assert "resumed" in result.stdout
        mock_get_account_manager.resume_account.assert_called_once()

    def test_resume_account_error(self, mock_get_account_manager):
        """Test resuming account with error."""
        mock_get_account_manager.resume_account.side_effect = ValueError("not paused")

        result = runner.invoke(app, ["accounts", "resume", "test-001"])

        assert result.exit_code == 1
        assert "Error" in result.stdout


class TestAccountsStatus:
    """Tests for accounts status command (detailed single-account view)."""

    def test_status_requires_account_id(self):
        """Test that status command requires an account_id argument."""
        result = runner.invoke(app, ["accounts", "status"])
        # Should fail due to missing required argument
        assert result.exit_code == 2
        # Error message may be in stdout or combined output
        output = result.stdout + (result.output if hasattr(result, "output") else "")
        assert "Missing argument" in output or "Usage:" in output or result.exit_code == 2

    def test_status_specific_account(self):
        """Test getting detailed status of specific account."""
        from decimal import Decimal
        from unittest.mock import MagicMock

        mock_metrics = MagicMock()
        mock_metrics.account_id = "test-001"
        mock_metrics.account_name = "Test Account"
        mock_metrics.status = "active"
        mock_metrics.daily_pnl = Decimal("100")
        mock_metrics.to_status_dict.return_value = {
            "account_id": "test-001",
            "account_name": "Test Account",
            "status": "active",
            "balance": "$100,000.00",
            "equity": "$100,100.00",
            "daily_pnl": "$100.00 (+0.1%)",
            "max_drawdown": "0.0%",
            "peak_equity": "$100,100.00",
        }

        with patch("src.cli.accounts.RedisStateManager") as mock_redis_cls:
            mock_redis = MagicMock()
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis_cls.return_value = mock_redis

            with patch("src.cli.accounts.ConfigLoader") as mock_loader:
                mock_config = MagicMock()
                mock_loader.return_value.load.return_value = mock_config

                with patch("src.cli.accounts.AccountManager") as mock_manager_cls:
                    mock_manager = MagicMock()
                    mock_manager_cls.return_value = mock_manager

                    with patch("src.cli.accounts._get_metrics_service") as mock_get_service:
                        mock_service = MagicMock()
                        mock_service.get_account_metrics = AsyncMock(
                            return_value=mock_metrics
                        )
                        mock_get_service.return_value = mock_service

                        result = runner.invoke(
                            app, ["accounts", "status", "test-001"]
                        )

                        assert result.exit_code == 0
                        assert "test-001" in result.stdout
                        assert "active" in result.stdout

    def test_status_nonexistent_account(self):
        """Test getting status of nonexistent account."""
        with patch("src.cli.accounts.RedisStateManager") as mock_redis_cls:
            mock_redis = MagicMock()
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis_cls.return_value = mock_redis

            with patch("src.cli.accounts.ConfigLoader") as mock_loader:
                mock_config = MagicMock()
                mock_loader.return_value.load.return_value = mock_config

                with patch("src.cli.accounts.AccountManager") as mock_manager_cls:
                    mock_manager = MagicMock()
                    mock_manager_cls.return_value = mock_manager

                    with patch("src.cli.accounts._get_metrics_service") as mock_get_service:
                        mock_service = MagicMock()
                        mock_service.get_account_metrics = AsyncMock(return_value=None)
                        mock_get_service.return_value = mock_service

                        result = runner.invoke(
                            app, ["accounts", "status", "nonexistent"]
                        )

                        assert result.exit_code == 1
                        assert "not found" in result.stdout.lower()


class TestAccountsList:
    """Tests for accounts list command (summary table view)."""

    def test_list_all_accounts(self):
        """Test listing all accounts with summary metrics."""
        from decimal import Decimal
        from unittest.mock import MagicMock

        mock_metrics_a = MagicMock()
        mock_metrics_a.account_id = "test-001"
        mock_metrics_a.account_name = "Test One"
        mock_metrics_a.status = "active"
        mock_metrics_a.balance = Decimal("100000")
        mock_metrics_a.to_list_row.return_value = [
            "test-001",
            "Test One",
            "active",
            "$100,000.00",
            "+0.5%",
        ]

        mock_metrics_b = MagicMock()
        mock_metrics_b.account_id = "test-002"
        mock_metrics_b.account_name = "Test Two"
        mock_metrics_b.status = "paused"
        mock_metrics_b.balance = Decimal("50000")
        mock_metrics_b.to_list_row.return_value = [
            "test-002",
            "Test Two",
            "paused",
            "$50,000.00",
            "-1.0%",
        ]

        with patch("src.cli.accounts.RedisStateManager") as mock_redis_cls:
            mock_redis = MagicMock()
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis_cls.return_value = mock_redis

            with patch("src.cli.accounts.ConfigLoader") as mock_loader:
                mock_config = MagicMock()
                mock_loader.return_value.load.return_value = mock_config

                with patch("src.cli.accounts.AccountManager") as mock_manager_cls:
                    mock_manager = MagicMock()
                    mock_manager_cls.return_value = mock_manager

                    with patch("src.cli.accounts._get_metrics_service") as mock_get_service:
                        mock_service = MagicMock()
                        mock_service.get_all_account_metrics = AsyncMock(
                            return_value={
                                "test-001": mock_metrics_a,
                                "test-002": mock_metrics_b,
                            }
                        )
                        mock_get_service.return_value = mock_service

                        result = runner.invoke(app, ["accounts", "list"])

                        assert result.exit_code == 0
                        assert "test-001" in result.stdout
                        assert "test-002" in result.stdout
                        assert "Total Balance" in result.stdout

    def test_list_empty_accounts(self):
        """Test list with no configured accounts."""
        with patch("src.cli.accounts.RedisStateManager") as mock_redis_cls:
            mock_redis = MagicMock()
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis_cls.return_value = mock_redis

            with patch("src.cli.accounts.ConfigLoader") as mock_loader:
                mock_config = MagicMock()
                mock_loader.return_value.load.return_value = mock_config

                with patch("src.cli.accounts.AccountManager") as mock_manager_cls:
                    mock_manager = MagicMock()
                    mock_manager_cls.return_value = mock_manager

                    with patch("src.cli.accounts._get_metrics_service") as mock_get_service:
                        mock_service = MagicMock()
                        mock_service.get_all_account_metrics = AsyncMock(return_value={})
                        mock_get_service.return_value = mock_service

                        result = runner.invoke(app, ["accounts", "list"])

                        assert result.exit_code == 0
                        assert "No accounts configured" in result.stdout


class TestAccountsConfigErrors:
    """Tests for configuration error handling."""

    def test_config_not_found_for_status(self):
        """Test handling of missing config file for status command."""
        with patch("src.cli.accounts.ConfigLoader") as mock_loader:
            mock_loader.return_value.load.side_effect = FileNotFoundError(
                "Config not found"
            )
            with patch("src.cli.accounts.RedisStateManager") as mock_redis:
                mock_instance = MagicMock()
                mock_instance.connect = AsyncMock()
                mock_instance.close = AsyncMock()
                mock_redis.return_value = mock_instance

                result = runner.invoke(app, ["accounts", "status", "test-001"])

                assert result.exit_code == 1
                assert "Config file not found" in result.stdout

    def test_config_not_found_for_list(self):
        """Test handling of missing config file for list command."""
        with patch("src.cli.accounts.ConfigLoader") as mock_loader:
            mock_loader.return_value.load.side_effect = FileNotFoundError(
                "Config not found"
            )
            with patch("src.cli.accounts.RedisStateManager") as mock_redis:
                mock_instance = MagicMock()
                mock_instance.connect = AsyncMock()
                mock_instance.close = AsyncMock()
                mock_redis.return_value = mock_instance

                result = runner.invoke(app, ["accounts", "list"])

                assert result.exit_code == 1
                assert "Config file not found" in result.stdout


class TestMainCLI:
    """Tests for main CLI structure."""

    def test_main_help(self):
        """Test main CLI --help shows commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "accounts" in result.stdout
        assert "config" in result.stdout
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "status" in result.stdout

    def test_start_help_shows_options(self):
        """Test start command shows --dry-run and --verbose options."""
        result = runner.invoke(app, ["start", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.stdout
        assert "--verbose" in result.stdout or "-v" in result.stdout

    def test_stop_help_shows_force_option(self):
        """Test stop command shows --force option."""
        result = runner.invoke(app, ["stop", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.stdout or "-f" in result.stdout

    def test_status_help_shows_json_option(self):
        """Test status command shows --json option."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.stdout


# ---------------------------------------------------------------------------
# Epic 9 P0.10 — `accounts promote`
# ---------------------------------------------------------------------------


class TestPromoteCommand:
    """Tests for `trading-engine accounts promote`.

    Patches the helpers (config loader, firm registry, audit persistence)
    so the command can be exercised without TimescaleDB / firm YAML files.
    """

    def _patches(
        self,
        *,
        accounts=None,
        registry=None,
        validate_side_effect=None,
        persist_side_effect=None,
        session_factory_side_effect=None,
    ):
        from datetime import datetime, timezone

        from src.config.firm_profile import AccountPhase
        from src.rules.audit_logger import AuditEntry, AuditEventType

        # Default account list with one firm-bound account.
        if accounts is None:
            account = MagicMock()
            account.id = "ftmo-001"
            account.firm_id = "ftmo"
            account.product_id = "challenge"
            account.phase = "evaluation"
            accounts = [account]

        config = MagicMock()
        config.accounts = accounts

        if registry is None:
            registry = MagicMock()

        validate_phases = (
            AccountPhase(phase_id="evaluation", name="Evaluation"),
            AccountPhase(phase_id="verification", name="Verification"),
        )

        validate_patch = patch(
            "src.cli.accounts.validate_phase_transition",
            return_value=validate_phases if validate_side_effect is None else None,
            side_effect=validate_side_effect,
        )

        # Real entry — round-trip the same fields the command passes.
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc),
            account_id="ftmo-001",
            event_type=AuditEventType.SYSTEM_EVENT.value,
            event_subtype="phase_transition",
            source="cli",
            level="INFO",
            message="msg",
            rule_name="",
            rule_result="",
            context={},
        )
        build_patch = patch(
            "src.cli.accounts.build_phase_transition_audit_entry",
            return_value=entry,
        )

        config_patch = patch(
            "src.cli.accounts._load_accounts_config_or_exit",
            return_value=(config, "configs/accounts.yaml"),
        )
        registry_patch = patch(
            "src.cli.accounts._load_firm_registry_or_exit",
            return_value=registry,
        )
        if session_factory_side_effect is not None:
            session_patch = patch(
                "src.cli.audit.get_db_session_factory",
                side_effect=session_factory_side_effect,
            )
        else:
            session_patch = patch(
                "src.cli.audit.get_db_session_factory",
                return_value=MagicMock(),
            )
        persist_patch = patch(
            "src.cli.accounts._persist_audit_entry",
            new=AsyncMock(side_effect=persist_side_effect),
        )

        return (
            config_patch, registry_patch, validate_patch,
            build_patch, session_patch, persist_patch,
        )

    def test_promote_success(self):
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = runner.invoke(
                app,
                [
                    "accounts", "promote",
                    "--account", "ftmo-001",
                    "--phase", "verification",
                    "--reason", "Passed Challenge target",
                    "--actor", "ops-test",
                ],
            )
        assert result.exit_code == 0, result.stdout
        assert "evaluation → verification" in result.stdout
        assert "Reason:" in result.stdout and "Passed Challenge target" in result.stdout
        assert "Actor:" in result.stdout and "ops-test" in result.stdout
        # Hint to update YAML must appear
        assert "configs/accounts.yaml" in result.stdout
        assert "phase: verification" in result.stdout

    def test_promote_missing_required_flags(self):
        # `--account` is required
        result = runner.invoke(
            app,
            ["accounts", "promote", "--phase", "verification", "--reason", "x"],
        )
        assert result.exit_code != 0

    def test_promote_unknown_account_exits_1(self):
        # Empty account list → command should report "not found"
        patches = self._patches(accounts=[])
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = runner.invoke(
                app,
                [
                    "accounts", "promote",
                    "--account", "ghost",
                    "--phase", "verification",
                    "--reason", "x",
                ],
            )
        assert result.exit_code == 1
        assert "not found" in result.stdout

    def test_promote_validation_error_exits_1(self):
        from src.accounts.phase_promotion import PhasePromotionError

        patches = self._patches(
            validate_side_effect=PhasePromotionError("transition not allowed"),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = runner.invoke(
                app,
                [
                    "accounts", "promote",
                    "--account", "ftmo-001",
                    "--phase", "funded",
                    "--reason", "Skipping Verification",
                ],
            )
        assert result.exit_code == 1
        assert "transition not allowed" in result.stdout

    def test_promote_db_failure_exits_1(self):
        from sqlalchemy.exc import OperationalError

        patches = self._patches(
            persist_side_effect=OperationalError("stmt", {}, RuntimeError("conn refused")),
        )
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = runner.invoke(
                app,
                [
                    "accounts", "promote",
                    "--account", "ftmo-001",
                    "--phase", "verification",
                    "--reason", "ops",
                ],
            )
        assert result.exit_code == 1
        assert "Failed to write audit entry" in result.stdout

    def test_promote_emits_correlation_id(self):
        patches = self._patches()
        with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
            result = runner.invoke(
                app,
                [
                    "accounts", "promote",
                    "--account", "ftmo-001",
                    "--phase", "verification",
                    "--reason", "ops",
                    "--actor", "ops-test",
                ],
            )
        assert result.exit_code == 0, result.stdout
        # Correlation ID line is present and looks like a UUID prefix
        assert "Correlation ID:" in result.stdout
        # Capture the value and check format
        line = next(
            (ln for ln in result.stdout.splitlines() if "Correlation ID:" in ln),
            "",
        )
        cid = line.split("Correlation ID:")[1].strip()
        # uuid4 string form is 36 chars including hyphens
        assert len(cid) == 36
        assert cid.count("-") == 4
