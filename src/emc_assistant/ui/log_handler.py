"""The logging-seam UI handler (logging_design.md step 5).

A ``logging.Handler`` that captures the ``emc_assistant.*`` operational
stream for the desktop UI. Each record becomes a plain dict
``{timestamp, level, component, message}``; the UI thread drains the
queue and renders it (colouring by ``level``, filterable by
``component``).

Installed via ``configure_logging(ui_handler=QueueLogHandler())`` at UI
startup. Thread-safe — service work runs on a worker thread, the UI
drains on the UI thread; ``queue.Queue`` is the only channel.

Operational logs only: per the privacy boundary, records never carry
schematic / netlist content — only progress, warnings, errors.
"""

from __future__ import annotations

import logging
import queue
from datetime import datetime, timezone
from typing import Callable

_ROOT_PREFIX = "emc_assistant."


def record_to_dict(record: logging.LogRecord) -> dict:
    """Render a ``LogRecord`` as the UI's plain-dict shape."""
    return {
        "timestamp": datetime.fromtimestamp(
            record.created, timezone.utc
        ).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "level": record.levelname,
        "component": record.name.removeprefix(_ROOT_PREFIX),
        "message": record.getMessage(),
    }


class QueueLogHandler(logging.Handler):
    """Capture log records for the UI.

    Default mode buffers records in a thread-safe queue; the UI calls
    :meth:`drain` to collect everything pending. Pass ``callback`` to be
    notified per record instead (the callback must be cheap and must not
    raise — it runs on the logging thread).
    """

    def __init__(
        self,
        callback: Callable[[dict], None] | None = None,
        *,
        maxsize: int = 0,
    ) -> None:
        super().__init__()
        self._queue: "queue.Queue[dict]" = queue.Queue(maxsize=maxsize)
        self._callback = callback

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = record_to_dict(record)
        except Exception:  # noqa: BLE001 - logging must never raise
            self.handleError(record)
            return
        if self._callback is not None:
            try:
                self._callback(entry)
            except Exception:  # noqa: BLE001 - a bad callback must not break logging
                pass
            return
        try:
            self._queue.put_nowait(entry)
        except queue.Full:  # pragma: no cover - only with a bounded queue
            pass

    def drain(self) -> list[dict]:
        """Return every buffered record and clear the queue."""
        out: list[dict] = []
        while True:
            try:
                out.append(self._queue.get_nowait())
            except queue.Empty:
                break
        return out

    @property
    def pending(self) -> int:
        """Approximate number of buffered records (queue mode)."""
        return self._queue.qsize()
