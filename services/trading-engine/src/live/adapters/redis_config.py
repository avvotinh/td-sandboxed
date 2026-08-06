"""Redis adapter configuration.

Uses pydantic-settings for environment variable support.
"""

from pydantic import Field
from pydantic_settings import BaseSettings


class RedisConfig(BaseSettings):
    """Redis adapter configuration.

    Configuration for Redis connection and reconnection behavior.
    Supports environment variables.

    Attributes:
        redis_url: Redis connection URL (env: REDIS_URL)
        recv_timeout_ms: Receive timeout in milliseconds (0 = no timeout)
        reconnect_delays: Exponential backoff delays in seconds

    Example:
        # Default configuration
        config = RedisConfig()

        # With custom URL (from constructor)
        config = RedisConfig(redis_url="redis://redis-host:6379/0")

        # Environment variable: REDIS_URL=redis://myhost:6379
    """

    redis_url: str = Field(
        default="redis://localhost:6379",
        description="Redis connection URL (env: REDIS_URL)",
        alias="REDIS_URL",
    )
    recv_timeout_ms: int = Field(
        default=0,
        description="Receive timeout in milliseconds (0 = no timeout for pub/sub)",
    )
    reconnect_delays: list[int] = Field(
        default=[1, 2, 4, 8, 16, 30],
        description="Exponential backoff delays in seconds for reconnection",
    )
    max_reconnect_attempts: int = Field(
        default=0,
        description="Maximum reconnection attempts (0 = unlimited)",
    )

    model_config = {
        "extra": "ignore",
        "populate_by_name": True,  # Allow both redis_url and REDIS_URL as kwargs
    }
