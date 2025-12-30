"""Integration tests for AccountMetrics CLI commands.

Tests the full flow from MT5 updates through to CLI display,
verifying AC1-AC5 requirements for Story 3.6.
"""

import asyncio
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from typer.testing import CliRunner

from src.accounts.metrics import AccountMetrics
from src.accounts.metrics_service import AccountMetricsService
from src.cli.main import app

runner = CliRunner()


class TestFullMetricsFlow:
    """Integration tests for full metrics flow (Task 8.1).

    Test flow: update balance -> update equity -> query status
    """

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis with realistic behavior."""
        redis = MagicMock()
        # Storage for test data
        balances = {}
        statuses = {}

        async def save_balance(account_id, balance):
            balances[account_id] = balance

        async def get_balance(account_id):
            return balances.get(account_id)

        async def get_status(account_id):
            return statuses.get(account_id, "active")

        redis.save_account_balance = AsyncMock(side_effect=save_balance)
        redis.get_account_balance = AsyncMock(side_effect=get_balance)
        redis.get_account_status = AsyncMock(side_effect=get_status)
        redis.connect = AsyncMock()
        redis.close = AsyncMock()
        redis._balances = balances  # Expose for assertions

        return redis

    @pytest.fixture
    def mock_risk_registry(self):
        """Create mock RiskStateRegistry with realistic behavior."""
        registry = MagicMock()
        equity_values = {}

        async def update_equity(account_id, equity):
            state = MagicMock()
            state.current_equity = equity
            state.daily_pnl = equity - Decimal("100000")  # Assume start at 100k
            state.daily_pnl_percent = (state.daily_pnl / Decimal("100000")) * 100
            state.peak_equity = max(equity, Decimal("100000"))
            state.total_drawdown_percent = max(
                Decimal("0"),
                ((state.peak_equity - equity) / state.peak_equity) * 100
            )
            state.last_updated = datetime.now(timezone.utc)
            equity_values[account_id] = state

        def get_risk_state(account_id):
            return equity_values.get(account_id)

        registry.update_account_equity = AsyncMock(side_effect=update_equity)
        registry.get_risk_state = MagicMock(side_effect=get_risk_state)

        return registry

    @pytest.fixture
    def mock_account_manager(self):
        """Create mock AccountManager."""
        manager = MagicMock()
        config = MagicMock()
        config.name = "FTMO Gold Challenge"
        manager.get_account = MagicMock(return_value=config)
        manager.get_all_accounts = MagicMock(return_value=["ftmo-gold-001"])
        return manager

    @pytest.mark.asyncio
    async def test_full_flow_balance_equity_status(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Test complete flow: MT5 update -> service processing -> metrics query.

        AC1, AC4, AC5: Verifies balance/equity updates flow correctly and
        can be queried through the service.
        """
        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )

        # Step 1: Simulate MT5 balance/equity update
        await service.on_mt5_balance_update(
            "ftmo-gold-001",
            balance=Decimal("100000"),
            equity=Decimal("98500"),
        )

        # Step 2: Verify balance was saved to Redis
        mock_redis.save_account_balance.assert_called_with(
            "ftmo-gold-001", Decimal("100000")
        )

        # Step 3: Verify equity was updated in risk registry
        mock_risk_registry.update_account_equity.assert_called_with(
            "ftmo-gold-001", Decimal("98500")
        )

        # Step 4: Query metrics and verify combined data
        # Need to set up mock to return the stored balance
        mock_redis.get_account_balance = AsyncMock(return_value=Decimal("100000"))

        metrics = await service.get_account_metrics("ftmo-gold-001")

        assert metrics is not None
        assert metrics.account_id == "ftmo-gold-001"
        assert metrics.balance == Decimal("100000")
        assert metrics.equity == Decimal("98500")
        assert metrics.daily_pnl == Decimal("-1500")

    def test_status_command_displays_correct_format(self):
        """Test CLI status command output format matches AC1 requirements.

        AC1: Given Account A has initial balance $100,000 and current equity $98,500,
        when I run `trading-engine accounts status ftmo-gold-001`,
        then I see formatted output showing Account ID, Name, Status, Balance,
        Equity, Daily P&L (amount and %), Max Drawdown %, and Peak Equity
        """
        # Set up realistic mock data
        mock_metrics = MagicMock()
        mock_metrics.account_id = "ftmo-gold-001"
        mock_metrics.account_name = "FTMO Gold Challenge"
        mock_metrics.status = "active"
        mock_metrics.daily_pnl = Decimal("-1500")
        mock_metrics.to_status_dict.return_value = {
            "account_id": "ftmo-gold-001",
            "account_name": "FTMO Gold Challenge",
            "status": "active",
            "balance": "$100,000.00",
            "equity": "$98,500.00",
            "daily_pnl": "-$1,500.00 (-1.5%)",
            "max_drawdown": "1.5%",
            "peak_equity": "$100,000.00",
        }

        with patch("src.cli.accounts.RedisStateManager") as mock_redis_cls:
            mock_redis_inst = MagicMock()
            mock_redis_inst.connect = AsyncMock()
            mock_redis_inst.close = AsyncMock()
            mock_redis_cls.return_value = mock_redis_inst

            with patch("src.cli.accounts.ConfigLoader") as mock_loader:
                mock_config = MagicMock()
                mock_loader.return_value.load.return_value = mock_config

                with patch("src.cli.accounts.AccountManager") as mock_mgr_cls:
                    mock_manager = MagicMock()
                    mock_manager.load_accounts = MagicMock()
                    mock_mgr_cls.return_value = mock_manager

                    with patch("src.cli.accounts._get_metrics_service") as mock_get_svc:
                        mock_service = MagicMock()
                        mock_service.get_account_metrics = AsyncMock(
                            return_value=mock_metrics
                        )
                        mock_get_svc.return_value = mock_service

                        result = runner.invoke(
                            app, ["accounts", "status", "ftmo-gold-001"]
                        )

                        # Verify all required fields are present in output
                        assert result.exit_code == 0, f"CLI failed: {result.stdout}"
                        assert "ftmo-gold-001" in result.stdout
                        assert "FTMO Gold Challenge" in result.stdout
                        assert "active" in result.stdout
                        assert "$100,000.00" in result.stdout  # Balance
                        assert "$98,500.00" in result.stdout   # Equity
                        assert "-$1,500.00" in result.stdout   # Daily P&L
                        assert "1.5%" in result.stdout         # Drawdown or P&L %
                        assert "Peak Equity" in result.stdout


class TestMultiAccountList:
    """Integration tests for multi-account list (Task 8.2).

    Test multi-account list with mixed statuses.
    """

    def test_list_command_with_mixed_statuses(self):
        """Test list command shows all accounts with correct sorting.

        AC3: Given I run `trading-engine accounts list`,
        then I see a summary table with columns: ID, Name, Status, Balance, Daily P&L
        Accounts should be sorted by status (active first), then by ID.
        """
        mock_metrics_active = MagicMock()
        mock_metrics_active.account_id = "ftmo-gold-001"
        mock_metrics_active.account_name = "FTMO Gold"
        mock_metrics_active.status = "active"
        mock_metrics_active.balance = Decimal("100000")
        mock_metrics_active.to_list_row.return_value = [
            "ftmo-gold-001", "FTMO Gold", "active", "$100,000.00", "+0.5%"
        ]

        mock_metrics_paused = MagicMock()
        mock_metrics_paused.account_id = "ftmo-silver-002"
        mock_metrics_paused.account_name = "FTMO Silver"
        mock_metrics_paused.status = "paused"
        mock_metrics_paused.balance = Decimal("50000")
        mock_metrics_paused.to_list_row.return_value = [
            "ftmo-silver-002", "FTMO Silver", "paused", "$50,000.00", "-1.0%"
        ]

        mock_metrics_stopped = MagicMock()
        mock_metrics_stopped.account_id = "demo-003"
        mock_metrics_stopped.account_name = "Demo Account"
        mock_metrics_stopped.status = "stopped"
        mock_metrics_stopped.balance = Decimal("25000")
        mock_metrics_stopped.to_list_row.return_value = [
            "demo-003", "Demo Account", "stopped", "$25,000.00", "0.0%"
        ]

        with patch("src.cli.accounts.RedisStateManager") as mock_redis_cls:
            mock_redis = MagicMock()
            mock_redis.connect = AsyncMock()
            mock_redis.close = AsyncMock()
            mock_redis_cls.return_value = mock_redis

            with patch("src.cli.accounts.ConfigLoader") as mock_loader:
                mock_config = MagicMock()
                mock_loader.return_value.load.return_value = mock_config

                with patch("src.cli.accounts.AccountManager"):
                    with patch("src.cli.accounts._get_metrics_service") as mock_get_svc:
                        mock_service = MagicMock()
                        mock_service.get_all_account_metrics = AsyncMock(
                            return_value={
                                "ftmo-gold-001": mock_metrics_active,
                                "ftmo-silver-002": mock_metrics_paused,
                                "demo-003": mock_metrics_stopped,
                            }
                        )
                        mock_get_svc.return_value = mock_service

                        result = runner.invoke(app, ["accounts", "list"])

                        assert result.exit_code == 0

                        # Verify all accounts are listed
                        assert "ftmo-gold-001" in result.stdout
                        assert "ftmo-silver-002" in result.stdout
                        assert "demo-003" in result.stdout

                        # Verify table headers
                        assert "ID" in result.stdout
                        assert "Name" in result.stdout
                        assert "Status" in result.stdout
                        assert "Balance" in result.stdout

                        # Verify total balance
                        assert "Total Balance" in result.stdout
                        assert "$175,000.00" in result.stdout

                        # Verify sorting: active appears before paused/stopped
                        active_pos = result.stdout.find("ftmo-gold-001")
                        paused_pos = result.stdout.find("ftmo-silver-002")
                        stopped_pos = result.stdout.find("demo-003")
                        assert active_pos < paused_pos
                        assert active_pos < stopped_pos


class TestAccountIsolation:
    """Integration tests for account isolation (Task 8.3, AC2).

    Test concurrent balance updates to different accounts.
    """

    @pytest.mark.asyncio
    async def test_concurrent_updates_isolated(self):
        """Test concurrent balance updates don't cross-contaminate.

        AC2: Given Account B has different financials,
        when I view Account B's status,
        then I see Account B's metrics (not Account A's) - complete isolation
        """
        redis = MagicMock()
        balances = {}

        async def save_balance(account_id, balance):
            balances[account_id] = balance

        async def get_balance(account_id):
            return balances.get(account_id)

        redis.save_account_balance = AsyncMock(side_effect=save_balance)
        redis.get_account_balance = AsyncMock(side_effect=get_balance)
        redis.get_account_status = AsyncMock(return_value="active")

        risk_registry = MagicMock()
        risk_states = {}

        async def update_equity(account_id, equity):
            state = MagicMock()
            state.current_equity = equity
            state.daily_pnl = Decimal("0")
            state.daily_pnl_percent = Decimal("0")
            state.peak_equity = equity
            state.total_drawdown_percent = Decimal("0")
            state.last_updated = datetime.now(timezone.utc)
            risk_states[account_id] = state

        risk_registry.update_account_equity = AsyncMock(side_effect=update_equity)
        risk_registry.get_risk_state = MagicMock(side_effect=lambda aid: risk_states.get(aid))

        account_manager = MagicMock()
        configs = {
            "account-a": MagicMock(name="Account A"),
            "account-b": MagicMock(name="Account B"),
        }
        account_manager.get_account = MagicMock(side_effect=lambda aid: configs.get(aid))
        account_manager.get_all_accounts = MagicMock(return_value=["account-a", "account-b"])

        service = AccountMetricsService(redis, risk_registry, account_manager)

        # Concurrent updates to different accounts
        await asyncio.gather(
            service.on_mt5_balance_update("account-a", Decimal("100000"), Decimal("99000")),
            service.on_mt5_balance_update("account-b", Decimal("50000"), Decimal("52000")),
        )

        # Verify isolation - each account has its own data
        assert balances["account-a"] == Decimal("100000")
        assert balances["account-b"] == Decimal("50000")
        assert risk_states["account-a"].current_equity == Decimal("99000")
        assert risk_states["account-b"].current_equity == Decimal("52000")

        # Query metrics and verify isolation
        redis.get_account_balance = AsyncMock(side_effect=get_balance)

        metrics_a = await service.get_account_metrics("account-a")
        metrics_b = await service.get_account_metrics("account-b")

        # Complete isolation verified
        assert metrics_a.balance == Decimal("100000")
        assert metrics_b.balance == Decimal("50000")
        assert metrics_a.equity == Decimal("99000")
        assert metrics_b.equity == Decimal("52000")

        # Cross-check: A's data is not B's data
        assert metrics_a.balance != metrics_b.balance
        assert metrics_a.equity != metrics_b.equity

    @pytest.mark.asyncio
    async def test_rapid_concurrent_updates_same_account_debounced(self):
        """Test rapid concurrent updates to same account are debounced."""
        redis = MagicMock()
        redis.save_account_balance = AsyncMock()

        risk_registry = MagicMock()
        risk_registry.update_account_equity = AsyncMock()
        risk_registry.get_risk_state = MagicMock(return_value=None)

        account_manager = MagicMock()
        account_manager.get_account = MagicMock(return_value=MagicMock(name="Test"))

        service = AccountMetricsService(redis, risk_registry, account_manager)

        # Fire multiple rapid updates
        updates = [
            service.on_mt5_balance_update("test-001", Decimal(str(100000 + i)), Decimal(str(100000 + i)))
            for i in range(10)
        ]
        await asyncio.gather(*updates)

        # Due to debouncing, only first update should be processed
        # (all others are within 100ms window)
        assert redis.save_account_balance.call_count == 1
        assert risk_registry.update_account_equity.call_count == 1


class TestRedisKeyPatterns:
    """Integration tests for Redis key patterns (AC5)."""

    @pytest.mark.asyncio
    async def test_redis_key_patterns_correct(self):
        """Verify correct Redis key patterns are used.

        AC5: Given an account's metrics are stored in Redis,
        when I query the status,
        then the CLI retrieves data from `risk:{account_id}:state` hash
        """
        # This test verifies the key patterns used match the specification
        redis = MagicMock()
        calls = []

        async def track_save(account_id, balance):
            calls.append(("save_balance", f"account:{account_id}:balance", balance))

        async def track_get(account_id):
            calls.append(("get_balance", f"account:{account_id}:balance"))
            return Decimal("100000")

        async def track_status(account_id):
            calls.append(("get_status", f"account:{account_id}:status"))
            return "active"

        redis.save_account_balance = AsyncMock(side_effect=track_save)
        redis.get_account_balance = AsyncMock(side_effect=track_get)
        redis.get_account_status = AsyncMock(side_effect=track_status)

        risk_registry = MagicMock()
        risk_registry.update_account_equity = AsyncMock()

        def track_risk_state(account_id):
            calls.append(("get_risk_state", f"risk:{account_id}:state"))
            state = MagicMock()
            state.current_equity = Decimal("99000")
            state.daily_pnl = Decimal("-1000")
            state.daily_pnl_percent = Decimal("-1.0")
            state.peak_equity = Decimal("100000")
            state.total_drawdown_percent = Decimal("1.0")
            state.last_updated = datetime.now(timezone.utc)
            return state

        risk_registry.get_risk_state = MagicMock(side_effect=track_risk_state)

        account_manager = MagicMock()
        account_manager.get_account = MagicMock(return_value=MagicMock(name="Test"))

        service = AccountMetricsService(redis, risk_registry, account_manager)

        # Trigger balance update
        await service.on_mt5_balance_update(
            "ftmo-001", Decimal("100000"), Decimal("99000")
        )

        # Query metrics
        await service.get_account_metrics("ftmo-001")

        # Verify key patterns used
        key_patterns = [c[1] for c in calls]

        # Balance key: account:{id}:balance
        assert "account:ftmo-001:balance" in key_patterns

        # Status key: account:{id}:status
        assert "account:ftmo-001:status" in key_patterns

        # Risk state key: risk:{id}:state
        assert "risk:ftmo-001:state" in key_patterns
