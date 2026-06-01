"""Signal-map (feature-keeper) specialist agent (M2.10.1).

Refines the resolved user signal map — renames, retypes, target-band
suggestions, and proposed new probes. Does not mutate the map this
run; refinements land in the report and the user applies them by
editing ``user_context.json``.
"""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    select_metrics_by_prefix,
)
from emc_assistant.recommendations.engine import Recommendation


class SignalMapAgent(Agent):
    name = "signal_map"
    area_title = "User signal map"
    prompt_filename = "signal_map_agent.md"
    keywords = [
        "signal",
        "voltage",
        "current",
        "rail",
        "load",
        "out",
        "in",
        "ref",
        "fb",
    ]
    metric_prefixes: list[str] = []

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        notes: list[str] = []
        if ctx.signals:
            notes.append(
                "Resolved signal map ("
                + ", ".join(f"{s.name}={s.expr} [{s.kind}, {s.source}]" for s in ctx.signals)
                + ")"
            )
        else:
            notes.append("Resolved signal map is empty — agent is dormant.")
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=[],
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, ["v_meas", "dm_", "cm_"]),
            snippets=self._select_snippets(ctx),
            baseline_recs=[],
            notes=notes,
            topology=ctx.topology,
            dut_supply_net=ctx.dut_supply_net,
            dut_return_net=ctx.dut_return_net,
            signals=list(ctx.signals),
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        signals = inputs.signals
        findings: list[Finding] = []
        recs: list[Recommendation] = []
        limitations = ["Deterministic fallback; no LLM was invoked."]

        if not signals:
            findings.append(
                Finding(
                    title="Signal map is empty — feature-keeper is dormant",
                    detail=(
                        "No user signals were detected from the schematic and the "
                        "user_context.signals[] block is empty. Run "
                        "`pipeline run --accept-signals` to auto-detect candidates."
                    ),
                    severity="info",
                )
            )
            recs.append(
                Recommendation(
                    id="REC-001",
                    area=self.name,
                    severity="info",
                    confidence=0.3,
                    problem="No user signals declared or detected.",
                    evidence=["resolved signal map is empty"],
                    proposed_change={
                        "type": "signal_add",
                        "description": (
                            "Declare meaningful signals (Vout, Iout, etc.) in "
                            "user_context.json under the top-level signals[] key, "
                            "or run --accept-signals so the feature-keeper auto-detects them."
                        ),
                    },
                    simulation_required=False,
                    user_action="Edit user_context.json to add the signals[] block.",
                    limitations=["Dormant agent."],
                    sources=["engineering_estimate"],
                )
            )
            return AgentFinding(
                agent=self.name,
                area=self.area_title,
                confidence=0.3,
                findings=findings,
                risks=[],
                recommendations=recs,
                missing_data=[],
                simulation_requests=[],
                sources=["engineering_estimate"],
                limitations=limitations,
                llm_generated=False,
            )

        # Active path: the map exists. Surface a few light deterministic refinements.
        findings.append(
            Finding(
                title=f"Signal map has {len(signals)} entries",
                detail=(
                    "Signals: "
                    + ", ".join(f"{s.name} ({s.expr})" for s in signals)
                    + ". The LLM path of this agent would refine names, propose "
                    "target bands, and suggest current probes."
                ),
                severity="info",
            )
        )
        # Heuristic: any signal without a target band gets a low-priority hint.
        for s in signals:
            if s.target_band is None:
                recs.append(
                    Recommendation(
                        id=f"REC-{len(recs) + 1:03d}",
                        area=self.name,
                        severity="info",
                        confidence=0.4,
                        problem=f"Signal {s.name} has no target band declared.",
                        evidence=[f"signal {s.name} ({s.expr}) — no target_band in user_context"],
                        proposed_change={
                            "type": "signal_add_target_band",
                            "description": (
                                f"Add a target_band for {s.name} (min/typ/max) in "
                                "user_context.signals[] so the report can flag "
                                "out-of-band observations."
                            ),
                        },
                        simulation_required=False,
                        user_action="Re-run with --llm openai for concrete band proposals.",
                        limitations=["Deterministic fallback; bands not inferred."],
                        sources=["engineering_estimate"],
                    )
                )
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.45,
            findings=findings,
            risks=[],
            recommendations=recs,
            missing_data=[],
            simulation_requests=[],
            sources=["engineering_estimate"],
            limitations=limitations,
            llm_generated=False,
        )
