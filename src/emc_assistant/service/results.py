"""Shared types for the service layer.

Service functions return typed result dataclasses (defined in each
service module) and raise :class:`ServiceError` for expected,
user-facing failures. The CLI adapter maps a ``ServiceError`` to its
``exit_code``; the M3 UI renders ``message`` (and ``details``).
"""

from __future__ import annotations


class ServiceError(Exception):
    """An expected, user-facing failure — bad project config, a missing
    input file, an invalid mode, a schema violation.

    Distinct from an unexpected bug: a bug propagates as its own
    exception. The CLI adapter catches ``ServiceError`` and returns
    ``exit_code``; the UI shows ``message`` and any ``details`` lines.
    """

    def __init__(
        self,
        message: str,
        *,
        exit_code: int = 1,
        details: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.exit_code = exit_code
        self.details: list[str] = list(details or [])
