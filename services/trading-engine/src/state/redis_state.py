"""Redis state management for account status persistence."""

import json
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import redis.asyncio as aioredis

if TYPE_CHECKING:
    from decimal import Decimal

    from ..accounts.risk_state import RiskState


class RedisStateManager:
    """Manages account state persistence in Redis.

    Uses key pattern: account:{account_id}:status

    This class provides async Redis operations for:
    - Saving account status
    - Retrieving account status
    - Listing all account statuses
    """

    # TTL constants for risk state keys
    RISK_STATE_TTL_SECONDS = 60 * 60 * 24 * 7  # 7 days
    RISK_VIOLATION_TTL_SECONDS = 60 * 60 * 24 * 90  # 90 days
    RISK_VIOLATION_MAX_ENTRIES = 1000  # Keep last N violations

    def __init__(self, redis_url: str = "redis://localhost:6379") -> None:
        """Initialize RedisStateManager.

        Args:
            redis_url: Redis connection URL.
        """
        self.redis_url = redis_url
        self._client: aioredis.Redis | None = None

    async def connect(self) -> None:
        """Establish Redis connection."""
        self._client = await aioredis.from_url(
            self.redis_url,
            encoding="utf-8",
            decode_responses=True,
        )

    @property
    def client(self) -> aioredis.Redis:
        """Get Redis client, raising if not connected.

        Returns:
            Connected Redis client.

        Raises:
            RuntimeError: If not connected.
        """
        if self._client is None:
            raise RuntimeError("Redis not connected. Call connect() first.")
        return self._client

    async def save_account_status(self, account_id: str, status: str) -> None:
        """Save account status to Redis.

        Args:
            account_id: Account identifier.
            status: Status value to save.
        """
        key = f"account:{account_id}:status"
        await self.client.set(key, status)

    async def get_account_status(self, account_id: str) -> str | None:
        """Get account status from Redis.

        Args:
            account_id: Account identifier.

        Returns:
            Status value or None if not found.
        """
        key = f"account:{account_id}:status"
        return await self.client.get(key)

    async def get_all_account_statuses(self) -> dict[str, str]:
        """Get all account statuses using SCAN.

        Returns:
            Dictionary of account_id -> status.
        """
        statuses: dict[str, str] = {}
        async for key in self.client.scan_iter("account:*:status"):
            # Extract account_id from key pattern account:{id}:status
            parts = key.split(":")
            if len(parts) == 3:
                account_id = parts[1]
                status = await self.client.get(key)
                if status:
                    statuses[account_id] = status
        return statuses

    async def delete_account_status(self, account_id: str) -> None:
        """Delete account status from Redis.

        Args:
            account_id: Account identifier.
        """
        key = f"account:{account_id}:status"
        await self.client.delete(key)

    async def update_account_health(
        self, account_id: str, health_data: dict[str, str]
    ) -> None:
        """Update account health hash with TTL.

        Args:
            account_id: Account identifier.
            health_data: Health data dict (last_heartbeat, status, etc.)
        """
        key = f"account:{account_id}:health"
        await self.client.hset(key, mapping=health_data)
        await self.client.expire(key, 60)  # 60 second TTL

    async def get_account_health(self, account_id: str) -> dict[str, str] | None:
        """Get account health data.

        Args:
            account_id: Account identifier.

        Returns:
            Health data dict or None if not found.
        """
        key = f"account:{account_id}:health"
        data = await self.client.hgetall(key)
        return data if data else None

    async def clear_account_health(self, account_id: str) -> None:
        """Clear account health data.

        Args:
            account_id: Account identifier.
        """
        key = f"account:{account_id}:health"
        await self.client.delete(key)

    async def save_account_last_error(self, account_id: str, error: str) -> None:
        """Save last error for account.

        Args:
            account_id: Account identifier.
            error: Error message to save.
        """
        key = f"account:{account_id}:last_error"
        await self.client.set(key, error)

    async def get_account_last_error(self, account_id: str) -> str | None:
        """Get last error for account.

        Args:
            account_id: Account identifier.

        Returns:
            Last error message or None if not found.
        """
        key = f"account:{account_id}:last_error"
        return await self.client.get(key)

    async def publish_alert(
        self, account_id: str, alert_type: str, message: str
    ) -> None:
        """Publish alert to Redis pub/sub channel.

        Channel format: alerts:{alert_type}:{account_id}

        Args:
            account_id: Account identifier.
            alert_type: Type of alert (e.g., "error").
            message: Alert message.
        """
        channel = f"alerts:{alert_type}:{account_id}"
        payload = json.dumps(
            {
                "account_id": account_id,
                "alert_type": alert_type,
                "message": message,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        )
        await self.client.publish(channel, payload)

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # Risk State Management Methods

    async def save_risk_state(self, account_id: str, state: "RiskState") -> None:
        """Save risk state to Redis hash with TTL.

        Key pattern: risk:{account_id}:state
        TTL: 7 days (auto-cleanup of stale data)

        Args:
            account_id: Account identifier
            state: RiskState to persist
        """
        key = f"risk:{account_id}:state"
        await self.client.hset(key, mapping=state.to_dict())
        await self.client.expire(key, self.RISK_STATE_TTL_SECONDS)

    async def get_risk_state(self, account_id: str) -> "RiskState | None":
        """Get risk state from Redis.

        Args:
            account_id: Account identifier

        Returns:
            RiskState if found, None otherwise
        """
        from ..accounts.risk_state import RiskState

        key = f"risk:{account_id}:state"
        data = await self.client.hgetall(key)
        if not data:
            return None
        return RiskState.from_dict(data)

    async def reset_daily_risk_state(self, account_id: str) -> None:
        """Reset daily metrics in risk state at midnight UTC.

        Preserves peak_equity and total_drawdown, resets daily counters.

        Args:
            account_id: Account identifier
        """
        key = f"risk:{account_id}:state"
        await self.client.hset(
            key,
            mapping={
                "daily_pnl": "0",
                "daily_pnl_percent": "0",
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def record_risk_violation(
        self,
        account_id: str,
        rule_type: str,
        current_value: str,
        limit_value: str,
    ) -> None:
        """Record rule violation to Redis list for audit trail.

        Key pattern: risk:{account_id}:violations
        TTL: 90 days

        Args:
            account_id: Account that violated rule
            rule_type: Type of rule violated (daily_loss, max_drawdown)
            current_value: Current metric value at violation
            limit_value: Limit that was exceeded
        """
        key = f"risk:{account_id}:violations"
        violation = json.dumps({
            "rule_type": rule_type,
            "current_value": current_value,
            "limit_value": limit_value,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        await self.client.lpush(key, violation)
        await self.client.ltrim(key, 0, self.RISK_VIOLATION_MAX_ENTRIES - 1)
        await self.client.expire(key, self.RISK_VIOLATION_TTL_SECONDS)

    # Account Balance Management Methods (Story 3.6)

    async def save_account_balance(
        self, account_id: str, balance: "Decimal"
    ) -> None:
        """Save account balance to Redis.

        Key pattern: account:{account_id}:balance

        Args:
            account_id: Account identifier
            balance: Balance value (stored as string for precision)
        """
        key = f"account:{account_id}:balance"
        await self.client.set(key, str(balance))

    async def get_account_balance(self, account_id: str) -> "Decimal | None":
        """Get account balance from Redis.

        Args:
            account_id: Account identifier

        Returns:
            Decimal balance if found, None otherwise
        """
        from decimal import Decimal

        key = f"account:{account_id}:balance"
        value = await self.client.get(key)
        if value is None:
            return None
        return Decimal(value)

    async def get_all_account_balances(self) -> "dict[str, Decimal]":
        """Get balances for all accounts.

        Scans for all balance keys and returns a dict.

        Returns:
            Dict mapping account_id to balance
        """
        from decimal import Decimal

        balances: dict[str, Decimal] = {}
        async for key in self.client.scan_iter("account:*:balance"):
            # Extract account_id from key pattern account:{id}:balance
            parts = key.split(":")
            if len(parts) == 3:
                account_id = parts[1]
                value = await self.client.get(key)
                if value:
                    balances[account_id] = Decimal(value)
        return balances
