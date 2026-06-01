"""Tests for the M2.11 diagnostic-narrative synthesiser.

Covers:

- ``aggregate_findings`` clustering by topic keywords + severity ranking,
- ``Synthesiser.deterministic_synthesise`` produces a schema-valid narrative,
- ``Synthesiser.synthesise`` with a stub LLM parses good JSON into a narrative,
- malformed LLM response falls back to deterministic with a note,
- the M2.11 schema validates the result.
"""

from __future__ import annotations

import json

from emc_assistant.agents.base import AgentFinding, Finding
from emc_assistant.agents.synthesiser import (
    DiagnosticNarrative,
    Synthesiser,
    aggregate_findings,
)
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.llm.stub import StubAssistant
from emc_assistant.schemas import require_valid


def _finding(agent: str, title: str, detail: str = "", severity: str = "info") -> AgentFinding:
    return AgentFinding(
        agent=agent,
        area=agent,
        confidence=0.5,
        findings=[Finding(title=title, detail=detail, severity=severity)],
    )


# ---- aggregate_findings ---------------------------------------------------


def test_aggregate_findings_clusters_dm_dominance_across_agents():
    findings = [
        _finding("dcdc", "DM dominates over CM", severity="high"),
        _finding("filtering", "Differential mode dominate the rail", severity="medium"),
        _finding("power_integrity", "Low CM, high DM dominance", severity="medium"),
        _finding("stackup", "Tight plane spacing recommended", severity="info"),
    ]
    clusters = aggregate_findings(findings)
    # dm_dominance cluster from 3 agents; stackup matches no topic.
    dm = next(c for c in clusters if c.topic == "dm_dominance")
    assert set(dm.agents) == {"dcdc", "filtering", "power_integrity"}
    assert dm.max_severity == "high"


def test_aggregate_findings_orders_by_agent_count_then_severity():
    findings = [
        _finding("a", "DM dominates", severity="info"),
        _finding("b", "DM dominate path", severity="info"),
        _finding("c", "Hot loop ringing", severity="critical"),
    ]
    clusters = aggregate_findings(findings)
    # dm_dominance has 2 agents (a, b); hot_loop has 1 agent (c) but critical.
    # 2 agents beats 1.
    assert clusters[0].topic == "dm_dominance"
    assert clusters[1].topic == "hot_loop"


def test_aggregate_findings_skips_unmatched_topics():
    findings = [
        _finding("dcdc", "Random observation", "lorem ipsum text"),
    ]
    clusters = aggregate_findings(findings)
    assert clusters == []


def test_aggregate_findings_with_empty_input():
    assert aggregate_findings([]) == []


def test_aggregate_findings_counts_agent_once_when_it_contributes_twice():
    """An agent that emits two findings matching the same cluster must
    appear once in `agents`, and `sample_titles` mirrors that ordering."""
    af = AgentFinding(
        agent="dcdc",
        area="dcdc",
        confidence=0.5,
        findings=[
            Finding(title="DM dominates the rail", detail="", severity="high"),
            Finding(title="DM dominance corroborates the snubber risk", detail="", severity="medium"),
        ],
    )
    clusters = aggregate_findings([af])
    dm = next(c for c in clusters if c.topic == "dm_dominance")
    assert dm.agents == ["dcdc"]  # not ["dcdc", "dcdc"]
    # sample_titles is captured once per agent (the first matching title).
    assert dm.sample_titles == ["DM dominates the rail"]
    # Severity escalates to the highest seen.
    assert dm.max_severity == "high"


# ---- Deterministic synthesise --------------------------------------------


def test_deterministic_synthesise_with_clusters():
    synth = Synthesiser()
    findings = [
        _finding("dcdc", "DM dominates over CM", severity="high"),
        _finding("filtering", "Undamped LC input filter risk", severity="medium"),
        _finding("filtering", "Differential mode dominate path", severity="high"),
    ]
    nar = synth.deterministic_synthesise(
        findings=findings, ranking=None, sim_metrics={},
    )
    assert isinstance(nar, DiagnosticNarrative)
    assert nar.llm_generated is False
    # dm_dominance wins by 2 agents (dcdc + filtering) vs input_filter_stability's 1 agent.
    # The title is produced by `topic.replace("_", " ").title()` so it must contain "Dm Dominance".
    assert "dm dominance" in nar.title.lower(), f"got title: {nar.title!r}"
    # Both agents that contributed to the dominant cluster are cited.
    assert set(nar.cited_findings) == {"dcdc", "filtering"}, f"got: {nar.cited_findings}"
    # Confidence sits in the documented [0.2 .. 0.6] band for the deterministic stub.
    assert 0.2 <= nar.confidence <= 0.6
    # The fallback always notes its provenance.
    assert any("deterministic" in lim.lower() for lim in nar.limitations)
    require_valid("diagnostic_narrative.schema.json", nar.to_schema_dict())


def test_deterministic_synthesise_with_no_clusters_returns_pending():
    synth = Synthesiser()
    nar = synth.deterministic_synthesise(
        findings=[_finding("dcdc", "uncategorised note", "blah")],
        ranking=None,
        sim_metrics={},
    )
    assert "Pending" in nar.title
    assert nar.confidence <= 0.3
    require_valid("diagnostic_narrative.schema.json", nar.to_schema_dict())


def test_deterministic_synthesise_includes_top_variant_labels():
    synth = Synthesiser()
    nar = synth.deterministic_synthesise(
        findings=[_finding("dcdc", "DM dominates", severity="high")],
        ranking=[
            {"rank": 1, "label": "par-trace-L-iso-25x1-max", "metric": 3.5},
            {"rank": 2, "label": "baseline", "metric": 3.4},
        ],
        sim_metrics={},
    )
    assert "par-trace-L-iso-25x1-max" in nar.cited_variants
    assert "baseline" in nar.cited_variants


# ---- Stub-LLM synthesise --------------------------------------------------


def _problem_ctx() -> ProblemContext:
    return ProblemContext(
        project_id="test",
        analysis_scope="conducted_emi",
        topology="DC/DC buck",
        switching_frequency_hz=400_000.0,
        has_layout=False,
        has_stackup=False,
    )


def test_synthesise_with_stub_assistant_parses_json():
    canned = json.dumps({
        "title": "Stub diagnostic",
        "narrative": "Stub narrative paragraph.",
        "dominant_issue": "Stub dominant issue.",
        "confidence": 0.65,
        "cited_findings": ["dcdc", "filtering"],
        "cited_variants": ["baseline"],
        "cited_rule_ids": ["R-001"],
        "limitations": ["stub: no real LLM"],
    })
    stub = StubAssistant(canned_completion=canned)
    synth = Synthesiser()
    nar = synth.synthesise(
        problem_ctx=_problem_ctx(),
        findings=[_finding("dcdc", "DM dominates", severity="high")],
        sim_metrics={"dm_peak": 3.5, "cm_peak": 0.0},
        ranking=[],
        ranking_metric_key=None,
        snippets=[],
        signals=[],
        assistant=stub,
    )
    assert nar.llm_generated is True
    assert nar.title == "Stub diagnostic"
    assert nar.confidence == 0.65
    assert "dcdc" in nar.cited_findings
    require_valid("diagnostic_narrative.schema.json", nar.to_schema_dict())


def test_synthesise_with_malformed_response_falls_back():
    stub = StubAssistant(canned_completion="not JSON at all")
    synth = Synthesiser()
    nar = synth.synthesise(
        problem_ctx=_problem_ctx(),
        findings=[_finding("dcdc", "DM dominates", severity="high")],
        sim_metrics={},
        ranking=[],
        ranking_metric_key=None,
        snippets=[],
        signals=[],
        assistant=stub,
    )
    assert nar.llm_generated is False
    assert any("malformed" in lim.lower() for lim in nar.limitations)
    require_valid("diagnostic_narrative.schema.json", nar.to_schema_dict())


def test_synthesise_response_missing_required_fields_falls_back():
    canned = json.dumps({"narrative": "only narrative", "confidence": 0.5})
    stub = StubAssistant(canned_completion=canned)
    synth = Synthesiser()
    nar = synth.synthesise(
        problem_ctx=_problem_ctx(),
        findings=[_finding("dcdc", "DM dominates", severity="high")],
        sim_metrics={},
        ranking=[],
        ranking_metric_key=None,
        snippets=[],
        signals=[],
        assistant=stub,
    )
    # Missing title + dominant_issue -> fallback
    assert nar.llm_generated is False
    assert any("malformed" in lim.lower() for lim in nar.limitations)


def test_synthesise_stub_records_synthesis_purpose():
    canned = json.dumps({
        "title": "T", "narrative": "N", "dominant_issue": "D", "confidence": 0.5,
    })
    stub = StubAssistant(canned_completion=canned)
    synth = Synthesiser()
    synth.synthesise(
        problem_ctx=_problem_ctx(),
        findings=[_finding("dcdc", "DM dominates", severity="high")],
        sim_metrics={},
        ranking=[],
        ranking_metric_key=None,
        snippets=[],
        signals=[],
        assistant=stub,
    )
    # Exactly one call (not retried on parse error etc.).
    assert len(stub.complete_calls) == 1
    _msgs, purpose = stub.complete_calls[0]
    assert purpose == "synthesis.diagnostic"


def test_synthesise_prompt_includes_aggregated_findings_metrics_and_ranking():
    """Regression guard: every key input section must appear in the user
    payload sent to the LLM. If a refactor drops one accidentally, this
    test catches it before the LLM silently synthesises with missing data."""
    canned = json.dumps({
        "title": "T", "narrative": "N", "dominant_issue": "D", "confidence": 0.5,
    })
    stub = StubAssistant(canned_completion=canned)
    synth = Synthesiser()
    synth.synthesise(
        problem_ctx=_problem_ctx(),
        findings=[
            _finding("dcdc", "DM dominates", severity="high"),
            _finding("filtering", "Differential mode dominate path", severity="high"),
        ],
        sim_metrics={"dm_peak": 3.5, "cm_peak": 1e-7},
        ranking=[
            {"rank": 1, "label": "par-trace-L-iso-25x1-max", "metric": 3.60},
            {"rank": 2, "label": "baseline", "metric": 3.55},
        ],
        ranking_metric_key="v_meas_peak",
        snippets=[],
        signals=[],
        assistant=stub,
    )
    messages, _ = stub.complete_calls[0]
    # User message is the second one.
    user_payload = messages[1]["content"]
    # All 7 input sections from the prompt contract must appear.
    for section in (
        "# Problem context",
        "# Simulation metrics",
        "# Variant ranking",
        "# Aggregated findings",
        "# Retrieved knowledge snippets",
        "# Tracked user signals",
    ):
        assert section in user_payload, f"missing section: {section!r}"
    # The dm_dominance cluster (2 agents) is present in the prompt.
    assert "dm_dominance" in user_payload
    assert "dcdc" in user_payload and "filtering" in user_payload
    # Both metrics appear.
    assert "dm_peak" in user_payload and "cm_peak" in user_payload
    # Ranking entries appear with their labels + metric.
    assert "par-trace-L-iso-25x1-max" in user_payload
    assert "v_meas_peak" in user_payload
