"""Statically verify every intra-`src` import resolves to a module that exists.

Catches the reorganize failure mode that import smoke tests miss: a relative
import whose depth changed now resolves to a *different* package that happens
to exist, or to nothing at all. Pure AST + filesystem, so it sees every import
including ones behind `if TYPE_CHECKING:` and function-local imports.

Run from services/trading-engine/.
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path("src")


def known_modules() -> set[str]:
    names: set[str] = set()
    for path in SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        parts = list(path.with_suffix("").parts)
        if parts[-1] == "__init__":
            parts.pop()
        names.add(".".join(parts))
        # every package prefix is importable too
        for i in range(1, len(parts)):
            names.add(".".join(parts[:i]))
    return names


def package_parts(path: Path) -> list[str]:
    parts = list(path.with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
        return parts
    return parts[:-1]


def main() -> int:
    modules = known_modules()
    broken: list[str] = []
    checked = 0

    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_bytes().decode("utf-8"))
        except SyntaxError as exc:
            broken.append(f"{path}: syntax error: {exc}")
            continue

        pkg = package_parts(path)
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.ImportFrom):
                if node.level:
                    base = pkg[: len(pkg) - (node.level - 1)]
                    target = ".".join([*base, node.module] if node.module else base)
                else:
                    target = node.module or ""
                targets = [target]
            elif isinstance(node, ast.Import):
                targets = [a.name for a in node.names]

            for target in targets:
                if not target.startswith("src"):
                    continue
                checked += 1
                # No parent fallback: in `from A.B import C` and `import A.B`,
                # A.B must itself be a module. Accepting a resolvable parent
                # hides exactly the case this check exists for — a submodule
                # that moved out from under its package.
                if target in modules:
                    continue
                broken.append(f"{path}:{node.lineno}: cannot resolve {target!r}")

    print(f"checked {checked} intra-src imports across {len(modules)} known modules")
    if broken:
        print(f"\n{len(broken)} UNRESOLVABLE:")
        for line in broken:
            print(f"  {line}")
        return 1
    print("all imports resolve")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
