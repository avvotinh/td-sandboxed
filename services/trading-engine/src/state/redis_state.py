"""Redis state management for account status persistence."""

import redis.asyncio as aioredis


class RedisStateManager:
    """Manages account state persistence in Redis.

    Uses key pattern: account:{account_id}:status

    This class provides async Redis operations for:
    - Saving account status
    - Retrieving account status
    - Listing all account statuses
    """

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

    async def close(self) -> None:
        """Close Redis connection gracefully."""
        if self._client:
            await self._client.aclose()
            self._client = None
