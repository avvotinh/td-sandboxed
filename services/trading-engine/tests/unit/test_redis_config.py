"""Unit tests for Redis configuration.

Tests cover:
- Default configuration values
- Custom configuration values
- Environment variable support
- Reconnect delays configuration
"""

from __future__ import annotations

import os
from unittest.mock import patch

import pytest

from src.adapters.redis_config import RedisConfig


class TestRedisConfigDefaults:
    """Tests for RedisConfig default values."""

    def test_default_redis_url(self):
        """Test default Redis URL."""
        config = RedisConfig()
        assert config.redis_url == "redis://localhost:6379"

    def test_default_recv_timeout(self):
        """Test default receive timeout is 0 (no timeout)."""
        config = RedisConfig()
        assert config.recv_timeout_ms == 0

    def test_default_reconnect_delays(self):
        """Test default reconnect delay sequence."""
        config = RedisConfig()
        assert config.reconnect_delays == [1, 2, 4, 8, 16, 30]


class TestRedisConfigCustom:
    """Tests for RedisConfig custom values."""

    def test_custom_redis_url(self):
        """Test custom Redis URL."""
        config = RedisConfig(redis_url="redis://redis-host:6380/1")
        assert config.redis_url == "redis://redis-host:6380/1"

    def test_custom_recv_timeout(self):
        """Test custom receive timeout."""
        config = RedisConfig(recv_timeout_ms=5000)
        assert config.recv_timeout_ms == 5000

    def test_custom_reconnect_delays(self):
        """Test custom reconnect delays."""
        config = RedisConfig(reconnect_delays=[0, 1, 5, 10])
        assert config.reconnect_delays == [0, 1, 5, 10]

    def test_redis_url_with_auth(self):
        """Test Redis URL with authentication."""
        config = RedisConfig(redis_url="redis://user:password@host:6379")
        assert config.redis_url == "redis://user:password@host:6379"

    def test_redis_url_with_database(self):
        """Test Redis URL with database selection."""
        config = RedisConfig(redis_url="redis://localhost:6379/2")
        assert config.redis_url == "redis://localhost:6379/2"


class TestRedisConfigFromDict:
    """Tests for RedisConfig from dictionary."""

    def test_config_from_dict(self):
        """Test configuration can be created from dict."""
        data = {
            "redis_url": "redis://remote-host:6379",
            "recv_timeout_ms": 2000,
        }
        config = RedisConfig(**data)
        assert config.redis_url == "redis://remote-host:6379"
        assert config.recv_timeout_ms == 2000

    def test_config_partial_dict(self):
        """Test configuration with partial dict uses defaults."""
        data = {"redis_url": "redis://custom:6379"}
        config = RedisConfig(**data)
        assert config.redis_url == "redis://custom:6379"
        assert config.recv_timeout_ms == 0  # default
        assert config.reconnect_delays == [1, 2, 4, 8, 16, 30]  # default


class TestRedisConfigEnvironment:
    """Tests for RedisConfig environment variable support."""

    def test_redis_url_from_env(self):
        """Test REDIS_URL environment variable is used."""
        with patch.dict(os.environ, {"REDIS_URL": "redis://env-host:6379/3"}, clear=True):
            config = RedisConfig()
            assert config.redis_url == "redis://env-host:6379/3"

    def test_explicit_value_overrides_env(self):
        """Test explicit value overrides environment variable."""
        with patch.dict(os.environ, {"REDIS_URL": "redis://env-host:6379"}, clear=True):
            config = RedisConfig(redis_url="redis://explicit:6379")
            assert config.redis_url == "redis://explicit:6379"


class TestRedisConfigMaxReconnectAttempts:
    """Tests for max reconnect attempts configuration."""

    def test_default_max_reconnect_attempts(self):
        """Test default max_reconnect_attempts is 0 (unlimited)."""
        config = RedisConfig()
        assert config.max_reconnect_attempts == 0

    def test_custom_max_reconnect_attempts(self):
        """Test custom max_reconnect_attempts."""
        config = RedisConfig(max_reconnect_attempts=10)
        assert config.max_reconnect_attempts == 10


class TestRedisConfigReconnectDelays:
    """Tests for reconnect delay configuration."""

    def test_empty_reconnect_delays(self):
        """Test empty reconnect delays list is valid."""
        config = RedisConfig(reconnect_delays=[])
        assert config.reconnect_delays == []

    def test_single_reconnect_delay(self):
        """Test single reconnect delay."""
        config = RedisConfig(reconnect_delays=[5])
        assert config.reconnect_delays == [5]

    def test_reconnect_delay_max_calculation(self):
        """Test max delay is last element."""
        config = RedisConfig(reconnect_delays=[1, 2, 4, 8, 16, 30, 60])
        max_delay = config.reconnect_delays[-1]
        assert max_delay == 60

    def test_reconnect_delay_sequence_used_for_backoff(self):
        """Test delays can be used for exponential backoff."""
        config = RedisConfig()
        # Verify first delay is 1 second
        assert config.reconnect_delays[0] == 1
        # Verify last delay is 30 seconds
        assert config.reconnect_delays[-1] == 30
        # Verify 6 delays in sequence
        assert len(config.reconnect_delays) == 6
