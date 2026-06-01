"""Specialist agent layer (M2.9).

Each agent owns one engineering area (DC/DC, filtering, decoupling, …)
and consumes a slice of the project context + retrieved knowledge to
emit one ``AgentFinding`` per pipeline run. Findings land under
``results/findings/<area>.json`` and feed the report's per-area
Recommendations subsections.

The shared base class and dataclasses live in :mod:`base`; per-agent
classes live in ``<area>_agent.py`` modules. The orchestrator
(:mod:`orchestrator`) fans out to all active agents in one run.
"""

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    Risk,
    SimulationRequest,
)
from emc_assistant.agents.injection import ParasiticInjection
from emc_assistant.agents.synthesiser import (
    DiagnosticNarrative,
    FindingCluster,
    Synthesiser,
    aggregate_findings,
)

__all__ = [
    "Agent",
    "AgentContext",
    "AgentFinding",
    "AgentInputs",
    "DiagnosticNarrative",
    "Finding",
    "FindingCluster",
    "ParasiticInjection",
    "Risk",
    "SimulationRequest",
    "Synthesiser",
    "aggregate_findings",
]
