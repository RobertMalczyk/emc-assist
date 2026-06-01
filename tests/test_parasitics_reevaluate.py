"""Tests for the M2.17 LLM/RAG parasitic value re-evaluation pass.

Covers ParasiticsAgent.reevaluate_values: it returns citation-backed
min/typ/max band *proposals* and fails safe to the deterministic prior
(omits the net) on any LLM error, malformed response, or unusable band.
The service-layer use case (apply / audit / report disclosure) is tested
separately.
"""

from __future__ import annotations

import json

from emc_assistant.agents.parasitics_agent import ParasiticsAgent


class _FakeAssistant:
    """Minimal LLM stand-in — only needs `complete()`."""

    def __init__(self, response):
        self.response = response
        self.calls: list = []

    def complete(self, *, messages, purpose, expected_output_tokens=1600):
        self.calls.append((messages, purpose))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _candidates():
    return [
        {
            "net": "VIN",
            "role": "power_rail",
            "prior": {"r_band": [1e-3, 3e-3, 9e-3], "l_band": [5e-9, 1e-8, 3e-8],
                      "c_band": [1e-12, 3e-12, 9e-12]},
            "snippets": [{"rule_id": "R1", "source_id": "S032", "summary": "trace L"}],
        },
        {
            "net": "SW",
            "role": "switching_node",
            "prior": {"r_band": [1e-3, 4e-3, 1e-2], "l_band": [6e-9, 1.5e-8, 4e-8],
                      "c_band": [1e-12, 3e-12, 9e-12]},
            "snippets": [{"rule_id": "R2", "source_id": "S033", "summary": "hot loop"}],
        },
    ]


def _refined(net, r, l, c, **extra):
    out = {"net": net, "r_band": r, "l_band": l, "c_band": c}
    out.update(extra)
    return out


def test_reevaluate_parses_refined_bands_and_citations():
    resp = json.dumps({"refined": [
        _refined("VIN", [2e-3, 5e-3, 1e-2], [6e-9, 1.2e-8, 3.5e-8], [1e-12, 2.7e-12, 8e-12],
                 confidence=0.7, rationale="per S032", cited_sources=["S032"]),
    ]})
    out = ParasiticsAgent().reevaluate_values(
        _candidates(), assistant=_FakeAssistant(resp), context_line="ctx")
    assert set(out) == {"VIN"}  # SW omitted by the model → caller keeps its prior
    v = out["VIN"]
    assert v["r_band"] == [2e-3, 5e-3, 1e-2]
    assert v["confidence"] == 0.7
    assert v["cited_sources"] == ["S032"]
    assert "S032" in v["rationale"]


def test_reevaluate_failsafe_on_llm_error():
    out = ParasiticsAgent().reevaluate_values(
        _candidates(), assistant=_FakeAssistant(RuntimeError("boom")), context_line="ctx")
    assert out == {}  # keep all deterministic priors


def test_reevaluate_failsafe_on_malformed_json():
    out = ParasiticsAgent().reevaluate_values(
        _candidates(), assistant=_FakeAssistant("not json at all"), context_line="ctx")
    assert out == {}


def test_reevaluate_skips_net_with_unusable_band_keeps_others():
    resp = json.dumps({"refined": [
        _refined("VIN", [1e-3, 3e-3], [5e-9, 1e-8, 3e-8], [1e-12, 3e-12, 9e-12]),  # r_band only 2 → skip
        _refined("SW", {"min": 2e-3, "typ": 5e-3, "max": 1e-2}, [6e-9, 1.2e-8, 3.5e-8],
                 [1e-12, 2.7e-12, 8e-12], cited_sources=["S033"]),  # dict band → coerced
    ]})
    out = ParasiticsAgent().reevaluate_values(
        _candidates(), assistant=_FakeAssistant(resp), context_line="ctx")
    assert "VIN" not in out
    assert out["SW"]["r_band"] == [2e-3, 5e-3, 1e-2]


def test_reevaluate_sorts_band_and_rejects_nonpositive():
    resp = json.dumps({"refined": [
        _refined("VIN", [9e-3, 1e-3, 3e-3], [5e-9, 1e-8, 3e-8], [1e-12, 3e-12, 9e-12]),  # out of order
        _refined("SW", [0, 3e-3, 9e-3], [5e-9, 1e-8, 3e-8], [1e-12, 3e-12, 9e-12]),  # 0 ohm → reject
    ]})
    out = ParasiticsAgent().reevaluate_values(
        _candidates(), assistant=_FakeAssistant(resp), context_line="ctx")
    assert out["VIN"]["r_band"] == [1e-3, 3e-3, 9e-3]  # sorted to min/typ/max
    assert "SW" not in out  # non-positive value rejected


def test_reevaluate_missing_citations_still_returned_but_empty():
    """A refined band with no cited source is still a proposal (caller flags
    it engineering_estimate); cited_sources comes back as []."""
    resp = json.dumps({"refined": [
        _refined("VIN", [2e-3, 5e-3, 1e-2], [6e-9, 1.2e-8, 3.5e-8], [1e-12, 2.7e-12, 8e-12]),
    ]})
    out = ParasiticsAgent().reevaluate_values(
        _candidates(), assistant=_FakeAssistant(resp), context_line="ctx")
    assert out["VIN"]["cited_sources"] == []


def test_reevaluate_empty_candidates_makes_no_call():
    fake = _FakeAssistant("{}")
    assert ParasiticsAgent().reevaluate_values([], assistant=fake, context_line="ctx") == {}
    assert fake.calls == []


# ---- service-level: reevaluate_parasitics (audit / apply / fail-safe) -------

import shutil
from pathlib import Path

import pytest

from emc_assistant.service import parasitics as para_service
from emc_assistant.service.options import CommandOptions
from emc_assistant.service.results import ServiceError

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _copy_example(tmp_path):
    dst = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


class _RefiningAssistant:
    """Echo stub: reads the candidate priors out of the prompt and returns a
    refined band for every net (doubling typ/max) — topology-agnostic."""

    name = "openai"
    budget_tracker = None

    def __init__(self):
        self.calls: list = []

    def complete(self, *, messages, purpose, expected_output_tokens=1600):
        self.calls.append(purpose)
        user = messages[-1]["content"]
        cands = json.loads(user[user.index("["):])  # the candidates JSON array

        def dbl(b):
            return [b[0], b[1] * 2, b[2] * 2]

        refined = [
            {"net": c["net"], "r_band": dbl(c["prior"]["r_band"]),
             "l_band": dbl(c["prior"]["l_band"]), "c_band": dbl(c["prior"]["c_band"]),
             "confidence": 0.8, "rationale": "stub", "cited_sources": ["S032"]}
            for c in cands
        ]
        return json.dumps({"refined": refined})


def test_service_reevaluate_writes_audit_with_full_bands_and_provenance(tmp_path):
    project = _copy_example(tmp_path)
    res = para_service.reevaluate_parasitics(
        str(project), CommandOptions(stub_assistant=_RefiningAssistant()), apply=False)
    assert res.audit_path.is_file()
    assert res.considered > 0
    assert res.refined_count == res.considered  # the stub refines every target
    assert res.cited_count == res.considered

    audit = json.loads(res.audit_path.read_text(encoding="utf-8"))["nets"]
    one = next(n for n in audit if n["refined"])
    assert one["value_source"] == "llm_rag"
    assert len(one["prior"]["r_band"]) == 3 and len(one["refined"]["r_band"]) == 3  # full min/typ/max
    assert "typ_delta_pct" in one and one["refined"]["cited_sources"] == ["S032"]

    # apply=False → user_context untouched
    uc = json.loads((project / "input" / "user_context.json").read_text("utf-8"))
    assert not (uc.get("parasitics") or {}).get("per_net")


def test_service_reevaluate_apply_persists_typ_only(tmp_path):
    project = _copy_example(tmp_path)
    res = para_service.reevaluate_parasitics(
        str(project), CommandOptions(stub_assistant=_RefiningAssistant()), apply=True)
    assert res.applied == res.refined_count > 0

    per_net = json.loads(
        (project / "input" / "user_context.json").read_text("utf-8"))["parasitics"]["per_net"]
    assert per_net
    sample = next(iter(per_net.values()))
    # only typ values land as overrides (+ any preserved skip) — never bands
    assert set(sample) <= {"r_mohm", "l_nh", "c_pf", "skip"}
    assert {"r_mohm", "l_nh", "c_pf"} <= set(sample)
    assert "r_band" not in sample


def test_service_reevaluate_failsafe_keeps_priors_on_llm_error(tmp_path):
    project = _copy_example(tmp_path)

    class _Boom:
        name = "openai"
        budget_tracker = None

        def complete(self, **kwargs):
            raise RuntimeError("boom")

    res = para_service.reevaluate_parasitics(
        str(project), CommandOptions(stub_assistant=_Boom()), apply=True)
    assert res.refined_count == 0 and res.applied == 0
    audit = json.loads(res.audit_path.read_text("utf-8"))["nets"]
    assert audit and all(
        n["refined"] is None and n["value_source"] == "rule_of_thumb" for n in audit)


def test_service_reevaluate_requires_llm(tmp_path):
    project = _copy_example(tmp_path)
    with pytest.raises(ServiceError):
        para_service.reevaluate_parasitics(str(project), CommandOptions(), apply=False)


def test_apply_reevaluated_persists_typ_from_audit_no_llm(tmp_path):
    """The accept step reads the audit a preview wrote and persists typ-only —
    no second LLM call."""
    project = _copy_example(tmp_path)
    para_service.reevaluate_parasitics(  # preview writes the audit
        str(project), CommandOptions(stub_assistant=_RefiningAssistant()), apply=False)
    res = para_service.apply_reevaluated_parasitics(str(project))  # no assistant needed
    assert res.applied > 0
    per_net = json.loads(
        (project / "input" / "user_context.json").read_text("utf-8"))["parasitics"]["per_net"]
    sample = next(iter(per_net.values()))
    assert {"r_mohm", "l_nh", "c_pf"} <= set(sample) and "r_band" not in sample


def test_apply_reevaluated_requires_audit(tmp_path):
    project = _copy_example(tmp_path)
    with pytest.raises(ServiceError):
        para_service.apply_reevaluated_parasitics(str(project))  # no audit yet
