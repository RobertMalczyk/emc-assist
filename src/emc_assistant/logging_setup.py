"""Structured logging seam (see docs/design/logging_design.md).

Replaces the codebase's ad-hoc ``print()`` output with stdlib
``logging``, so both the CLI and the future M3 UI consume the same
operational stream. Components log under the ``emc_assistant.<component>``
tree; the existing ``[tag]`` prefixes stay inside the message strings.

The console handler prints ``%(message)s`` verbatim — output is
byte-identical to the old ``print()`` calls regardless of level — so the
log *level* is carried on the record (for ``--quiet`` filtering and the
M3 UI handler's severity colouring) without changing what the terminal
shows.

Operational logs must never carry schematic / netlist content or LLM
payloads — those stay in the redacted ``results/llm/*.jsonl`` privacy
log. Log net counts and roles, not net lists from a confidential design.
"""

from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

_ROOT = "emc_assistant"

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "quiet": logging.WARNING,
}


def get_logger(component: str = "cli") -> logging.Logger:
    """Return the logger for a component (``emc_assistant.<component>``)."""
    return logging.getLogger(f"{_ROOT}.{component}")


def ensure_utf8_stdio() -> None:
    """Force UTF-8 on ``sys.stdout`` / ``sys.stderr``.

    Windows consoles default to a locale code page (e.g. cp1250 on a Polish
    install) that cannot encode characters the tool routinely logs — Ω, µ, →,
    ≈, the non-breaking hyphen in LLM-written text. Without this the console
    logging handler raises ``UnicodeEncodeError`` on those lines. Call once at
    every front-end entry point (CLI *and* UI). Best-effort and idempotent.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # pragma: no cover - best effort
                pass


class _StdoutHandler(logging.StreamHandler):
    """A ``StreamHandler`` that always targets the *current* ``sys.stdout``.

    Resolving the stream at emit time — rather than capturing it once at
    construction — keeps the handler correct when ``sys.stdout`` is
    swapped: by pytest's ``capsys`` between tests, or by a UI that
    redirects output. This is what preserves the CLI's ``capsys``-based
    tests across the ``print()`` → ``logging`` migration.
    """

    def __init__(self) -> None:
        super().__init__(sys.stdout)

    @property
    def stream(self):  # type: ignore[override]
        return sys.stdout

    @stream.setter
    def stream(self, _value) -> None:  # noqa: D401 - always sys.stdout
        pass

    def emit(self, record: logging.LogRecord) -> None:
        # Pre-sanitize against the stream's own codec so a non-UTF-8 console
        # (Windows cp1250 on a Polish install) can't choke on characters the
        # tool routinely logs — Ω, µ, →, ≈, the non-breaking hyphen in
        # LLM-written text. The base StreamHandler.emit would otherwise let the
        # write raise UnicodeEncodeError and emit a "--- Logging error ---"
        # traceback per line. This is a backstop behind ensure_utf8_stdio()
        # (after which the stream is UTF-8 and the round-trip is lossless).
        try:
            stream = self.stream
            msg = self.format(record)
            enc = getattr(stream, "encoding", None)
            if enc:
                msg = msg.encode(enc, "replace").decode(enc, "replace")
            stream.write(msg + self.terminator)
            self.flush()
        except RecursionError:  # pragma: no cover - see stdlib logging
            raise
        except Exception:  # noqa: BLE001 - never let logging crash a run
            self.handleError(record)


class _JsonlFormatter(logging.Formatter):
    """One JSON object per record — for the per-run log file."""

    def format(self, record: logging.LogRecord) -> str:
        return json.dumps({
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%SZ"),
            "level": record.levelname,
            "component": record.name.removeprefix(f"{_ROOT}."),
            "message": record.getMessage(),
        }, ensure_ascii=False)


def configure_logging(
    level: str | int = "info",
    *,
    log_file: str | Path | None = None,
    ui_handler: logging.Handler | None = None,
) -> logging.Logger:
    """(Re)configure the ``emc_assistant`` logger. Idempotent.

    Called once at CLI entry / UI startup. The console handler is rebound
    to the *current* ``sys.stdout`` on every call, so it cooperates with
    pytest's ``capsys`` (each ``main()`` re-binds to the captured stream).

    - ``level`` — ``"debug"`` | ``"info"`` | ``"warning"`` / ``"quiet"``,
      or a ``logging`` level int.
    - ``log_file`` — also append a JSONL log there (the per-run file).
    - ``ui_handler`` — a handler the M3 UI installs to capture records.
    """
    lvl = _LEVELS.get(level, level) if isinstance(level, str) else level
    logger = logging.getLogger(_ROOT)
    logger.setLevel(lvl)
    logger.propagate = False  # do not double-log through the root logger

    for h in list(logger.handlers):
        logger.removeHandler(h)

    console = _StdoutHandler()
    console.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(console)

    if log_file is not None:
        fh = logging.FileHandler(Path(log_file), encoding="utf-8")
        fh.setFormatter(_JsonlFormatter())
        logger.addHandler(fh)

    if ui_handler is not None:
        logger.addHandler(ui_handler)

    return logger


def add_run_log_file(path: str | Path) -> logging.Handler:
    """Attach a per-run JSONL log file handler; return it so the caller
    can remove it when the run ends."""
    fh = logging.FileHandler(Path(path), encoding="utf-8")
    fh.setFormatter(_JsonlFormatter())
    logging.getLogger(_ROOT).addHandler(fh)
    return fh


def remove_handler(handler: logging.Handler) -> None:
    """Detach a handler added by :func:`add_run_log_file`."""
    logging.getLogger(_ROOT).removeHandler(handler)
    handler.close()
