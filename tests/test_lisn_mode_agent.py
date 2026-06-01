"""Tests for the M2.10.x LISN-mode agent (12th specialist agent).

The agent runs pre-composition: decide() returns dual vs single LISN.
Covers the deterministic heuristic, the LLM path with a fake assistant,
and the fail-safe behaviour on a bad LLM response.
"""

from __future__ import annotations

import json

import pytest

from emc_assistant.agents.lisn_mode_agent import LisnModeAgent, LisnModeDecision
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import build_topology_report


class _FakeAssistant:
    name = "fake"

    def __init__(self, response):
        self.response = response
        self.calls: list = []

    def complete(self, *, messages, purpose, expected_output_tokens=400):
        self.calls.append((messages, purpose))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _ctx(topology_str="DC/DC buck converter", hypothesis=""):
    return ProblemContext(
        project_id="t", analysis_scope="conducted_emi",
        topology=topology_str, problem_hypothesis=hypothesis,
        has_layout=False, has_stackup=False,
    )


def _topology():
    src = "* t\nVin in 0 DC 24\nR1 in out 1\nCout out 0 10u\n.end\n"
    return build_topology_report(parse_cir(src))


# ---- deterministic heuristic ----------------------------------------------


def test_deterministic_defaults_to_dual():
    d = LisnModeAgent().decide(topology=_topology(), problem_context=_ctx(), assistant=None)
    assert d.mode == "dual"
    assert d.source == "deterministic"
    assert 0.0 < d.confidence <= 1.0


def test_deterministic_picks_single_on_chassis_hint():
    ctx = _ctx(hypothesis="return is bonded to the chassis / earth")
    d = LisnModeAgent().decide(topology=_topology(), problem_context=ctx, assistant=None)
    assert d.mode == "single"


def test_deterministic_decision_without_topology():
    d = LisnModeAgent().decide(topology=None, problem_context=_ctx(), assistant=None)
    assert d.mode in ("dual", "single")


# ---- LLM path --------------------------------------------------------------


def test_llm_path_returns_llm_decision():
    fake = _FakeAssistant(json.dumps(
        {"lisn_mode": "single", "confidence": 0.8, "rationale": "chassis return"}
    ))
    d = LisnModeAgent().decide(
        topology=_topology(), problem_context=_ctx(), assistant=fake,
    )
    assert d.mode == "single"
    assert d.source == "llm"
    assert d.confidence == pytest.approx(0.8)
    assert len(fake.calls) == 1
    assert fake.calls[0][1] == "agent.lisn_mode"


def test_llm_path_tolerates_fenced_json():
    fake = _FakeAssistant(
        "```json\n" + json.dumps(
            {"lisn_mode": "dual", "confidence": 0.7, "rationale": "ok"}
        ) + "\n```"
    )
    d = LisnModeAgent().decide(topology=_topology(), problem_context=_ctx(), assistant=fake)
    assert d.mode == "dual" and d.source == "llm"


def test_llm_bad_mode_falls_back_to_heuristic():
    fake = _FakeAssistant(json.dumps(
        {"lisn_mode": "triple", "confidence": 0.9, "rationale": "nonsense"}
    ))
    d = LisnModeAgent().decide(topology=_topology(), problem_context=_ctx(), assistant=fake)
    assert d.mode == "dual"  # heuristic default
    assert d.source == "deterministic"


def test_llm_error_falls_back_to_heuristic():
    fake = _FakeAssistant(RuntimeError("budget exceeded"))
    d = LisnModeAgent().decide(topology=_topology(), problem_context=_ctx(), assistant=fake)
    assert d.mode in ("dual", "single")
    assert d.source == "deterministic"


def test_llm_malformed_json_falls_back():
    fake = _FakeAssistant("not json at all")
    d = LisnModeAgent().decide(topology=_topology(), problem_context=_ctx(), assistant=fake)
    assert d.source == "deterministic"


# ---- decision serialisation + ABC finding ---------------------------------


def test_decision_to_dict():
    d = LisnModeDecision(mode="dual", confidence=0.6, rationale="r", source="llm")
    out = d.to_dict()
    assert out == {
        "lisn_mode": "dual", "confidence": 0.6, "rationale": "r", "source": "llm",
    }


def test_deterministic_finding_is_well_formed():
    from emc_assistant.agents.base import AgentContext

    agent = LisnModeAgent()
    ctx = AgentContext(problem_context=_ctx(), topology=_topology())
    finding = agent.deterministic_finding(agent.select_relevant(ctx))
    assert finding.agent == "lisn_mode"
    assert finding.findings and finding.findings[0].title.startswith("LISN mode:")
    assert finding.recommendations
    assert finding.llm_generated is False
