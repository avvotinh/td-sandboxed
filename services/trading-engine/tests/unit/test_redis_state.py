"""Tests for RedisStateManager class with mocked Redis."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.state.redis_state import RedisStateManager


@pytest.fixture
def mock_redis_client():
    """Create a mock Redis client."""
    client = MagicMock()
    client.set = AsyncMock()
    client.get = AsyncMock()
    client.delete = AsyncMock()
    client.aclose = AsyncMock()
    return client


@pytest.fixture
def redis_manager():
    """Create RedisStateManager instance."""
    return RedisStateManager("redis://localhost:6379")


class TestRedisStateManagerInit:
    """Tests for RedisStateManager initialization."""

    def test_init_default_url(self):
        """Test default Redis URL."""
        manager = RedisStateManager()
        assert manager.redis_url == "redis://localhost:6379"

    def test_init_custom_url(self):
        """Test custom Redis URL."""
        manager = RedisStateManager("redis://custom:6380")
        assert manager.redis_url == "redis://custom:6380"

    def test_client_none_before_connect(self, redis_manager):
        """Test client is None before connect."""
        assert redis_manager._client is None


class TestRedisStateManagerConnect:
    """Tests for connect method."""

    @pytest.mark.asyncio
    async def test_connect_creates_client(self, redis_manager):
        """Test connect creates Redis client."""
        with patch("src.state.redis_state.aioredis") as mock_aioredis:
            mock_client = MagicMock()
            # from_url needs to be an async function
            async_from_url = AsyncMock(return_value=mock_client)
            mock_aioredis.from_url = async_from_url

            await redis_manager.connect()

            async_from_url.assert_called_once_with(
                "redis://localhost:6379",
                encoding="utf-8",
                decode_responses=True,
            )
            assert redis_manager._client == mock_client


class TestRedisStateManagerClient:
    """Tests for client property."""

    def test_client_raises_when_not_connected(self, redis_manager):
        """Test client property raises when not connected."""
        with pytest.raises(RuntimeError) as exc_info:
            _ = redis_manager.client
        assert "not connected" in str(exc_info.value)

    def test_client_returns_when_connected(self, redis_manager, mock_redis_client):
        """Test client property returns client when connected."""
        redis_manager._client = mock_redis_client
        assert redis_manager.client == mock_redis_client


class TestRedisStateManagerSaveStatus:
    """Tests for save_account_status method."""

    @pytest.mark.asyncio
    async def test_save_account_status(self, redis_manager, mock_redis_client):
        """Test saving account status."""
        redis_manager._client = mock_redis_client

        await redis_manager.save_account_status("test-001", "active")

        mock_redis_client.set.assert_called_once_with(
            "account:test-001:status", "active"
        )

    @pytest.mark.asyncio
    async def test_save_status_key_format(self, redis_manager, mock_redis_client):
        """Test key format is correct."""
        redis_manager._client = mock_redis_client

        await redis_manager.save_account_status("my-account", "paused")

        call_args = mock_redis_client.set.call_args
        key = call_args[0][0]
        assert key == "account:my-account:status"


class TestRedisStateManagerGetStatus:
    """Tests for get_account_status method."""

    @pytest.mark.asyncio
    async def test_get_account_status_found(self, redis_manager, mock_redis_client):
        """Test getting existing account status."""
        redis_manager._client = mock_redis_client
        mock_redis_client.get.return_value = "active"

        status = await redis_manager.get_account_status("test-001")

        assert status == "active"
        mock_redis_client.get.assert_called_once_with("account:test-001:status")

    @pytest.mark.asyncio
    async def test_get_account_status_not_found(self, redis_manager, mock_redis_client):
        """Test getting nonexistent account status."""
        redis_manager._client = mock_redis_client
        mock_redis_client.get.return_value = None

        status = await redis_manager.get_account_status("nonexistent")

        assert status is None


class TestRedisStateManagerGetAllStatuses:
    """Tests for get_all_account_statuses method."""

    @pytest.mark.asyncio
    async def test_get_all_statuses(self, redis_manager, mock_redis_client):
        """Test getting all account statuses."""
        redis_manager._client = mock_redis_client

        # Mock scan_iter to return keys
        async def mock_scan_iter(pattern):
            for key in ["account:test-001:status", "account:test-002:status"]:
                yield key

        mock_redis_client.scan_iter = mock_scan_iter
        mock_redis_client.get.side_effect = ["active", "paused"]

        statuses = await redis_manager.get_all_account_statuses()

        assert len(statuses) == 2
        assert statuses["test-001"] == "active"
        assert statuses["test-002"] == "paused"

    @pytest.mark.asyncio
    async def test_get_all_statuses_empty(self, redis_manager, mock_redis_client):
        """Test getting all statuses when none exist."""
        redis_manager._client = mock_redis_client

        async def mock_scan_iter(pattern):
            return
            yield  # Make it a generator that yields nothing

        mock_redis_client.scan_iter = mock_scan_iter

        statuses = await redis_manager.get_all_account_statuses()

        assert statuses == {}

    @pytest.mark.asyncio
    async def test_get_all_statuses_filters_none_values(
        self, redis_manager, mock_redis_client
    ):
        """Test that None values are filtered out."""
        redis_manager._client = mock_redis_client

        async def mock_scan_iter(pattern):
            for key in ["account:test-001:status", "account:test-002:status"]:
                yield key

        mock_redis_client.scan_iter = mock_scan_iter
        mock_redis_client.get.side_effect = ["active", None]

        statuses = await redis_manager.get_all_account_statuses()

        assert len(statuses) == 1
        assert statuses["test-001"] == "active"


class TestRedisStateManagerDeleteStatus:
    """Tests for delete_account_status method."""

    @pytest.mark.asyncio
    async def test_delete_account_status(self, redis_manager, mock_redis_client):
        """Test deleting account status."""
        redis_manager._client = mock_redis_client

        await redis_manager.delete_account_status("test-001")

        mock_redis_client.delete.assert_called_once_with("account:test-001:status")


class TestRedisStateManagerClose:
    """Tests for close method."""

    @pytest.mark.asyncio
    async def test_close_when_connected(self, redis_manager, mock_redis_client):
        """Test close when connected."""
        redis_manager._client = mock_redis_client

        await redis_manager.close()

        mock_redis_client.aclose.assert_called_once()
        assert redis_manager._client is None

    @pytest.mark.asyncio
    async def test_close_when_not_connected(self, redis_manager):
        """Test close when not connected does nothing."""
        await redis_manager.close()  # Should not raise
        assert redis_manager._client is None


class TestRedisKeyPatterns:
    """Tests for Redis key pattern compliance."""

    @pytest.mark.asyncio
    async def test_key_pattern_format(self, redis_manager, mock_redis_client):
        """Test key follows pattern account:{account_id}:status."""
        redis_manager._client = mock_redis_client

        test_cases = [
            ("ftmo-gold-001", "account:ftmo-gold-001:status"),
            ("my_account", "account:my_account:status"),
            ("account123", "account:account123:status"),
        ]

        for account_id, expected_key in test_cases:
            mock_redis_client.set.reset_mock()
            await redis_manager.save_account_status(account_id, "active")
            call_args = mock_redis_client.set.call_args[0]
            assert call_args[0] == expected_key, f"Failed for {account_id}"


class TestRiskStateMethods:
    """Tests for risk state management methods (Story 3.5)."""

    @pytest.fixture
    def mock_redis_client_with_hash(self):
        """Create a mock Redis client with hash operations."""
        client = MagicMock()
        client.hset = AsyncMock()
        client.hgetall = AsyncMock(return_value={})
        client.expire = AsyncMock()
        client.lpush = AsyncMock()
        client.ltrim = AsyncMock()
        return client

    @pytest.mark.asyncio
    async def test_save_risk_state(self, redis_manager, mock_redis_client_with_hash):
        """Test saving risk state to Redis hash."""
        from src.accounts.risk_state import RiskState

        redis_manager._client = mock_redis_client_with_hash
        state = RiskState(
            daily_pnl="-1000",
            current_equity="99000",
        )

        await redis_manager.save_risk_state("test-001", state)

        # Verify hset called with correct key (positional arg)
        call_args = mock_redis_client_with_hash.hset.call_args
        assert call_args[0][0] == "risk:test-001:state"

        # Verify TTL set to configured value
        mock_redis_client_with_hash.expire.assert_called_once()
        expire_args = mock_redis_client_with_hash.expire.call_args[0]
        assert expire_args[0] == "risk:test-001:state"
        assert expire_args[1] == redis_manager.RISK_STATE_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_get_risk_state_found(self, redis_manager, mock_redis_client_with_hash):
        """Test getting existing risk state."""
        redis_manager._client = mock_redis_client_with_hash
        mock_redis_client_with_hash.hgetall.return_value = {
            "daily_pnl": "-1000",
            "daily_pnl_percent": "-1.0",
            "current_equity": "99000",
            "peak_equity": "100000",
            "total_drawdown_percent": "1.0",
            "daily_starting_balance": "100000",
            "last_updated": "2025-12-29T00:00:00+00:00",
        }

        state = await redis_manager.get_risk_state("test-001")

        assert state is not None
        from decimal import Decimal
        assert state.daily_pnl == Decimal("-1000")
        assert state.current_equity == Decimal("99000")
        mock_redis_client_with_hash.hgetall.assert_called_once_with("risk:test-001:state")

    @pytest.mark.asyncio
    async def test_get_risk_state_not_found(self, redis_manager, mock_redis_client_with_hash):
        """Test getting nonexistent risk state returns None."""
        redis_manager._client = mock_redis_client_with_hash
        mock_redis_client_with_hash.hgetall.return_value = {}

        state = await redis_manager.get_risk_state("nonexistent")

        assert state is None

    @pytest.mark.asyncio
    async def test_reset_daily_risk_state(self, redis_manager, mock_redis_client_with_hash):
        """Test resetting daily risk metrics."""
        redis_manager._client = mock_redis_client_with_hash

        await redis_manager.reset_daily_risk_state("test-001")

        # Verify hset called with reset values (key is positional, mapping is keyword)
        call_args = mock_redis_client_with_hash.hset.call_args
        assert call_args[0][0] == "risk:test-001:state"
        mapping = call_args[1]["mapping"]
        assert mapping["daily_pnl"] == "0"
        assert mapping["daily_pnl_percent"] == "0"
        assert "last_updated" in mapping

    @pytest.mark.asyncio
    async def test_record_risk_violation(self, redis_manager, mock_redis_client_with_hash):
        """Test recording risk violation to Redis list."""
        redis_manager._client = mock_redis_client_with_hash

        await redis_manager.record_risk_violation(
            "test-001",
            "daily_loss",
            "5.5",
            "5.0",
        )

        # Verify lpush called
        mock_redis_client_with_hash.lpush.assert_called_once()
        call_args = mock_redis_client_with_hash.lpush.call_args[0]
        assert call_args[0] == "risk:test-001:violations"

        # Verify ltrim keeps last N entries
        mock_redis_client_with_hash.ltrim.assert_called_once_with(
            "risk:test-001:violations", 0, redis_manager.RISK_VIOLATION_MAX_ENTRIES - 1
        )

        # Verify TTL set to configured value
        mock_redis_client_with_hash.expire.assert_called_once()
        expire_args = mock_redis_client_with_hash.expire.call_args[0]
        assert expire_args[1] == redis_manager.RISK_VIOLATION_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_risk_state_key_pattern(self, redis_manager, mock_redis_client_with_hash):
        """Test risk state keys follow pattern risk:{account_id}:state."""
        from src.accounts.risk_state import RiskState

        redis_manager._client = mock_redis_client_with_hash

        test_accounts = ["ftmo-001", "5ers-btc", "personal"]
        for account_id in test_accounts:
            mock_redis_client_with_hash.hset.reset_mock()
            await redis_manager.save_risk_state(account_id, RiskState())

            call_args = mock_redis_client_with_hash.hset.call_args
            assert call_args[0][0] == f"risk:{account_id}:state"
