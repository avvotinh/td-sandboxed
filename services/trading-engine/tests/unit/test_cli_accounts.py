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
