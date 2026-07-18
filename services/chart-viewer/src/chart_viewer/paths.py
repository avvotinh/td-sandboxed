"""Repo-root discovery + path-traversal guards.

Result Contract v2 ``run.data_ref`` values are RELATIVE TO THE REPO
ROOT (see ``docs/v2/01-architecture.md`` §4). The viewer must not
import trading-engine code, so this is a small local copy of the
``repo_root()`` convention from
``services/trading-engine/src/backtesting/job_config.py``.
"""

from __future__ import annotations

import os
from pathlib import Path

_REPO_ROOT_ENV = "TD_REPO_ROOT"


def repo_root() -> Path:
    """Locate the repository root for resolving relative data paths.

    Resolution order:

    1. ``TD_REPO_ROOT`` env var (explicit override).
    2. Walk up from this module's file to the first directory
       containing ``.git``.
    3. Fallback to the current working directory.
    """
    override = os.environ.get(_REPO_ROOT_ENV)
    if override:
        return Path(override)
    here = Path(__file__).resolve().parent
    for candidate in (here, *here.parents):
        if (candidate / ".git").exists():
            return candidate
    return Path.cwd()


class PathOutsideRepoError(ValueError):
    """A data reference resolved to a path outside the repo root."""


def resolve_within_repo(ref: str, root: Path) -> Path:
    """Resolve ``ref`` against ``root``; reject anything escaping it.

    Relative refs resolve under ``root``; absolute refs are accepted
    only when they already point inside ``root``. Anything that
    resolves outside (``..`` segments, absolute paths elsewhere,
    drive-relative tricks) raises :class:`PathOutsideRepoError`.
    """
    root_resolved = root.resolve()
    candidate = Path(ref)
    if not candidate.is_absolute():
        candidate = root_resolved / candidate
    resolved = candidate.resolve()
    if not resolved.is_relative_to(root_resolved):
        raise PathOutsideRepoError(
            f"data reference escapes the repo root: {ref!r}"
        )
    return resolved
