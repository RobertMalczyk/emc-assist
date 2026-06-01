"""IC-vendor specialist agent.

Compares the design against datasheet / reference-design snippets. Without
a vendor citation in the retrieved snippets, the agent refuses to claim
specific IC knowledge.
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


class IcVendorAgent(Agent):
    name = "ic_vendor"
    area_title = "IC-vendor recommendations"
    prompt_filename = "ic_vendor_agent.md"
    keywords = [
        "datasheet",
        "reference design",
        "evaluation board",
        "evm",
        "application note",
        "vendor",
        "lm",
        "tps",
        "lt",
        "regulator",
    ]
    metric_prefixes = ["v_meas"]

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, self.metric_prefixes),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=[
                "Refuse to name specific IC values, pin functions, or layout "
                "cells without a vendor snippet in retrieved knowledge."
            ],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        has_vendor_snippet = any("SRC-" in s.source_id for s in inputs.snippets)
        findings = [
            Finding(
                title=(
                    "Vendor snippet present" if has_vendor_snippet else "No vendor snippet in retrieval"
                ),
                detail=(
                    "Retrieved snippets include vendor content; specific IC "
                    "recommendations are possible in the LLM path."
                    if has_vendor_snippet
                    else (
                        "No datasheet or reference-design snippet was retrieved. "
                        "IC-specific recommendations are deferred. Add the "
                        "regulator datasheet to knowledge/raw_sources to unlock "
                        "this agent in the LLM path."
                    )
                ),
                severity="info",
            )
        ]
        missing = (
            []
            if has_vendor_snippet
            else [
                "Datasheet for the regulator IC",
                "Vendor reference design / evaluation board",
            ]
        )
        recs = [
            Recommendation(
                id="REC-001",
                area=self.name,
                severity="info",
                confidence=0.3,
                problem=(
                    "Deterministic fallback for the IC-vendor agent. The LLM "
                    "path generates concrete cross-checks against vendor reference designs."
                ),
                evidence=[
                    "Vendor snippet found in retrieval"
                    if has_vendor_snippet
                    else "No vendor snippet found in retrieval"
                ],
                proposed_change={
                    "type": "investigate",
                    "description": (
                        "Add the regulator datasheet and / or reference-design "
                        "PDF to knowledge/raw_sources and re-index. Then re-run "
                        "with --llm openai."
                    ),
                },
                simulation_required=False,
                user_action="Re-run with --llm openai after adding vendor docs.",
                limitations=["Deterministic fallback; no LLM was invoked."],
                sources=["engineering_estimate"],
            )
        ]
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.3,
            findings=findings,
            risks=[],
            recommendations=recs,
            missing_data=missing,
            simulation_requests=[],
            sources=["engineering_estimate"],
            limitations=[
                "Deterministic fallback; no LLM was invoked.",
                "IC-specific claims require a vendor snippet — none was retrieved.",
            ]
            if not has_vendor_snippet
            else ["Deterministic fallback; no LLM was invoked."],
            llm_generated=False,
        )
