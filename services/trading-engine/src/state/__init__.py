"""State module - State management.

This module handles:
- Redis state snapshots
- Position reconciliation
- Crash recovery state
- Account status persistence

Exports:
- RedisStateManager: Async Redis state persistence
"""

from .redis_state import RedisStateManager

__all__ = ["RedisStateManager"]
