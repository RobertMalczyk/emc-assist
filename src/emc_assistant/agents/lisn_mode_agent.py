"""LISN-mode specialist agent (M2.10.x).

The 12th specialist agent. Unlike the eleven post-simulation report
agents, this one runs **before** the testbench is composed: its
decision — dual-LISN (CISPR-style) vs single-LISN (legacy) — shapes the
testbench itself (the dual-LISN topology lifts the DUT ground to a
separate ``DUT_GND`` node and enables the DM/CM split).

The CLI invokes :meth:`LisnModeAgent.decide` from the pre-composition
resolver ``_resolve_lisn_mode``. An explicit ``lisn_mode`` in
``user_context.testbench_wiring`` always overrides the agent.

``select_relevant`` / ``deterministic_finding`` are implemented for
contract compatibility with the :class:`Agent` ABC and to give a
report-shaped finding, but this agent is not part of the post-simulation
orchestrator fan-out.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    parse_json_object,
)
from emc_assistant.recommendations.engine import Recommendation


_VALID_MODES = ("dual", "single")
_CHASSIS_HINTS = ("chassis", "earth", "frame ground", "metal enclosure", "pe ")


@dataclass
class LisnModeDecision:
    """The agent's pre-composition decision."""

    mode: str  # "dual" | "single"
    confidence: float
    rationale: str
    source: str  # "llm" | "deterministic" | "user_override"

    def to_dict(self) -> dict:
        return {
            "lisn_mode": self.mode,
            "confidence": self.confidence,
            "rationale": self.rationale,
            "source": self.source,
        }


class LisnModeAgent(Agent):
    name = "lisn_mode"
    area_title = "LISN topology selection"
    prompt_filename = "lisn_mode_agent.md"
    keywords = ["lisn", "ground", "return", "chassis", "earth", "conducted", "cispr"]
    metric_prefixes: list[str] = []

    # ------------------------------------------------------------------
    # Primary entry point — pre-composition decision
    # ------------------------------------------------------------------

    def decide(
        self, *, topology, problem_context, assistant
    ) -> LisnModeDecision:
        """Decide dual vs single LISN for this circuit.

        ``assistant`` None or deterministic → the rule-based heuristic.
        Otherwise the LLM path; any LLM error or malformed response
        falls back to the heuristic (fail-safe).
        """
        if assistant is None or getattr(assistant, "name", "") == "deterministic":
            return self._deterministic_decision(topology, problem_context)
        try:
            raw = assistant.complete(
                messages=self._decision_messages(topology, problem_context),
                purpose=f"agent.{self.name}",
                expected_output_tokens=400,
            )
            data = parse_json_object(raw)
            mode = str(data.get("lisn_mode", "")).strip().lower()
            if mode not in _VALID_MODES:
                raise ValueError(f"lisn_mode must be dual|single; got {mode!r}")
            conf = float(data.get("confidence", 0.5))
            rationale = str(data.get("rationale", "")).strip() or "LLM decision."
            return LisnModeDecision(
                mode=mode,
                confidence=max(0.0, min(1.0, conf)),
                rationale=rationale,
                source="llm",
            )
        except Exception as exc:  # noqa: BLE001 - fail-safe to the heuristic
            det = self._deterministic_decision(topology, problem_context)
            return LisnModeDecision(
                mode=det.mode,
                confidence=det.confidence,
                rationale=f"LLM decision unavailable ({exc}); used the heuristic. "
                + det.rationale,
                source="deterministic",
            )

    def _deterministic_decision(self, topology, problem_context) -> LisnModeDecision:
        """Rule-based fallback: dual-LISN unless the return looks chassis-bonded.

        A conducted-EMI DC/DC analysis defaults to a CISPR-style
        dual-LISN. Single-LISN is chosen only when the project context
        explicitly signals a chassis/earth-referenced return.
        """
        hay = " ".join(
            str(x).lower()
            for x in (
                getattr(problem_context, "topology", ""),
                getattr(problem_context, "problem_hypothesis", ""),
            )
        )
        if any(h in hay for h in _CHASSIS_HINTS):
            return LisnModeDecision(
                mode="single",
                confidence=0.5,
                rationale=(
                    "Project context mentions a chassis/earth-referenced return, "
                    "so a single-LISN testbench models the return path more "
                    "faithfully. Heuristic decision — verify against the schematic."
                ),
                source="deterministic",
            )
        return LisnModeDecision(
            mode="dual",
            confidence=0.6,
            rationale=(
                "Conducted-EMI DC/DC analysis defaults to a CISPR-style dual-LISN; "
                "no chassis/earth-referenced return was detected, so the supply and "
                "return rails each get their own LISN and a true DM/CM split is "
                "available. Heuristic decision — run --llm openai for a "
                "topology-aware judgement."
            ),
            source="deterministic",
        )

    def _decision_messages(self, topology, problem_context) -> list[dict[str, Any]]:
        system = self.prompt_path.read_text(encoding="utf-8")
        payload: dict[str, Any] = {
            "problem_context": {
                "project_type": getattr(problem_context, "topology", ""),
                "analysis_scope": getattr(problem_context, "analysis_scope", ""),
                "input_voltage_v": getattr(problem_context, "input_voltage_v", None),
                "problem_hypothesis": getattr(problem_context, "problem_hypothesis", ""),
            },
            "topology": topology.to_schema_dict() if topology is not None else None,
        }
        user = (
            "Decide the LISN mode for this circuit.\n\n"
            + json.dumps(payload, indent=1, ensure_ascii=True)
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------------
    # Agent ABC contract (report-shaped; not used in the post-sim fan-out)
    # ------------------------------------------------------------------

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=[],
            sim_metrics={},
            snippets=self._select_snippets(ctx),
            baseline_recs=[],
            notes=["LISN-mode agent — pre-composition decision agent."],
            topology=ctx.topology,
            dut_supply_net=ctx.dut_supply_net,
            dut_return_net=ctx.dut_return_net,
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        decision = self._deterministic_decision(
            inputs.topology, inputs.problem_context
        )
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=decision.confidence,
            findings=[
                Finding(
                    title=f"LISN mode: {decision.mode}",
                    detail=decision.rationale,
                    severity="info",
                )
            ],
            risks=[],
            recommendations=[
                Recommendation(
                    id="REC-001",
                    area=self.name,
                    severity="info",
                    confidence=decision.confidence,
                    problem=(
                        "The conducted-EMI testbench needs a LISN topology "
                        "(dual-LISN CISPR-style vs single-LISN legacy)."
                    ),
                    evidence=[decision.rationale],
                    proposed_change={
                        "type": "testbench_lisn_mode",
                        "description": f"Use a {decision.mode}-LISN testbench.",
                    },
                    simulation_required=False,
                    user_action=(
                        "Set testbench_wiring.lisn_mode in user_context.json to "
                        "override; leave it unset/'auto' to let this agent decide."
                    ),
                    limitations=["Deterministic fallback; no LLM was invoked."],
                    sources=["engineering_estimate"],
                )
            ],
            missing_data=[],
            simulation_requests=[],
            sources=["engineering_estimate"],
            limitations=["Deterministic fallback; no LLM was invoked."],
            llm_generated=False,
        )
