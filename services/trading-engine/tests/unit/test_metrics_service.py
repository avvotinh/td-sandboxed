"""Unit tests for AccountMetricsService."""

import pytest
from decimal import Decimal
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from src.accounts.metrics_service import AccountMetricsService
from src.accounts.metrics import AccountMetrics


class TestAccountMetricsService:
    """Unit tests for AccountMetricsService."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock RedisStateManager."""
        redis = MagicMock()
        redis.get_account_balance = AsyncMock(return_value=Decimal("100000"))
        redis.get_account_status = AsyncMock(return_value="active")
        redis.save_account_balance = AsyncMock()
        return redis

    @pytest.fixture
    def mock_risk_registry(self):
        """Create mock RiskStateRegistry."""
        registry = MagicMock()
        risk_state = MagicMock()
        risk_state.current_equity = Decimal("98500")
        risk_state.daily_pnl = Decimal("-1500")
        risk_state.daily_pnl_percent = Decimal("-1.5")
        risk_state.peak_equity = Decimal("100000")
        risk_state.total_drawdown_percent = Decimal("1.5")
        risk_state.last_updated = datetime.now(timezone.utc)
        registry.get_risk_state = MagicMock(return_value=risk_state)
        registry.update_account_equity = AsyncMock()
        return registry

    @pytest.fixture
    def mock_account_manager(self):
        """Create mock AccountManager."""
        manager = MagicMock()
        account_config = MagicMock()
        account_config.name = "FTMO Gold Challenge"
        manager.get_account = MagicMock(return_value=account_config)
        manager.get_all_accounts = MagicMock(return_value=["ftmo-gold-001"])
        return manager

    @pytest.mark.asyncio
    async def test_get_account_metrics_combines_sources(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Metrics combines data from Redis, RiskRegistry, and AccountManager."""
        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        metrics = await service.get_account_metrics("ftmo-gold-001")

        assert metrics is not None
        assert metrics.account_id == "ftmo-gold-001"
        assert metrics.account_name == "FTMO Gold Challenge"
        assert metrics.status == "active"
        assert metrics.balance == Decimal("100000")
        assert metrics.equity == Decimal("98500")
        assert metrics.daily_pnl == Decimal("-1500")
        assert metrics.daily_pnl_percent == Decimal("-1.5")
        assert metrics.peak_equity == Decimal("100000")
        assert metrics.max_drawdown_percent == Decimal("1.5")

    @pytest.mark.asyncio
    async def test_get_account_metrics_not_found(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Returns None for non-existent account."""
        mock_account_manager.get_account = MagicMock(return_value=None)

        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        metrics = await service.get_account_metrics("nonexistent")

        assert metrics is None

    @pytest.mark.asyncio
    async def test_get_account_metrics_no_risk_state(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Returns metrics with defaults when no risk state exists."""
        mock_risk_registry.get_risk_state = MagicMock(return_value=None)

        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        metrics = await service.get_account_metrics("ftmo-gold-001")

        assert metrics is not None
        # When no risk state, equity defaults to balance
        assert metrics.equity == Decimal("100000")
        assert metrics.daily_pnl == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_account_metrics_no_balance(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Returns metrics with zero balance when not found in Redis."""
        mock_redis.get_account_balance = AsyncMock(return_value=None)

        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        metrics = await service.get_account_metrics("ftmo-gold-001")

        assert metrics is not None
        assert metrics.balance == Decimal("0")

    @pytest.mark.asyncio
    async def test_get_all_account_metrics(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Get metrics for all accounts."""
        mock_account_manager.get_all_accounts = MagicMock(
            return_value=["account-a", "account-b"]
        )

        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        all_metrics = await service.get_all_account_metrics()

        assert len(all_metrics) == 2
        assert "account-a" in all_metrics
        assert "account-b" in all_metrics

    @pytest.mark.asyncio
    async def test_update_balance(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """Update balance saves to Redis."""
        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        await service.update_balance("ftmo-gold-001", Decimal("105000"))

        mock_redis.save_account_balance.assert_called_once_with(
            "ftmo-gold-001", Decimal("105000")
        )

    @pytest.mark.asyncio
    async def test_on_mt5_balance_update(
        self, mock_redis, mock_risk_registry, mock_account_manager
    ):
        """MT5 balance update updates both balance and equity."""
        service = AccountMetricsService(
            mock_redis, mock_risk_registry, mock_account_manager
        )
        await service.on_mt5_balance_update(
            "ftmo-gold-001",
            balance=Decimal("100000"),
            equity=Decimal("101500"),
        )

        mock_redis.save_account_balance.assert_called_once_with(
            "ftmo-gold-001", Decimal("100000")
        )
        mock_risk_registry.update_account_equity.assert_called_once_with(
            "ftmo-gold-001", Decimal("101500")
        )


class TestAccountMetricsServiceIsolation:
    """Test that accounts are properly isolated."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies with multi-account support."""
        redis = MagicMock()
        risk_registry = MagicMock()
        account_manager = MagicMock()

        # Setup different balances per account
        async def get_balance(account_id):
            balances = {
                "account-a": Decimal("100000"),
                "account-b": Decimal("50000"),
            }
            return balances.get(account_id)

        redis.get_account_balance = get_balance
        redis.get_account_status = AsyncMock(return_value="active")

        # Setup different risk states per account
        def get_risk_state(account_id):
            states = {
                "account-a": MagicMock(
                    current_equity=Decimal("99000"),
                    daily_pnl=Decimal("-1000"),
                    daily_pnl_percent=Decimal("-1.0"),
                    peak_equity=Decimal("100000"),
                    total_drawdown_percent=Decimal("1.0"),
                    last_updated=datetime.now(timezone.utc),
                ),
                "account-b": MagicMock(
                    current_equity=Decimal("52000"),
                    daily_pnl=Decimal("2000"),
                    daily_pnl_percent=Decimal("4.0"),
                    peak_equity=Decimal("52000"),
                    total_drawdown_percent=Decimal("0.0"),
                    last_updated=datetime.now(timezone.utc),
                ),
            }
            return states.get(account_id)

        risk_registry.get_risk_state = get_risk_state

        # Setup different account configs
        def get_account(account_id):
            config_a = MagicMock()
            config_a.name = "Account A"
            config_b = MagicMock()
            config_b.name = "Account B"
            configs = {
                "account-a": config_a,
                "account-b": config_b,
            }
            return configs.get(account_id)

        account_manager.get_account = get_account
        account_manager.get_all_accounts = MagicMock(
            return_value=["account-a", "account-b"]
        )

        return redis, risk_registry, account_manager

    @pytest.mark.asyncio
    async def test_metrics_isolation(self, mock_dependencies):
        """Each account gets its own metrics (no cross-contamination)."""
        redis, risk_registry, account_manager = mock_dependencies

        service = AccountMetricsService(redis, risk_registry, account_manager)

        metrics_a = await service.get_account_metrics("account-a")
        metrics_b = await service.get_account_metrics("account-b")

        # Account A should have its own values
        assert metrics_a.balance == Decimal("100000")
        assert metrics_a.equity == Decimal("99000")
        assert metrics_a.daily_pnl == Decimal("-1000")
        assert metrics_a.account_name == "Account A"

        # Account B should have its own values (completely different)
        assert metrics_b.balance == Decimal("50000")
        assert metrics_b.equity == Decimal("52000")
        assert metrics_b.daily_pnl == Decimal("2000")
        assert metrics_b.account_name == "Account B"

        # Verify no cross-contamination
        assert metrics_a.balance != metrics_b.balance
        assert metrics_a.daily_pnl != metrics_b.daily_pnl


class TestAccountMetricsServiceDebouncing:
    """Test debouncing for high-frequency updates.

    Uses mocked datetime to ensure deterministic behavior regardless of
    system timing or load.
    """

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies."""
        redis = MagicMock()
        redis.save_account_balance = AsyncMock()
        redis.get_account_balance = AsyncMock(return_value=Decimal("100000"))
        redis.get_account_status = AsyncMock(return_value="active")

        risk_registry = MagicMock()
        risk_registry.update_account_equity = AsyncMock()
        risk_registry.get_risk_state = MagicMock(return_value=None)

        account_manager = MagicMock()
        account_manager.get_account = MagicMock(return_value=MagicMock(name="Test"))

        return redis, risk_registry, account_manager

    @pytest.mark.asyncio
    async def test_debounce_blocks_rapid_updates(self, mock_dependencies):
        """Rapid updates within debounce window are blocked.

        Uses mocked datetime to simulate time progression deterministically.
        """
        from unittest.mock import patch
        from datetime import timedelta

        redis, risk_registry, account_manager = mock_dependencies
        service = AccountMetricsService(redis, risk_registry, account_manager)

        # Create a controlled timestamp
        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("src.accounts.metrics_service.datetime") as mock_dt:
            # First update at T=0
            mock_dt.now.return_value = base_time
            await service.on_mt5_balance_update(
                "test-001", Decimal("100000"), Decimal("100000")
            )

            # Second update at T=50ms (within 100ms debounce window)
            mock_dt.now.return_value = base_time + timedelta(milliseconds=50)
            await service.on_mt5_balance_update(
                "test-001", Decimal("100001"), Decimal("100001")
            )

            # Only first update should have been processed
            assert redis.save_account_balance.call_count == 1
            assert risk_registry.update_account_equity.call_count == 1

    @pytest.mark.asyncio
    async def test_debounce_allows_after_window_expires(self, mock_dependencies):
        """Updates after debounce window expires are processed.

        Verifies that after waiting past the debounce window (100ms),
        subsequent updates are allowed.
        """
        from unittest.mock import patch
        from datetime import timedelta

        redis, risk_registry, account_manager = mock_dependencies
        service = AccountMetricsService(redis, risk_registry, account_manager)

        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("src.accounts.metrics_service.datetime") as mock_dt:
            # First update at T=0
            mock_dt.now.return_value = base_time
            await service.on_mt5_balance_update(
                "test-001", Decimal("100000"), Decimal("100000")
            )

            # Second update at T=150ms (after 100ms debounce window)
            mock_dt.now.return_value = base_time + timedelta(milliseconds=150)
            await service.on_mt5_balance_update(
                "test-001", Decimal("100001"), Decimal("100001")
            )

            # Both updates should have been processed
            assert redis.save_account_balance.call_count == 2
            assert risk_registry.update_account_equity.call_count == 2

    @pytest.mark.asyncio
    async def test_debounce_allows_different_accounts(self, mock_dependencies):
        """Different accounts can update within debounce window.

        Per-account debouncing means account A's debounce state
        doesn't affect account B.
        """
        from unittest.mock import patch

        redis, risk_registry, account_manager = mock_dependencies
        service = AccountMetricsService(redis, risk_registry, account_manager)

        base_time = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)

        with patch("src.accounts.metrics_service.datetime") as mock_dt:
            mock_dt.now.return_value = base_time

            # Update account A
            await service.on_mt5_balance_update(
                "account-a", Decimal("100000"), Decimal("100000")
            )

            # Update account B immediately (should succeed - different account)
            await service.on_mt5_balance_update(
                "account-b", Decimal("50000"), Decimal("50000")
            )

            # Both updates should have been processed
            assert redis.save_account_balance.call_count == 2
            assert risk_registry.update_account_equity.call_count == 2
