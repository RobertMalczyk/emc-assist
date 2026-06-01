"""Minimal deterministic EMC recommendation engine (no LLM).

Every recommendation is an *engineering hypothesis* — labelled with
assumptions, limitations, and a "simulation_required" flag. We never
claim that a design "passes EMC".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from emc_assistant.parasitics.model import ParasiticEstimate


@dataclass
class Recommendation:
    id: str
    area: str
    severity: str  # info|low|medium|high|critical
    confidence: float  # 0..1
    problem: str
    evidence: list[str] = field(default_factory=list)
    proposed_change: dict = field(default_factory=dict)
    simulation_required: bool = True
    user_action: str = ""
    limitations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    llm_generated: bool = False
    """True when the recommendation text was produced by an LLM (M2.7+).
    False for deterministic rule-based recommendations from this engine."""
    citations: list[str] = field(default_factory=list)
    """Optional Source_ID or knowledge-pack snippet IDs the LLM cited.
    Empty for deterministic recommendations."""

    def to_schema_dict(self) -> dict:
        return {
            "id": self.id,
            "area": self.area,
            "severity": self.severity,
            "confidence": float(self.confidence),
            "problem": self.problem,
            "evidence": list(self.evidence),
            "proposed_change": dict(self.proposed_change),
            "simulation_required": bool(self.simulation_required),
            "user_action": self.user_action,
            "limitations": list(self.limitations),
            "sources": list(self.sources),
            "llm_generated": bool(self.llm_generated),
            "citations": list(self.citations),
        }


def _next_id(seq: int) -> str:
    return f"REC-{seq:03d}"


def build_baseline_recommendations(
    parasitics: Iterable[ParasiticEstimate],
    *,
    has_layout: bool = False,
    has_stackup: bool = False,
) -> list[Recommendation]:
    """Build baseline M0 recommendations from parasitic estimates only.

    Emits:
    - a mandatory recommendation about the LISN testbench,
    - a recommendation about verifying parasitic resonances,
    - an informational entry per estimated parasitic.
    """
    recs: list[Recommendation] = []
    seq = 1

    base_limits = []
    if not has_layout:
        base_limits.append("No layout available — parasitics estimated geometrically.")
    if not has_stackup:
        base_limits.append("No stack-up data — defaulting to eps_r=4.3 (FR-4).")

    recs.append(
        Recommendation(
            id=_next_id(seq),
            area="testbench",
            severity="info",
            confidence=0.6,
            problem=(
                "No dedicated conducted-EMI testbench. Without a LISN and cable "
                "model, an LTspice spectrum has limited pre-compliance value."
            ),
            evidence=[
                "EMC rule R-003: conducted-EMI pre-compliance needs LISN and cables with parasitics.",
            ],
            proposed_change={
                "type": "add_subcircuit",
                "description": "Add the generated .SUBCKT LISN50UH and cable model CABLE_PWR to the netlist.",
                "component": "LISN50UH",
            },
            simulation_required=True,
            user_action="Insert the generated SPICE fragments into the netlist and run AC/TRAN.",
            limitations=[
                "Educational LISN topology; does not match an EMI-receiver detector.",
                *base_limits,
            ],
            sources=["R-003"],
        )
    )
    seq += 1

    inductive = [p for p in parasitics if p.parasitic_type == "L"]
    capacitive = [p for p in parasitics if p.parasitic_type == "C"]
    if inductive and capacitive:
        recs.append(
            Recommendation(
                id=_next_id(seq),
                area="parasitics",
                severity="medium",
                confidence=0.5,
                problem=(
                    "Trace/via parasitic L and C can create resonances inside the EMI band."
                ),
                evidence=[
                    f"Identified {len(inductive)} inductive and {len(capacitive)} capacitive parasitics.",
                    "Rules R002/R010 — first-order formulas for trace L and via L.",
                ],
                proposed_change={
                    "type": "sweep",
                    "description": (
                        "Sweep min/typ/max of the parasitics and observe resonances "
                        "at the LISN measurement port."
                    ),
                },
                simulation_required=True,
                user_action="Run .step or several TRAN/AC simulations for min/typ/max corners.",
                limitations=[
                    "Parasitic values are ±20–50% estimates.",
                    *base_limits,
                ],
                sources=["R002", "R010"],
            )
        )
        seq += 1

    for p in parasitics:
        recs.append(
            Recommendation(
                id=_next_id(seq),
                area=f"parasitic.{p.structure}.{p.parasitic_type}",
                severity="info",
                confidence=0.4,
                problem=(
                    f"Estimated parasitic {p.structure}/{p.parasitic_type}: "
                    f"min={p.min_value:.3g}, typ={p.value:.3g}, max={p.max_value:.3g} {p.unit}."
                ),
                evidence=p.assumptions + ([f"formula: {p.formula}"] if p.formula else []),
                proposed_change={
                    "type": "include_in_testbench",
                    "description": p.ltspice_representation or "Insert as a series/shunt element in the testbench.",
                    "values": {
                        "min": p.min_value,
                        "typ": p.value,
                        "max": p.max_value,
                        "unit": p.unit,
                    },
                },
                simulation_required=True,
                limitations=base_limits,
                sources=list(p.source_ids),
            )
        )
        seq += 1

    return recs
