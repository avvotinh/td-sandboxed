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
    """Tests for accounts status command."""

    def test_status_all_accounts(self, mock_get_account_manager):
        """Test getting status of all accounts."""
        result = runner.invoke(app, ["accounts", "status"])

        assert result.exit_code == 0
        assert "test-001" in result.stdout
        assert "test-002" in result.stdout
        assert "active" in result.stdout
        assert "paused" in result.stdout
        mock_get_account_manager.get_all_statuses.assert_called_once()

    def test_status_specific_account(self, mock_get_account_manager):
        """Test getting status of specific account."""
        result = runner.invoke(app, ["accounts", "status", "test-001"])

        assert result.exit_code == 0
        assert "test-001" in result.stdout
        assert "active" in result.stdout
        mock_get_account_manager.get_account_status.assert_called_once_with("test-001")

    def test_status_nonexistent_account(self, mock_get_account_manager):
        """Test getting status of nonexistent account."""
        mock_get_account_manager._validate_account_exists.side_effect = ValueError(
            "Account not found"
        )

        result = runner.invoke(app, ["accounts", "status", "nonexistent"])

        assert result.exit_code == 1
        assert "Error" in result.stdout

    def test_status_empty_accounts(self, mock_get_account_manager):
        """Test status with no configured accounts."""
        mock_get_account_manager.get_all_statuses.return_value = {}

        result = runner.invoke(app, ["accounts", "status"])

        assert result.exit_code == 0
        assert "No accounts configured" in result.stdout


class TestAccountsConfigErrors:
    """Tests for configuration error handling."""

    def test_config_not_found(self):
        """Test handling of missing config file."""
        with patch("src.cli.accounts.ConfigLoader") as mock_loader:
            mock_loader.return_value.load.side_effect = FileNotFoundError(
                "Config not found"
            )
            with patch("src.cli.accounts.RedisStateManager") as mock_redis:
                mock_instance = MagicMock()
                mock_instance.connect = AsyncMock()
                mock_instance.close = AsyncMock()
                mock_redis.return_value = mock_instance

                result = runner.invoke(app, ["accounts", "status"])

                assert result.exit_code == 1
                assert "Config file not found" in result.stdout


class TestMainCLI:
    """Tests for main CLI structure."""

    def test_main_help(self):
        """Test main CLI --help shows commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "accounts" in result.stdout
        assert "start" in result.stdout
        assert "stop" in result.stdout
        assert "status" in result.stdout

    def test_start_engine(self):
        """Test start command."""
        result = runner.invoke(app, ["start"])
        assert result.exit_code == 0
        assert "Starting trading engine" in result.stdout

    def test_stop_engine(self):
        """Test stop command."""
        result = runner.invoke(app, ["stop"])
        assert result.exit_code == 0
        assert "Stopping trading engine" in result.stdout

    def test_status_engine(self):
        """Test status command."""
        result = runner.invoke(app, ["status"])
        assert result.exit_code == 0
        assert "status" in result.stdout.lower()
