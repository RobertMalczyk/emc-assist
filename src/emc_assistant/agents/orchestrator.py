"""Specialist-agent orchestrator (M2.9).

Fans out to all 11 active agents in one ``pipeline run``, writes a
JSON finding per agent under ``<output_dir>/findings/<agent>.json``,
and validates each file against ``schemas/agent_finding.schema.json``.

Two failure modes are isolated:

- ``BudgetExceeded`` from the budget tracker aborts the remaining
  agents (the user's cap is hard); already-produced findings stay on
  disk so the report can still mention partial coverage.
- Any other agent-level exception (bad JSON, network blip, model
  refusal) falls back to that agent's deterministic finding with a
  limitation appended, so the run still produces 11 findings.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
)
from emc_assistant.agents.dcdc_agent import DcDcAgent
from emc_assistant.agents.decoupling_agent import DecouplingAgent
from emc_assistant.agents.filtering_agent import FilteringAgent
from emc_assistant.agents.high_speed_agent import HighSpeedAgent
from emc_assistant.agents.ic_vendor_agent import IcVendorAgent
from emc_assistant.agents.layout_risk_agent import LayoutRiskAgent
from emc_assistant.agents.mixed_signal_agent import MixedSignalAgent
from emc_assistant.agents.parasitics_agent import ParasiticsAgent
from emc_assistant.agents.power_integrity_agent import PowerIntegrityAgent
from emc_assistant.agents.signal_map_agent import SignalMapAgent
from emc_assistant.agents.stackup_agent import StackupAgent
from emc_assistant.llm.assistant import LlmAssistant
from emc_assistant.llm.budget import BudgetExceeded
from emc_assistant.schemas import require_valid


AGENT_CLASSES: list[type[Agent]] = [
    DcDcAgent,
    FilteringAgent,
    PowerIntegrityAgent,
    DecouplingAgent,
    ParasiticsAgent,
    StackupAgent,
    HighSpeedAgent,
    MixedSignalAgent,
    IcVendorAgent,
    LayoutRiskAgent,
    SignalMapAgent,
]
"""Active specialist agents in canonical report order. Adding or
removing an entry changes the per-area subsection count in the report.
``acdc`` and ``analog`` agents are parked stubs and not loaded here."""


@dataclass
class OrchestrationResult:
    """Summary of one orchestration pass.

    Includes the list of findings (in canonical order), the list of
    agent names whose LLM call failed and fell back to deterministic
    output, and a flag indicating that the budget guard interrupted
    the run.
    """

    findings: list[AgentFinding]
    failed_agents: list[str]
    budget_exhausted: bool


def _write_finding(finding: AgentFinding, findings_dir: Path) -> Path:
    findings_dir.mkdir(parents=True, exist_ok=True)
    out_path = findings_dir / f"{finding.agent}.json"
    schema_dict = finding.to_schema_dict()
    require_valid("agent_finding.schema.json", schema_dict)
    out_path.write_text(
        json.dumps(schema_dict, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return out_path


def run_agents(
    ctx: AgentContext,
    *,
    assistant: LlmAssistant | None,
    output_dir: Path,
    agents: Iterable[type[Agent]] | None = None,
) -> OrchestrationResult:
    """Run every active agent against the shared context.

    ``output_dir`` is the project results directory; findings land in
    ``output_dir / "findings"``. The orchestrator returns an
    :class:`OrchestrationResult` listing each finding plus any
    agent-level failures.

    When ``assistant`` is ``None`` or its name is ``"deterministic"``
    every agent runs its deterministic fallback (the M2.9 acceptance
    criterion: ``--llm none`` produces a finding per agent, none silently
    empty). The roster has grown to 11 since M2.9 (signal_map, M2.10.1).
    """
    findings_dir = Path(output_dir) / "findings"
    findings_dir.mkdir(parents=True, exist_ok=True)

    agent_classes = list(agents) if agents is not None else AGENT_CLASSES
    findings: list[AgentFinding] = []
    failed: list[str] = []
    budget_exhausted = False

    for cls in agent_classes:
        agent = cls()
        try:
            finding = agent.run(ctx, assistant)
        except BudgetExceeded:
            budget_exhausted = True
            # Save the deterministic fallback so the area is still represented.
            inputs = agent.select_relevant(ctx)
            finding = agent.deterministic_finding(inputs)
            finding.limitations.append(
                "Run-level LLM budget exhausted before this agent could be called."
            )
            findings.append(finding)
            _write_finding(finding, findings_dir)
            # Stop firing further LLM calls; remaining agents run as
            # deterministic so the report still has 11 sections.
            for remaining in agent_classes[agent_classes.index(cls) + 1 :]:
                remaining_agent = remaining()
                remaining_inputs = remaining_agent.select_relevant(ctx)
                remaining_finding = remaining_agent.deterministic_finding(remaining_inputs)
                remaining_finding.limitations.append(
                    "Run-level LLM budget exhausted; LLM path skipped."
                )
                findings.append(remaining_finding)
                _write_finding(remaining_finding, findings_dir)
            break
        except Exception as exc:  # noqa: BLE001
            failed.append(agent.name)
            inputs = agent.select_relevant(ctx)
            finding = agent.deterministic_finding(inputs)
            finding.limitations.append(
                f"LLM call failed ({type(exc).__name__}); deterministic fallback used."
            )

        findings.append(finding)
        _write_finding(finding, findings_dir)

    return OrchestrationResult(
        findings=findings,
        failed_agents=failed,
        budget_exhausted=budget_exhausted,
    )


def list_agent_names() -> list[str]:
    """Return the canonical agent-name order for report subsections."""
    return [cls().name for cls in AGENT_CLASSES]
