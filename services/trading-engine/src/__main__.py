"""Trading Engine Entry Point."""

import sys

from src.cli import app


def _force_utf8_stdio() -> None:
    """Make stdout/stderr encode the non-ASCII glyphs the CLI summaries use.

    Windows consoles default to cp1252, which has no code point for the arrows
    and check marks in the run/AB summaries — printing one raises
    ``UnicodeEncodeError`` and kills the command *after* the backtest has
    already run. ``errors="replace"`` keeps output alive on any terminal that
    still cannot render a glyph.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


if __name__ == "__main__":
    _force_utf8_stdio()
    app()
