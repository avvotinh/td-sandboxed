"""Lock-loss mediator — breaks the circular dependency between
:class:`CrashRecoveryManager` (which needs an ``on_lock_lost`` callback at
construction time) and :class:`EngineLifecycle._on_lock_lost` (which needs
the orchestrators to already exist).

Story 10.2 introduces this indirection so the DI container can build the
crash-recovery manager eagerly. The mediator starts with a no-op handler;
the lifecycle binds its real handler once both objects exist.
"""
from __future__ import annotations

from collections.abc import Callable


class LockLostMediator:
    """Bindable callback shim invoked when the engine's process lock is lost."""

    def __init__(self) -> None:
        self._handler: Callable[[], None] | None = None

    def bind(self, handler: Callable[[], None]) -> None:
        """Bind the real handler. Idempotent — last bind wins."""
        self._handler = handler

    def __call__(self) -> None:
        if self._handler is not None:
            self._handler()
