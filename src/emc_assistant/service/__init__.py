"""Application service layer — the core both front-ends call.

The CLI (``cli.py``) is a thin argparse adapter over this package; the M3
desktop UI calls the same functions in-process. Service functions:

- take **plain parameters** (never an ``argparse.Namespace``),
- emit progress / warnings / errors through the logging seam
  (``emc_assistant.logging_setup``),
- return a **typed result** dataclass (never an exit code),
- raise :class:`ServiceError` for expected, user-facing failures.

This keeps the use-case orchestration in one place; the domain packages
(``project``, ``parasitics``, ``testbench``, ``ltspice``, ``results``,
``recommendations``, ``reports``, ``knowledge``, ``agents``) stay focused
on domain logic.
"""

from __future__ import annotations

from emc_assistant.service import (
    context,
    knowledge,
    netlist,
    options,
    parasitics,
    pipeline,
    project,
    raw,
    recommendations,
    report,
    resolve,
    simulate,
    testbench,
    waveform,
)
from emc_assistant.service.options import CommandOptions
from emc_assistant.service.results import ServiceError

__all__ = [
    "ServiceError",
    "CommandOptions",
    "context",
    "knowledge",
    "netlist",
    "options",
    "parasitics",
    "pipeline",
    "project",
    "raw",
    "recommendations",
    "report",
    "resolve",
    "simulate",
    "testbench",
    "waveform",
]
