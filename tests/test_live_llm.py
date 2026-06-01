"""Live OpenAI tests — exercise every LLM path against the real model.

These run only when an API key is resolvable (env var or key file) and
``EMC_ASSISTANT_SKIP_LIVE_LLM`` is not set; otherwise conftest auto-skips
them (so keyless CI stays green). Each test caps spend with a small
per-run budget. Payloads are the redacted, structured summaries the
features already send — never the schematic.

Coverage: the 11 specialist agents (orchestrator fan-out), the 12th
LISN-mode agent, the recommendations writer, the diagnostic synthesiser,
and the M2.10.7 parasitic-negligibility screen.

Run just these:    pytest -m live_llm
Skip them:         EMC_ASSISTANT_SKIP_LIVE_LLM=1 pytest

NOTE: with a key present these make real (paid) calls on every run — the
agents test alone fires 11. Use the skip env for fast keyless iteration.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from emc_assistant.agents.base import AgentContext, AgentFinding, Finding
from emc_assistant.agents.injection import ShuntParasitic
from emc_assistant.agents.lisn_mode_agent import LisnModeAgent
from emc_assistant.agents.orchestrator import list_agent_names, run_agents
from emc_assistant.agents.parasitics_agent import ParasiticsAgent
from emc_assistant.agents.synthesiser import DiagnosticNarrative, Synthesiser
from emc_assistant.llm.assistant import ProblemContext, RedactedSnippet
from emc_assistant.llm.budget import BudgetTracker
from emc_assistant.llm.openai_provider import OpenAiAssistant
from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import build_topology_report
from emc_assistant.schemas import require_valid

pytestmark = pytest.mark.live_llm


# ---- shared fixtures / builders -------------------------------------------


def _assistant(budget_usd: float = 0.15, cap_usd: float | None = None) -> OpenAiAssistant:
    tracker = BudgetTracker(cap_usd=cap_usd) if cap_usd else None
    return OpenAiAssistant(budget_usd=budget_usd, budget_tracker=tracker)


def _problem_ctx() -> ProblemContext:
    return ProblemContext(
        project_id="live_test",
        analysis_scope="conducted_emi",
        topology="DC/DC buck converter",
        input_voltage_v=24.0,
        switching_frequency_hz=400_000.0,
        load_current_a=2.0,
        frequency_range_min_hz=150_000.0,
        frequency_range_max_hz=30_000_000.0,
        has_layout=False,
        has_stackup=False,
    )


def _snippets() -> list[RedactedSnippet]:
    return [
        RedactedSnippet(
            rule_id="R-001", source_id="SRC-031",
            summary="Low-EMI DC/DC: keep the input-filter resonance below 5x F_sw.",
        ),
        RedactedSnippet(
            rule_id="R-074", source_id="SRC-074",
            summary="SLUA929: damp the input filter to prevent oscillation.",
        ),
    ]


def _sim_metrics() -> dict[str, float]:
    return {
        "v_meas_peak": 3.41,
        "dm_peak": 3.65,
        "cm_peak": 2.3e-7,
        "v_meas_band_peak_dbuv_150000_30000000": 66.2,
        "vrms": 0.643,
    }


def _agent_ctx() -> AgentContext:
    return AgentContext(
        problem_context=_problem_ctx(),
        parasitics=[],
        sim_metrics=_sim_metrics(),
        snippets=_snippets(),
        baseline_recs=[],
    )


def _topology():
    src = "* t\nVin in 0 DC 24\nR1 in out 1\nCout out 0 10u\n.end\n"
    return build_topology_report(parse_cir(src))


def _shunt(net: str, c_pf: float, rationale: str) -> ShuntParasitic:
    return ShuntParasitic(
        net=net, capacitance_f=c_pf * 1e-12, return_net="DUT_GND",
        rule_id="engineering_estimate", source="rule_of_thumb", rationale=rationale,
    )


# ---- M2.10.7 negligibility screen -----------------------------------------


def test_negligibility_screen_real_openai_partitions_nets():
    """The screen, against the real model, classifies every net exactly
    once and keeps the high-dv/dt nets (switching node, power rail)."""
    entries = [
        _shunt("SW", 30, "switching node — fast dv/dt, dominant conducted-EMI source"),
        _shunt("VIN", 50, "input power rail feeding the DUT through the LISN"),
        _shunt("N_BIAS_HIZ", 1, "high-impedance static bias divider tap, no fast edges"),
    ]
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=_assistant(),
        context_line="DC/DC buck converter, conducted EMI 150 kHz - 30 MHz pre-compliance.",
    )
    kept_nets = {e.net for e in kept}
    dropped_nets = {d["net"] for d in dropped}
    assert kept_nets | dropped_nets == {"SW", "VIN", "N_BIAS_HIZ"}
    assert kept_nets.isdisjoint(dropped_nets)
    for d in dropped:
        assert set(d) >= {"net", "kind", "reason"} and d["kind"] == "shunt"
    assert "SW" in kept_nets, f"switching node was dropped: {dropped}"
    assert "VIN" in kept_nets, f"power rail was dropped: {dropped}"


# ---- M2.17 value re-evaluation --------------------------------------------


def test_value_reevaluation_real_openai_returns_plausible_bands():
    """The M2.17 re-evaluation, against the real model, returns min/typ/max
    bands (never single values), physically plausible for a PCB trace and with
    a confidence in [0, 1] — the strongly-prompted invariants, not wording."""
    candidates = [
        {"net": "VIN", "role": "power_rail",
         "prior": {"r_band": [1e-3, 3e-3, 9e-3], "l_band": [5e-9, 1.2e-8, 3e-8],
                   "c_band": [1e-12, 3e-12, 9e-12]},
         "snippets": [{"rule_id": "PCB-TRACE-L", "source_id": "S033",
                       "summary": "A 1 cm PCB trace carries roughly 6-10 nH of "
                       "loop inductance.", "excerpt": ""}]},
        {"net": "SW", "role": "switching_node",
         "prior": {"r_band": [1e-3, 4e-3, 1e-2], "l_band": [6e-9, 1.5e-8, 4e-8],
                   "c_band": [1e-12, 3e-12, 9e-12]},
         "snippets": [{"rule_id": "PCB-STRAY-C", "source_id": "S034",
                       "summary": "Trace-to-plane stray capacitance is a few pF "
                       "per cm.", "excerpt": ""}]},
    ]
    out = ParasiticsAgent().reevaluate_values(
        candidates, assistant=_assistant(),
        context_line="DC/DC buck converter, conducted EMI 150 kHz - 30 MHz pre-compliance.",
    )
    assert out, "model returned no usable refinements"
    for v in out.values():
        for key in ("r_band", "l_band", "c_band"):
            b = v[key]
            assert len(b) == 3 and b[0] <= b[1] <= b[2] and b[0] > 0  # a real band
        assert 0.0 <= v["confidence"] <= 1.0
        assert v["l_band"][1] < 1e-6   # typ L well under 1 uH (PCB trace, not a coil)
        assert v["c_band"][1] < 1e-9   # typ C well under 1 nF (stray, not a cap)


# ---- the 11 specialist agents (orchestrator fan-out) ----------------------


def test_specialist_agents_real_openai_all_llm_generated(tmp_path):
    """Every active agent's prompt yields parseable JSON from the real
    model: 11 schema-valid findings, all llm_generated, none crashed."""
    result = run_agents(
        _agent_ctx(),
        assistant=_assistant(budget_usd=0.15, cap_usd=2.0),
        output_dir=tmp_path,
    )
    assert [f.agent for f in result.findings] == list_agent_names()
    assert result.failed_agents == [], f"agents crashed: {result.failed_agents}"
    fell_back = [
        (f.agent, f.limitations) for f in result.findings if not f.llm_generated
    ]
    assert fell_back == [], f"agents fell back to deterministic: {fell_back}"
    # Each finding carries content + is schema-valid (orchestrator also
    # validates on write).
    for f in result.findings:
        assert f.findings or f.recommendations, f"{f.agent}: empty finding"
        require_valid("agent_finding.schema.json", f.to_schema_dict())


# ---- the 12th agent: LISN mode --------------------------------------------


def test_lisn_mode_agent_real_openai_decides():
    decision = LisnModeAgent().decide(
        topology=_topology(), problem_context=_problem_ctx(), assistant=_assistant(),
    )
    assert decision.source == "llm", f"fell back to heuristic: {decision}"
    assert decision.mode in ("dual", "single")
    assert 0.0 < decision.confidence <= 1.0
    assert decision.rationale.strip()


# ---- recommendations writer -----------------------------------------------


def test_explain_recommendations_real_openai_replace_mode():
    drafts = _assistant(budget_usd=0.20).explain_recommendations(
        problem_context=_problem_ctx(),
        parasitics=[],
        sim_metrics=_sim_metrics(),
        snippets=_snippets(),
        mode="replace",
    )
    assert drafts, "no recommendation drafts returned"
    for d in drafts:
        assert d.llm_generated is True
        assert d.problem.strip(), "recommendation has no problem statement"
        require_valid("recommendation.schema.json", d.to_schema_dict())
    # At least one draft cites a source we supplied (R-001 / R-074 / SRC-*).
    cited = {c for d in drafts for c in (d.citations + d.sources)}
    assert cited, "no citations on any draft — the snippets were ignored"


# ---- diagnostic synthesiser -----------------------------------------------


def test_synthesiser_real_openai_writes_narrative():
    findings = [
        AgentFinding(agent="dcdc", area="dcdc", confidence=0.6,
                     findings=[Finding(title="DM dominates over CM", detail="", severity="high")]),
        AgentFinding(agent="filtering", area="filtering", confidence=0.6,
                     findings=[Finding(title="Undamped LC input filter risk", detail="", severity="medium")]),
    ]
    nar = Synthesiser().synthesise(
        problem_ctx=_problem_ctx(),
        findings=findings,
        sim_metrics=_sim_metrics(),
        ranking=[{"rank": 1, "label": "baseline", "metric": 3.41}],
        ranking_metric_key="v_meas_peak",
        snippets=_snippets(),
        signals=[],
        assistant=_assistant(budget_usd=0.20),
    )
    assert isinstance(nar, DiagnosticNarrative)
    assert nar.llm_generated is True, f"fell back: {nar.limitations}"
    assert nar.title.strip() and nar.dominant_issue.strip()
    assert 0.0 <= nar.confidence <= 1.0
    require_valid("diagnostic_narrative.schema.json", nar.to_schema_dict())


# ---- standalone suggest-negligible endpoint (the UI AI button) ------------


def test_suggest_negligible_endpoint_real_openai(tmp_path):
    """The service backing the parasitics 'AI: suggest negligible' button
    runs the screen on the real per-net plan and returns dropped nets."""
    from emc_assistant.service import CommandOptions
    from emc_assistant.service.parasitics import SuggestNegligibleResult, suggest_negligible

    case_001 = Path(__file__).resolve().parents[1] / "examples" / "case_001_buck_conducted_emi"
    dst = tmp_path / "case_001"
    shutil.copytree(case_001, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)

    res = suggest_negligible(
        str(dst),
        CommandOptions(llm="openai", accept_wiring=True, accept_parasitics=True, llm_budget_usd=0.30),
    )
    assert isinstance(res, SuggestNegligibleResult)
    assert res.considered >= 1, "no per-net parasitics were considered"
    assert isinstance(res.dropped, list)
    for d in res.dropped:
        assert set(d) >= {"net", "kind", "reason"} and d["kind"] in ("shunt", "series")
