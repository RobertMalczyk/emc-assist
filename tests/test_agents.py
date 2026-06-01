"""Tests for the specialist-agent layer (M2.9).

Covers:

- per-agent deterministic fallback produces a schema-valid AgentFinding,
- ``Agent.parse_response`` handles good JSON, fenced JSON, malformed text,
- the orchestrator fans out to all 10 agents, writes JSON per area,
- the stub-LLM path returns ``llm_generated=True`` findings,
- ``BudgetTracker`` cumulative cap halts the orchestrator mid-run,
- a malformed LLM response triggers the deterministic fallback for
  *that* agent without taking down the rest of the run.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from emc_assistant.agents import (
    Agent,
    AgentContext,
    AgentInputs,
)
from emc_assistant.agents.base import (
    build_minimal_deterministic_finding,
    parse_json_object,
    select_metrics_by_prefix,
    select_snippets_by_keywords,
)
from emc_assistant.agents.dcdc_agent import DcDcAgent
from emc_assistant.agents.decoupling_agent import DecouplingAgent
from emc_assistant.agents.filtering_agent import FilteringAgent
from emc_assistant.agents.high_speed_agent import HighSpeedAgent
from emc_assistant.agents.ic_vendor_agent import IcVendorAgent
from emc_assistant.agents.layout_risk_agent import LayoutRiskAgent
from emc_assistant.agents.mixed_signal_agent import MixedSignalAgent
from emc_assistant.agents.orchestrator import (
    AGENT_CLASSES,
    list_agent_names,
    run_agents,
)
from emc_assistant.agents.parasitics_agent import ParasiticsAgent
from emc_assistant.agents.power_integrity_agent import PowerIntegrityAgent
from emc_assistant.agents.stackup_agent import StackupAgent
from emc_assistant.llm.assistant import ProblemContext, RedactedSnippet
from emc_assistant.llm.budget import BudgetExceeded, BudgetTracker, CostEstimate
from emc_assistant.llm.stub import StubAssistant
from emc_assistant.schemas import require_valid


def _problem_ctx() -> ProblemContext:
    return ProblemContext(
        project_id="case_test",
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


def _agent_ctx() -> AgentContext:
    snippets = [
        RedactedSnippet(
            rule_id="R-001",
            source_id="SRC-031",
            summary="Low-EMI DC/DC: input filter resonance below 5× F_sw.",
        ),
        RedactedSnippet(
            rule_id="R-074",
            source_id="SRC-074",
            summary="SLUA929: input filter damping prevents oscillation.",
        ),
    ]
    return AgentContext(
        problem_context=_problem_ctx(),
        parasitics=[],
        sim_metrics={
            "v_meas_peak": 3.41,
            "dm_peak": 3.65,
            "cm_peak": 2.3e-7,
            "v_meas_band_peak_dbuv_150000_30000000": 66.2,
            "vrms": 0.643,
        },
        snippets=snippets,
        baseline_recs=[],
    )


# -- Helpers ----------------------------------------------------------------


def test_select_snippets_by_keywords_returns_matches():
    snippets = [
        RedactedSnippet(rule_id="R-1", source_id="SRC-A", summary="input filter damping"),
        RedactedSnippet(rule_id="R-2", source_id="SRC-B", summary="layout return paths"),
        RedactedSnippet(rule_id="R-3", source_id="SRC-C", summary="ferrite bead choices"),
    ]
    result = select_snippets_by_keywords(snippets, ["filter", "ferrite"])
    assert {s.rule_id for s in result} == {"R-1", "R-3"}


def test_select_snippets_falls_back_when_no_match():
    snippets = [
        RedactedSnippet(rule_id="R-1", source_id="SRC-A", summary="alpha"),
        RedactedSnippet(rule_id="R-2", source_id="SRC-B", summary="beta"),
    ]
    result = select_snippets_by_keywords(snippets, ["zzz"], fallback_top_k=1)
    assert result == [snippets[0]]


def test_select_metrics_by_prefix_returns_matching_keys():
    metrics = {"dm_peak": 1.0, "v_meas_peak": 2.0, "tnom": 25.0}
    result = select_metrics_by_prefix(metrics, ["dm_", "v_meas"])
    assert "tnom" not in result
    assert "dm_peak" in result and "v_meas_peak" in result


def test_select_metrics_falls_back_when_nothing_matches():
    metrics = {"a": 1.0, "b": 2.0}
    result = select_metrics_by_prefix(metrics, ["nope"])
    assert result == metrics


# -- parse_response ---------------------------------------------------------


def test_parse_json_object_handles_plain_json():
    data = parse_json_object('{"confidence": 0.5, "findings": []}')
    assert data["confidence"] == 0.5


def test_parse_json_object_handles_fenced_json():
    data = parse_json_object('```json\n{"confidence": 0.5}\n```')
    assert data["confidence"] == 0.5


def test_parse_json_object_rejects_non_object():
    with pytest.raises(ValueError):
        parse_json_object("[]")


def test_parse_json_object_rejects_malformed():
    with pytest.raises(ValueError):
        parse_json_object("not json at all")


# -- Each agent's deterministic path produces a valid finding ----------------


_AGENT_CLASSES_FOR_TEST: list[type[Agent]] = [
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
]


@pytest.mark.parametrize("cls", _AGENT_CLASSES_FOR_TEST, ids=lambda c: c.name)
def test_deterministic_finding_validates_against_schema(cls: type[Agent]):
    agent = cls()
    ctx = _agent_ctx()
    inputs = agent.select_relevant(ctx)
    finding = agent.deterministic_finding(inputs)
    assert finding.agent == agent.name
    assert finding.llm_generated is False
    assert len(finding.findings) >= 1, f"{agent.name} emitted zero findings"
    assert len(finding.recommendations) >= 1, f"{agent.name} emitted zero recs"
    # Schema-valid.
    require_valid("agent_finding.schema.json", finding.to_schema_dict())


def test_minimal_deterministic_finding_helper_validates():
    inputs = AgentInputs(problem_context=_problem_ctx())
    finding = build_minimal_deterministic_finding(
        agent_name="test_agent",
        area_title="Test area",
        inputs=inputs,
        focus="focus text",
        sweep_description="sweep text",
        confidence=0.4,
    )
    require_valid("agent_finding.schema.json", finding.to_schema_dict())
    assert finding.confidence == 0.4
    assert finding.simulation_requests, "sweep_description should produce a sim request"


# -- Orchestrator -----------------------------------------------------------


def test_run_agents_fans_out_to_all_active_agents(tmp_path: Path):
    """Default registry: 10 active agents, all run, all files written."""
    ctx = _agent_ctx()
    result = run_agents(ctx, assistant=None, output_dir=tmp_path)
    assert len(result.findings) == 11
    expected_names = list_agent_names()
    actual_names = [f.agent for f in result.findings]
    assert actual_names == expected_names
    findings_dir = tmp_path / "findings"
    for name in expected_names:
        path = findings_dir / f"{name}.json"
        assert path.is_file(), f"missing {name}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["agent"] == name


def test_run_agents_deterministic_path_emits_non_empty_sections(tmp_path: Path):
    """Acceptance: 10 sections, none silently empty under --llm none."""
    ctx = _agent_ctx()
    result = run_agents(ctx, assistant=None, output_dir=tmp_path)
    for finding in result.findings:
        assert finding.findings or finding.recommendations, (
            f"{finding.agent} produced no findings AND no recommendations"
        )


def test_run_agents_with_stub_marks_llm_generated(tmp_path: Path):
    """When a stub assistant returns valid JSON, the finding is LLM-marked."""
    canned = json.dumps(
        {
            "confidence": 0.7,
            "findings": [
                {"title": "stub finding", "detail": "stub text", "severity": "info"}
            ],
            "risks": [],
            "recommendations": [
                {
                    "id": "REC-001",
                    "area": "dcdc",
                    "severity": "info",
                    "confidence": 0.7,
                    "problem": "stub problem",
                    "evidence": ["stub evidence"],
                    "proposed_change": {
                        "type": "investigate",
                        "description": "stub change",
                    },
                    "sources": ["R-001"],
                    "citations": ["SRC-031"],
                    "limitations": [],
                    "simulation_required": True,
                    "user_action": "",
                }
            ],
            "missing_data": [],
            "simulation_requests": [],
            "sources": ["R-001"],
            "limitations": [],
        }
    )
    stub = StubAssistant(canned_completion=canned)
    ctx = _agent_ctx()
    result = run_agents(ctx, assistant=stub, output_dir=tmp_path)
    assert len(result.findings) == 11
    for finding in result.findings:
        assert finding.llm_generated is True
        assert any(f.title == "stub finding" for f in finding.findings)
    # Stub was called exactly once per agent.
    assert len(stub.complete_calls) == 11
    purposes = sorted(p for _, p in stub.complete_calls)
    assert all(p.startswith("agent.") for p in purposes)


def test_run_agents_falls_back_when_llm_returns_garbage(tmp_path: Path):
    """Malformed JSON from one agent ⇒ deterministic fallback, run continues."""
    stub = StubAssistant(canned_completion="this is not JSON")
    ctx = _agent_ctx()
    result = run_agents(ctx, assistant=stub, output_dir=tmp_path)
    assert len(result.findings) == 11
    # Every finding was supposed to come from the LLM, but the parser
    # rejected garbage and fell back. The Agent.run() path appends a
    # "malformed" limitation rather than recording in failed_agents.
    for finding in result.findings:
        assert finding.llm_generated is False
        assert any("malformed" in lim.lower() for lim in finding.limitations)


def test_run_agents_handles_assistant_exception(tmp_path: Path):
    """If complete() raises, that agent falls back; the rest continue."""

    class BoomAssistant(StubAssistant):
        def complete(self, **kwargs):  # type: ignore[override]
            raise RuntimeError("network blew up")

    assistant = BoomAssistant()
    ctx = _agent_ctx()
    result = run_agents(ctx, assistant=assistant, output_dir=tmp_path)
    assert len(result.findings) == 11
    assert set(result.failed_agents) == set(list_agent_names())
    for finding in result.findings:
        assert finding.llm_generated is False
        assert any("LLM call failed" in lim for lim in finding.limitations)


# -- Budget tracker --------------------------------------------------------


def test_budget_tracker_cumulative_cap_blocks_next_call():
    tracker = BudgetTracker(cap_usd=0.05)
    cheap = CostEstimate(
        model="gpt-5-mini",
        input_tokens=100,
        expected_output_tokens=100,
        input_cost_usd=0.02,
        output_cost_usd=0.02,
    )
    # First call fits.
    tracker.assert_can_afford(cheap)
    tracker.record(cheap.total_usd)
    # Second call would exceed.
    with pytest.raises(BudgetExceeded):
        tracker.assert_can_afford(cheap)


def test_run_agents_aborts_remaining_agents_on_budget_exhausted(tmp_path: Path):
    """When the LLM raises BudgetExceeded, the orchestrator runs the
    remaining agents deterministically so the report still has 10 sections.
    """

    class BudgetBomb(StubAssistant):
        def complete(self, **kwargs):  # type: ignore[override]
            raise BudgetExceeded("cap reached")

    ctx = _agent_ctx()
    result = run_agents(ctx, assistant=BudgetBomb(), output_dir=tmp_path)
    assert result.budget_exhausted is True
    assert len(result.findings) == 11
    # All 10 findings are deterministic with a budget-exhaustion note.
    for finding in result.findings:
        assert finding.llm_generated is False
        assert any("budget" in lim.lower() for lim in finding.limitations)


# -- AGENT_CLASSES registry --------------------------------------------------


def test_agent_classes_registry_has_eleven_active_agents():
    """The orchestrator's canonical registry holds 11 active agents (M2.10.1)."""
    assert len(AGENT_CLASSES) == 11
    names = list_agent_names()
    expected = {
        "dcdc",
        "filtering",
        "power_integrity",
        "decoupling",
        "parasitics",
        "stackup",
        "high_speed",
        "mixed_signal",
        "ic_vendor",
        "layout_risk",
        "signal_map",
    }
    assert set(names) == expected
    # acdc / analog stubs must NOT be loaded — they are parked.
    assert "acdc" not in names
    assert "analog" not in names


def test_each_agent_has_a_prompt_file():
    """Every active agent's prompt_filename resolves to a real file."""
    for cls in AGENT_CLASSES:
        agent = cls()
        assert agent.prompt_path.is_file(), (
            f"{agent.name}: prompt {agent.prompt_path} does not exist"
        )
        body = agent.prompt_path.read_text(encoding="utf-8")
        assert len(body) > 200, f"{agent.name} prompt looks empty or stubby"


# -- Build messages --------------------------------------------------------


def test_build_messages_includes_problem_context_and_snippets():
    agent = DcDcAgent()
    ctx = _agent_ctx()
    inputs = agent.select_relevant(ctx)
    messages = agent.build_messages(inputs)
    assert len(messages) == 2
    assert messages[0]["role"] == "system"
    assert messages[1]["role"] == "user"
    user_text = messages[1]["content"]
    assert "DC/DC buck converter" in user_text
    assert "switching_frequency_hz" in user_text
    assert "v_meas_peak" in user_text
    # Snippets are reduced to redacted summaries; no source URLs.
    assert "[R-001 / SRC-031]" in user_text
    assert "http" not in user_text.lower()


# -- M2.9.1 per-agent retrieval --------------------------------------------


def test_select_snippets_uses_retrieve_fn_when_set():
    """When ctx.retrieve_fn is set, the agent issues a focused query
    seeded by its own keywords -- not the shared snippet pool."""
    calls: list[list[str]] = []
    focused = [RedactedSnippet(rule_id="R-FOCUS", source_id="SRC-X", summary="focused hit")]

    def _fake_retrieve(keywords: list[str]) -> list[RedactedSnippet]:
        calls.append(list(keywords))
        return focused

    ctx = _agent_ctx()
    ctx.retrieve_fn = _fake_retrieve
    agent = DcDcAgent()
    inputs = agent.select_relevant(ctx)
    # The agent got the focused result, not the shared ctx.snippets pool.
    assert inputs.snippets == focused
    # retrieve_fn was called with this agent's own keyword list.
    assert calls == [DcDcAgent.keywords]


def test_select_snippets_two_agents_query_with_their_own_keywords():
    """Different agents must drive retrieve_fn with different keyword lists."""

    def _fake_retrieve(keywords: list[str]) -> list[RedactedSnippet]:
        # id encodes the first keyword so the two agents' results differ.
        return [RedactedSnippet(rule_id=f"R-{keywords[0]}", source_id="SRC", summary="x")]

    ctx = _agent_ctx()
    ctx.retrieve_fn = _fake_retrieve
    dec = DecouplingAgent().select_relevant(ctx)
    filt = FilteringAgent().select_relevant(ctx)
    assert dec.snippets != filt.snippets
    assert dec.snippets[0].rule_id == f"R-{DecouplingAgent.keywords[0]}"
    assert filt.snippets[0].rule_id == f"R-{FilteringAgent.keywords[0]}"


def test_select_snippets_falls_back_to_shared_pool_without_retrieve_fn():
    """No retrieve_fn -> keyword-filter the shared ctx.snippets pool (M2.9 behaviour)."""
    ctx = _agent_ctx()  # retrieve_fn defaults to None
    assert ctx.retrieve_fn is None
    inputs = DcDcAgent().select_relevant(ctx)
    assert {s.rule_id for s in inputs.snippets} <= {"R-001", "R-074"}
    assert inputs.snippets, "fallback must still yield something"


def test_select_snippets_falls_back_when_retrieve_fn_returns_empty():
    ctx = _agent_ctx()
    ctx.retrieve_fn = lambda _kw: []
    inputs = DcDcAgent().select_relevant(ctx)
    assert inputs.snippets, "empty retrieve_fn result must trigger fallback"
    assert {s.rule_id for s in inputs.snippets} <= {"R-001", "R-074"}


def test_select_snippets_falls_back_when_retrieve_fn_raises():
    """Retrieval must never break an agent: an exception -> shared-pool fallback."""

    def _boom(_kw):
        raise RuntimeError("vector index unreachable")

    ctx = _agent_ctx()
    ctx.retrieve_fn = _boom
    inputs = DcDcAgent().select_relevant(ctx)
    assert inputs.snippets, "retrieve_fn exception must fall back, not crash"

