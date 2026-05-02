"""Integration tests for CLI commands using Typer testing utilities.

These tests use mocking to simulate Redis and config behavior while testing
the full CLI command flow including argument parsing, validation, and output.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.cli.main import app

runner = CliRunner()


# Test data for mocking
MOCK_ACCOUNTS_CONFIG = {
    "accounts": [
        {
            "id": "ftmo-001",
            "name": "FTMO Challenge",
            "mt5": {"login": 12345, "server": "FTMO-Demo", "password_env": "FTMO_PASS"},
            "symbols": ["EURUSD", "GBPUSD"],
        },
        {
            "id": "ftmo-002",
            "name": "FTMO Funded",
            "mt5": {"login": 67890, "server": "FTMO-Live", "password_env": "FTMO_PASS_2"},
            "symbols": ["USDJPY"],
        },
    ]
}


@pytest.fixture
def mock_config_loader():
    """Create a mock ConfigLoader."""
    loader = MagicMock()
    config = MagicMock()
    config.accounts = []
    for acc_data in MOCK_ACCOUNTS_CONFIG["accounts"]:
        acc = MagicMock()
        acc.id = acc_data["id"]
        acc.name = acc_data["name"]
        acc.mt5 = MagicMock()
        acc.mt5.password_env = acc_data["mt5"]["password_env"]
        config.accounts.append(acc)
    config.model_dump.return_value = MOCK_ACCOUNTS_CONFIG
    loader.load.return_value = config
    return loader


@pytest.fixture
def mock_redis():
    """Create a mock RedisStateManager."""
    from datetime import datetime, timezone

    redis = MagicMock()
    redis.connect = AsyncMock()
    redis.close = AsyncMock()
    redis.client = MagicMock()
    redis.client.ping = AsyncMock()
    redis.client.set = AsyncMock()

    # Mock get to return appropriate values based on key
    async def mock_get(key):
        if key == "engine:state":
            return "running"
        elif key == "engine:start_time":
            return datetime.now(timezone.utc).isoformat()
        return None

    redis.client.get = AsyncMock(side_effect=mock_get)
    redis.client.delete = AsyncMock()
    redis.get_all_account_statuses = AsyncMock(
        return_value={"ftmo-001": "active", "ftmo-002": "paused"}
    )
    return redis


# ============================================================================
# TESTS FOR START COMMAND
# ============================================================================


class TestStartDryRun:
    """Tests for start --dry-run validation."""

    def test_dry_run_validates_config_exists(self):
        """Should fail gracefully when config file missing."""
        with patch.dict("os.environ", {"ACCOUNTS_CONFIG": "/nonexistent.yaml"}):
            result = runner.invoke(app, ["start", "--dry-run"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_dry_run_validates_config_syntax(self, mock_redis):
        """Should fail on invalid YAML syntax."""
        from src.config.loader import ConfigSyntaxError

        with patch("src.cli.main.ConfigLoader") as mock_loader_cls:
            import yaml

            mock_loader_cls.return_value.load.side_effect = ConfigSyntaxError(
                yaml.YAMLError("invalid syntax"), "/path/to/config.yaml"
            )
            result = runner.invoke(app, ["start", "--dry-run"])
            assert result.exit_code == 1
            assert "YAML" in result.output or "syntax" in result.output.lower()

    def test_dry_run_validates_redis_connection(self, mock_config_loader):
        """Should attempt Redis connection in dry-run mode."""
        with patch("src.cli.main.ConfigLoader", return_value=mock_config_loader):
            with patch.dict("os.environ", {"FTMO_PASS": "secret", "FTMO_PASS_2": "secret2"}):
                with patch("src.cli.main.RedisStateManager") as mock_redis_cls:
                    mock_instance = MagicMock()
                    mock_instance.connect = AsyncMock(
                        side_effect=ConnectionError("Redis down")
                    )
                    mock_redis_cls.return_value = mock_instance

                    result = runner.invoke(app, ["start", "--dry-run"])
                    assert result.exit_code == 1
                    assert "Redis" in result.output

    def test_dry_run_validates_env_vars_missing(self, mock_config_loader, mock_redis):
        """Should fail when required MT5 password env vars are missing."""
        with patch("src.cli.main.ConfigLoader", return_value=mock_config_loader):
            with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
                # Env vars not set
                with patch.dict("os.environ", {}, clear=True):
                    result = runner.invoke(app, ["start", "--dry-run"])
                    assert result.exit_code == 1
                    assert "Missing env vars" in result.output or "FTMO_PASS" in result.output

    def test_dry_run_success_shows_validation_results(self, mock_config_loader, mock_redis):
        """Should show what was validated on success."""
        with patch("src.cli.main.ConfigLoader", return_value=mock_config_loader):
            with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
                with patch.dict(
                    "os.environ", {"FTMO_PASS": "secret", "FTMO_PASS_2": "secret2"}
                ):
                    result = runner.invoke(app, ["start", "--dry-run"])
                    assert result.exit_code == 0
                    assert "Dry run" in result.output or "validations passed" in result.output
                    assert "✓" in result.output


class TestStartVerbose:
    """Tests for start --verbose flag."""

    def test_start_verbose_enables_debug_logging(self, mock_config_loader, mock_redis):
        """--verbose should enable DEBUG logging level."""
        with patch("src.cli.main.ConfigLoader", return_value=mock_config_loader):
            with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
                with patch("src.cli.main.AccountManager") as mock_manager_cls:
                    mock_manager = MagicMock()
                    mock_manager.get_account_status = AsyncMock(return_value=None)
                    mock_manager.start_account = AsyncMock()
                    mock_manager_cls.return_value = mock_manager

                    with patch("logging.getLogger") as mock_logger:
                        result = runner.invoke(app, ["start", "--verbose"])
                        # Verify logging was configured for debug
                        mock_logger.return_value.setLevel.assert_called()


class TestStartFull:
    """Tests for full start command."""

    def test_start_loads_accounts(self, mock_config_loader, mock_redis):
        """Start command should load and initialize accounts."""
        with patch("src.cli.main.ConfigLoader", return_value=mock_config_loader):
            with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
                with patch("src.cli.main.AccountManager") as mock_manager_cls:
                    mock_manager = MagicMock()
                    mock_manager.get_account_status = AsyncMock(return_value=None)
                    mock_manager.start_account = AsyncMock()
                    mock_manager_cls.return_value = mock_manager

                    result = runner.invoke(app, ["start"])
                    assert result.exit_code == 0
                    assert "Trading engine started" in result.output

    def test_start_config_error(self):
        """Start should fail gracefully on config error."""
        with patch.dict("os.environ", {"ACCOUNTS_CONFIG": "/nonexistent.yaml"}):
            result = runner.invoke(app, ["start"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()


# ============================================================================
# TESTS FOR STOP COMMAND
# ============================================================================


class TestStopCommand:
    """Tests for stop command."""

    def test_stop_force_skips_confirmation(self, mock_redis):
        """--force flag should skip confirmation prompt."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["stop", "--force"])
            assert result.exit_code == 0
            assert "stopped" in result.output.lower()

    def test_stop_confirms_before_shutdown(self, mock_redis):
        """Should prompt for confirmation without --force."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["stop"], input="y\n")
            assert result.exit_code == 0
            assert "stopped" in result.output.lower()

    def test_stop_abort_on_no(self, mock_redis):
        """Should abort on 'n' answer."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["stop"], input="n\n")
            assert result.exit_code == 1  # Aborted

    def test_stop_already_stopped(self, mock_redis):
        """Should handle already stopped engine gracefully."""
        mock_redis.client.get = AsyncMock(return_value="stopped")
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["stop", "-f"])
            assert result.exit_code == 0
            assert "already stopped" in result.output.lower()

    def test_stop_sets_stopped_state(self, mock_redis):
        """Stop should set engine state to stopped."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["stop", "-f"])
            assert result.exit_code == 0
            # Verify state was set to stopping then stopped
            mock_redis.client.set.assert_called()


# ============================================================================
# TESTS FOR STATUS COMMAND
# ============================================================================


class TestStatusCommand:
    """Tests for status command."""

    def test_status_shows_engine_state(self, mock_redis):
        """Status should display engine state."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["status"])
            assert result.exit_code == 0
            assert "Engine" in result.output
            assert "running" in result.output.lower() or "stopped" in result.output.lower()

    def test_status_shows_connection_info(self, mock_redis):
        """Status should show Redis and MT5 bridge status."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["status"])
            assert result.exit_code == 0
            assert "Redis" in result.output
            assert "MT5" in result.output or "Bridge" in result.output

    def test_status_shows_account_counts(self, mock_redis):
        """Status should show account counts by state."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["status"])
            assert result.exit_code == 0
            assert "active" in result.output.lower()
            assert "paused" in result.output.lower()


class TestStatusJson:
    """Tests for status --json output."""

    def test_status_json_is_valid_json(self, mock_redis):
        """--json output must be valid JSON."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["status", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert "engine" in data
            assert "accounts" in data
            assert "connections" in data

    def test_status_json_has_required_fields(self, mock_redis):
        """JSON output should have all required fields."""
        with patch("src.cli.main.RedisStateManager", return_value=mock_redis):
            result = runner.invoke(app, ["status", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)

            assert "status" in data["engine"]
            assert "uptime" in data["engine"]
            assert "active" in data["accounts"]
            assert "paused" in data["accounts"]
            assert "stopped" in data["accounts"]
            assert "total" in data["accounts"]
            assert "redis" in data["connections"]
            assert "mt5_bridge" in data["connections"]

    def test_status_handles_redis_disconnected(self):
        """Should handle Redis disconnection gracefully."""
        with patch("src.cli.main.RedisStateManager") as mock_redis_cls:
            mock_instance = MagicMock()
            mock_instance.connect = AsyncMock(side_effect=ConnectionError("Redis down"))
            mock_redis_cls.return_value = mock_instance

            result = runner.invoke(app, ["status", "--json"])
            assert result.exit_code == 0
            data = json.loads(result.output)
            assert data["connections"]["redis"]["status"] == "disconnected"
            assert data["engine"]["status"] == "unknown"


# ============================================================================
# TESTS FOR CONFIG COMMAND
# ============================================================================


class TestConfigDump:
    """Tests for config dump command."""

    def test_config_dump_masks_password_fields(self, mock_config_loader):
        """Any field with 'password' in name should be masked."""
        # Create config that has password fields
        config_with_password = {
            "accounts": [
                {
                    "id": "test",
                    "name": "Test",
                    "mt5": {"password_env": "FTMO_PASS", "some_password": "secret123"},
                }
            ]
        }
        mock_config_loader.load.return_value.model_dump.return_value = config_with_password

        with patch("src.cli.config.ConfigLoader", return_value=mock_config_loader):
            result = runner.invoke(app, ["config", "dump"])
            assert result.exit_code == 0
            assert "***" in result.output
            # Ensure actual password values don't appear
            assert "secret123" not in result.output

    def test_config_dump_yaml_format(self, mock_config_loader):
        """Default format should be YAML."""
        with patch("src.cli.config.ConfigLoader", return_value=mock_config_loader):
            result = runner.invoke(app, ["config", "dump"])
            assert result.exit_code == 0
            # YAML output shouldn't have JSON brackets
            assert result.output.strip()[0] != "{"

    def test_config_dump_json_format(self, mock_config_loader):
        """--format json should output valid JSON."""
        with patch("src.cli.config.ConfigLoader", return_value=mock_config_loader):
            result = runner.invoke(app, ["config", "dump", "--format", "json"])
            assert result.exit_code == 0
            # Should be valid JSON
            data = json.loads(result.output)
            assert "accounts" in data

    def test_config_dump_not_found(self):
        """Should error when config file not found."""
        with patch.dict("os.environ", {"ACCOUNTS_CONFIG": "/nonexistent.yaml"}):
            result = runner.invoke(app, ["config", "dump"])
            assert result.exit_code == 1
            assert "not found" in result.output.lower()

    def test_config_dump_invalid_format(self, mock_config_loader):
        """Should reject invalid format values."""
        with patch("src.cli.config.ConfigLoader", return_value=mock_config_loader):
            result = runner.invoke(app, ["config", "dump", "--format", "xml"])
            assert result.exit_code == 1
            assert "Invalid format" in result.output


class TestConfigValidate:
    """Tests for config validate command."""

    def test_config_validate_success(self, mock_config_loader):
        """Valid config should show success message."""
        with patch("src.cli.config.ConfigLoader", return_value=mock_config_loader):
            result = runner.invoke(app, ["config", "validate"])
            assert result.exit_code == 0
            assert "valid" in result.output.lower()

    def test_config_validate_shows_accounts(self, mock_config_loader):
        """Validate should list configured accounts."""
        with patch("src.cli.config.ConfigLoader", return_value=mock_config_loader):
            result = runner.invoke(app, ["config", "validate"])
            assert result.exit_code == 0
            assert "Accounts" in result.output
            assert "ftmo-001" in result.output

    def test_config_validate_invalid_config(self):
        """Should fail on invalid configuration."""
        from pydantic import ValidationError
        from src.config.loader import ConfigValidationError

        mock_validation_error = MagicMock(spec=ValidationError)
        mock_validation_error.errors.return_value = [
            {"loc": ("accounts", 0, "id"), "msg": "Field required"}
        ]

        with patch("src.cli.config.ConfigLoader") as mock_loader_cls:
            mock_loader_cls.return_value.load.side_effect = ConfigValidationError(
                mock_validation_error
            )
            result = runner.invoke(app, ["config", "validate"])
            assert result.exit_code == 1
            assert "validation failed" in result.output.lower() or "required" in result.output.lower()


# ============================================================================
# TESTS FOR MAIN CLI STRUCTURE
# ============================================================================


class TestMainCLI:
    """Tests for main CLI structure and help."""

    def test_main_help_shows_all_commands(self):
        """Main CLI should show all available commands."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "start" in result.output
        assert "stop" in result.output
        assert "status" in result.output
        assert "accounts" in result.output
        assert "config" in result.output

    def test_config_help_shows_subcommands(self):
        """Config group should show dump and validate subcommands."""
        result = runner.invoke(app, ["config", "--help"])
        assert result.exit_code == 0
        assert "dump" in result.output
        assert "validate" in result.output

    def test_start_help_shows_options(self):
        """Start command help should show --dry-run and --verbose options."""
        result = runner.invoke(app, ["start", "--help"])
        assert result.exit_code == 0
        assert "--dry-run" in result.output
        assert "--verbose" in result.output or "-v" in result.output

    def test_stop_help_shows_force_option(self):
        """Stop command help should show --force option."""
        result = runner.invoke(app, ["stop", "--help"])
        assert result.exit_code == 0
        assert "--force" in result.output or "-f" in result.output

    def test_status_help_shows_json_option(self):
        """Status command help should show --json option."""
        result = runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output


# ============================================================================
# UNIT TESTS FOR VALIDATION HELPERS
# ============================================================================


class TestValidationHelpers:
    """Unit tests for validation helper functions in main.py."""

    def test_validate_config_success(self, mock_config_loader):
        """Should return success for valid config."""
        from src.cli.main import _validate_config

        with patch("src.cli.main.ConfigLoader", return_value=mock_config_loader):
            valid, msg, loader = _validate_config("test.yaml")
            assert valid is True
            assert "valid" in msg.lower()
            assert loader is not None

    def test_validate_config_file_not_found(self):
        """Should return failure for missing config file."""
        from src.cli.main import _validate_config

        with patch("src.cli.main.ConfigLoader") as mock_cls:
            mock_cls.side_effect = FileNotFoundError("Config not found")
            valid, msg, loader = _validate_config("/nonexistent.yaml")
            assert valid is False
            assert "not found" in msg.lower()
            assert loader is None

    def test_validate_env_passwords_all_set(self, mock_config_loader):
        """Should pass when all password env vars are set."""
        from src.cli.main import _validate_env_passwords

        with patch.dict("os.environ", {"FTMO_PASS": "secret", "FTMO_PASS_2": "secret2"}):
            valid, missing = _validate_env_passwords(mock_config_loader)
            assert valid is True
            assert missing == []

    def test_validate_env_passwords_missing(self, mock_config_loader):
        """Should fail when password env vars are missing."""
        from src.cli.main import _validate_env_passwords

        with patch.dict("os.environ", {}, clear=True):
            valid, missing = _validate_env_passwords(mock_config_loader)
            assert valid is False
            assert "FTMO_PASS" in missing

    def test_validate_unique_account_ids_unique(self, mock_config_loader):
        """Should pass when all account IDs are unique."""
        from src.cli.main import _validate_unique_account_ids

        valid, duplicates = _validate_unique_account_ids(mock_config_loader)
        assert valid is True
        assert duplicates == []

    def test_validate_unique_account_ids_duplicates(self):
        """Should fail when duplicate account IDs exist."""
        from src.cli.main import _validate_unique_account_ids

        # Create mock with duplicate IDs
        loader = MagicMock()
        config = MagicMock()
        acc1 = MagicMock()
        acc1.id = "dup-001"
        acc2 = MagicMock()
        acc2.id = "dup-001"  # Duplicate!
        config.accounts = [acc1, acc2]
        loader.load.return_value = config

        valid, duplicates = _validate_unique_account_ids(loader)
        assert valid is False
        assert "dup-001" in duplicates


class TestSecretMasking:
    """Unit tests for secret masking function."""

    def test_mask_password_field(self):
        """Should mask fields containing 'password'."""
        from src.cli.config import mask_secrets

        result = mask_secrets({"password": "secret123"})
        assert result["password"] == "***"

    def test_mask_api_key_underscore(self):
        """Should mask fields containing 'api_key'."""
        from src.cli.config import mask_secrets

        result = mask_secrets({"api_key": "key123"})
        assert result["api_key"] == "***"

    def test_mask_apikey_camelcase(self):
        """Should mask camelCase 'apiKey' fields."""
        from src.cli.config import mask_secrets

        result = mask_secrets({"apiKey": "key456"})
        assert result["apiKey"] == "***"

    def test_mask_nested_secrets(self):
        """Should mask secrets in nested dictionaries."""
        from src.cli.config import mask_secrets

        result = mask_secrets({"config": {"database_password": "secret"}})
        assert result["config"]["database_password"] == "***"

    def test_preserve_non_secret_fields(self):
        """Should not mask non-secret fields."""
        from src.cli.config import mask_secrets

        result = mask_secrets({"name": "test", "count": 5})
        assert result["name"] == "test"
        assert result["count"] == 5


class TestUptimeCalculation:
    """Unit tests for uptime calculation."""

    def test_uptime_no_start_time(self):
        """Should return N/A when no start time."""
        from src.cli.main import get_uptime
        import asyncio

        redis = MagicMock()
        redis.client.get = AsyncMock(return_value=None)

        result = asyncio.run(get_uptime(redis))
        assert result == "N/A"

    def test_uptime_invalid_timestamp(self):
        """Should return N/A for invalid timestamp."""
        from src.cli.main import get_uptime
        import asyncio

        redis = MagicMock()
        redis.client.get = AsyncMock(return_value="invalid-timestamp")

        result = asyncio.run(get_uptime(redis))
        assert result == "N/A"

    def test_uptime_valid_timestamp(self):
        """Should calculate uptime correctly."""
        from src.cli.main import get_uptime
        from datetime import datetime, timezone, timedelta
        import asyncio

        # Set start time to 1 hour ago
        start_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
        redis = MagicMock()
        redis.client.get = AsyncMock(return_value=start_time)

        result = asyncio.run(get_uptime(redis))
        assert "1h" in result
        assert "0m" in result or "59m" in result  # Allow some timing variance
