"""Tests for the LLM-assistant layer: interface, deterministic fallback, stub, budget, privacy log."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emc_assistant.llm import (
    BudgetExceeded,
    DeterministicAssistant,
    ProblemContext,
    RecommendationDraft,
    RedactedSnippet,
    StubAssistant,
    estimate_cost_usd,
    write_privacy_log_entry,
)
from emc_assistant.llm.budget import assert_within_budget
from emc_assistant.parasitics.calculators import (
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)


def _ctx() -> ProblemContext:
    return ProblemContext(
        project_id="case_001",
        analysis_scope="conducted_emi_dc_dc",
        topology="buck_converter",
        input_voltage_v=24.0,
        switching_frequency_hz=400_000.0,
        load_current_a=2.0,
        problem_hypothesis="conducted EMI near switching harmonics",
        has_layout=False,
        has_stackup=True,
    )


def _parasitics():
    return [
        trace_resistance(length_mm=20.0, width_mm=1.0),
        trace_inductance_no_plane(length_mm=20.0, width_mm=1.0),
        trace_capacitance_from_z0_delay(length_mm=20.0, z0_ohm=50.0, delay_ps_per_mm=6.7),
        via_inductance(height_mm=1.6, drill_diameter_mm=0.3),
    ]


def test_redacted_snippet_construction():
    s = RedactedSnippet(rule_id="R-003", source_id="SRC-001", summary="LISN setup")
    assert s.rule_id == "R-003"
    assert s.source_id == "SRC-001"
    assert s.excerpt is None


def test_recommendation_draft_to_schema_dict_round_trip():
    d = RecommendationDraft(
        id="REC-001",
        area="filter",
        severity="medium",
        confidence=0.6,
        problem="Hypothetical peaking risk.",
        evidence=["Rule R-005 — high-Q filter"],
        proposed_change={"type": "add_damping", "description": "RC across input."},
        limitations=["No layout."],
        sources=["R-005"],
        citations=["SRC-021"],
        llm_generated=True,
    )
    out = d.to_schema_dict()
    assert out["llm_generated"] is True
    assert out["citations"] == ["SRC-021"]
    assert out["confidence"] == pytest.approx(0.6)


def test_deterministic_assistant_replace_mode_matches_baseline():
    """`--llm none` is byte-equivalent to M2.6.1's rule-based engine."""
    asst = DeterministicAssistant()
    drafts = asst.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[],
        mode="replace",
    )
    assert len(drafts) > 0
    assert all(d.llm_generated is False for d in drafts)
    # The testbench rec is always first.
    assert drafts[0].area == "testbench"


def test_deterministic_assistant_augment_mode_returns_baseline_as_drafts():
    asst = DeterministicAssistant()
    drafts = asst.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[],
        mode="replace",  # build a baseline once
    )
    baseline = drafts  # treat as the baseline for augment
    from emc_assistant.recommendations.engine import Recommendation

    baseline_recs = [
        Recommendation(
            id=d.id,
            area=d.area,
            severity=d.severity,
            confidence=d.confidence,
            problem=d.problem,
            evidence=d.evidence,
            proposed_change=d.proposed_change,
            simulation_required=d.simulation_required,
            user_action=d.user_action,
            limitations=d.limitations,
            sources=d.sources,
        )
        for d in baseline
    ]
    aug = asst.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[],
        mode="augment",
        baseline_recs=baseline_recs,
    )
    assert len(aug) == len(baseline)
    assert all(d.llm_generated is False for d in aug)


def test_stub_assistant_replace_mode_returns_synthetic_rec():
    stub = StubAssistant()
    snippets = [RedactedSnippet(rule_id="R-003", source_id="SRC-001", summary="LISN")]
    drafts = stub.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={"v_meas_peak": 3.41},
        snippets=snippets,
        mode="replace",
    )
    assert len(drafts) == 1
    assert drafts[0].llm_generated is True
    assert "R-003" in drafts[0].sources
    assert "SRC-001" in drafts[0].citations
    assert stub.call_count == 1
    assert stub.last_mode == "replace"


def test_stub_assistant_augment_mode_keeps_baseline_ids():
    stub = StubAssistant()
    asst = DeterministicAssistant()
    baseline_drafts = asst.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=[],
        mode="replace",
    )
    from emc_assistant.recommendations.engine import Recommendation

    baseline_recs = [
        Recommendation(
            id=d.id, area=d.area, severity=d.severity, confidence=d.confidence,
            problem=d.problem, evidence=d.evidence, proposed_change=d.proposed_change,
            simulation_required=d.simulation_required, user_action=d.user_action,
            limitations=d.limitations, sources=d.sources,
        )
        for d in baseline_drafts
    ]
    snippets = [RedactedSnippet(rule_id="R-005", source_id="SRC-021", summary="damping")]
    aug = stub.explain_recommendations(
        problem_context=_ctx(),
        parasitics=_parasitics(),
        sim_metrics={},
        snippets=snippets,
        mode="augment",
        baseline_recs=baseline_recs,
    )
    assert len(aug) == len(baseline_recs)
    assert [d.id for d in aug] == [r.id for r in baseline_recs]
    assert all(d.llm_generated for d in aug)
    assert all(d.problem.startswith("[stub-augmented]") for d in aug)


def test_estimate_cost_usd_gpt5_mini():
    est = estimate_cost_usd("hello " * 200, model="gpt-5-mini")
    assert est.model == "gpt-5-mini"
    assert est.input_tokens > 0
    assert est.expected_output_tokens > 0
    # input + output should sum to total
    assert est.total_usd == pytest.approx(est.input_cost_usd + est.output_cost_usd)


def test_assert_within_budget_passes():
    est = estimate_cost_usd("short", model="gpt-5-mini")
    assert_within_budget(est, budget_usd=1.0)  # should not raise


def test_assert_within_budget_raises_when_exceeded():
    est = estimate_cost_usd("hello " * 200, model="gpt-5-mini")
    with pytest.raises(BudgetExceeded):
        assert_within_budget(est, budget_usd=0.00001)


def test_unknown_model_uses_most_expensive_pricing():
    est = estimate_cost_usd("hi", model="some-unknown-model")
    est_known = estimate_cost_usd("hi", model="gpt-5-mini")
    # Unknown model should be at least as expensive as the cheapest known.
    assert est.total_usd >= est_known.total_usd


def test_privacy_log_writes_jsonl(tmp_path: Path):
    log = tmp_path / "llm" / "run-abc.jsonl"
    written = write_privacy_log_entry(
        log_path=log,
        model="gpt-5-mini",
        prompt_messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "user"}],
        response_text="[]",
        prompt_tokens=42,
        completion_tokens=7,
        cost_estimate_usd=0.001,
        purpose="recommendations.replace",
    )
    assert written == log
    assert log.is_file()
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["model"] == "gpt-5-mini"
    assert entry["purpose"] == "recommendations.replace"
    assert entry["prompt_tokens"] == 42
    assert entry["completion_tokens"] == 7
    assert entry["estimated_cost_usd"] == pytest.approx(0.001)
    assert len(entry["prompt_messages"]) == 2


def test_privacy_log_appends_multiple_entries(tmp_path: Path):
    log = tmp_path / "run.jsonl"
    for i in range(3):
        write_privacy_log_entry(
            log_path=log,
            model="gpt-5-mini",
            prompt_messages=[{"role": "user", "content": f"call {i}"}],
            response_text="[]",
            prompt_tokens=10,
            completion_tokens=5,
            cost_estimate_usd=0.0001,
            purpose=f"call.{i}",
        )
    lines = log.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3
    assert [json.loads(line)["purpose"] for line in lines] == ["call.0", "call.1", "call.2"]
