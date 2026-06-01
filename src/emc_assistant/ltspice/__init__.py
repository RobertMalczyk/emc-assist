"""Adapter for a local LTspice installation.

MVP M0 covered path detection and dry-run only; M1 added the full
local-run pipeline (subprocess + timeout + simulation_run.json).
"""

from emc_assistant.ltspice.adapter import LtspiceAdapter, discover_ltspice
from emc_assistant.ltspice.runner import SimulationResult, run_simulation

__all__ = ["LtspiceAdapter", "discover_ltspice", "SimulationResult", "run_simulation"]
