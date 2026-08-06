"""Entry-point stdio encoding guard.

Regression test for the cp1252 crash: the run/AB summaries print ``→`` and the
account commands print ``✓``/``✗``, none of which cp1252 can encode. On a
Windows console that raised ``UnicodeEncodeError`` *after* a multi-minute
backtest had already completed, losing the result.
"""

from __future__ import annotations

import io

from src.__main__ import _force_utf8_stdio


class _Recorder(io.StringIO):
    """Stand-in for a text stream that records ``reconfigure`` calls."""

    def __init__(self) -> None:
        super().__init__()
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:  # type: ignore[override]
        self.calls.append(kwargs)


class _NoReconfigure:
    """A stream without ``reconfigure`` — e.g. a pytest capture object."""


def test_reconfigures_stdout_and_stderr_to_utf8(monkeypatch) -> None:
    stdout, stderr = _Recorder(), _Recorder()
    monkeypatch.setattr("sys.stdout", stdout)
    monkeypatch.setattr("sys.stderr", stderr)

    _force_utf8_stdio()

    for stream in (stdout, stderr):
        assert stream.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_tolerates_streams_without_reconfigure(monkeypatch) -> None:
    monkeypatch.setattr("sys.stdout", _NoReconfigure())
    monkeypatch.setattr("sys.stderr", _NoReconfigure())

    _force_utf8_stdio()  # must not raise


def test_summary_glyphs_survive_the_configured_encoding() -> None:
    """The glyphs the CLI actually prints must round-trip under utf-8/replace."""
    buffer = io.TextIOWrapper(io.BytesIO(), encoding="utf-8", errors="replace")
    buffer.write("Window: a → b  ✓ ok  ✗ fail")
    buffer.flush()  # cp1252 would raise UnicodeEncodeError here
