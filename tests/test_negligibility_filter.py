"""Tests for the M2.10.7 LLM parasitic-negligibility screen.

Covers ParasiticsAgent.filter_negligible: it drops only the nets the
LLM is confident are negligible, and fails safe (keeps everything) on
any LLM error or malformed response.
"""

from __future__ import annotations

import json

from emc_assistant.agents.injection import SeriesParasitic, ShuntParasitic
from emc_assistant.agents.parasitics_agent import ParasiticsAgent


class _FakeAssistant:
    """Minimal LLM stand-in — only needs `complete()`."""

    def __init__(self, response):
        self.response = response
        self.calls: list = []

    def complete(self, *, messages, purpose, expected_output_tokens=900):
        self.calls.append((messages, purpose))
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def _shunt(net, c=2e-12):
    return ShuntParasitic(net=net, capacitance_f=c, rationale=f"stray C on {net}")


def _verdict(*pairs):
    """Build an LLM response JSON from (net, negligible) pairs."""
    return json.dumps({
        "verdicts": [
            {"net": n, "negligible": neg, "reason": "test"} for n, neg in pairs
        ]
    })


def test_filter_drops_only_negligible_nets():
    entries = [_shunt("N013"), _shunt("VOUT"), _shunt("sw")]
    fake = _FakeAssistant(_verdict(("N013", True), ("VOUT", False), ("sw", False)))
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=fake, context_line="ctx",
    )
    assert {e.net for e in kept} == {"VOUT", "sw"}
    assert len(dropped) == 1
    assert dropped[0]["net"] == "N013"
    assert dropped[0]["kind"] == "shunt"


def test_filter_keeps_net_missing_from_verdicts():
    """A net the LLM forgot to rule on is kept (fail-safe)."""
    entries = [_shunt("A"), _shunt("B")]
    fake = _FakeAssistant(_verdict(("A", True)))  # B omitted
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=fake, context_line="ctx",
    )
    assert {e.net for e in kept} == {"B"}
    assert [d["net"] for d in dropped] == ["A"]


def test_filter_fails_safe_on_llm_error():
    entries = [_shunt("A"), _shunt("B")]
    fake = _FakeAssistant(RuntimeError("budget exceeded"))
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=fake, context_line="ctx",
    )
    assert len(kept) == 2 and dropped == []


def test_filter_fails_safe_on_malformed_json():
    entries = [_shunt("A")]
    fake = _FakeAssistant("not json at all {{{")
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=fake, context_line="ctx",
    )
    assert len(kept) == 1 and dropped == []


def test_filter_tolerates_fenced_json():
    entries = [_shunt("A")]
    fake = _FakeAssistant("```json\n" + _verdict(("A", True)) + "\n```")
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=fake, context_line="ctx",
    )
    assert kept == [] and [d["net"] for d in dropped] == ["A"]


def test_filter_empty_plan():
    fake = _FakeAssistant(_verdict())
    kept, dropped = ParasiticsAgent().filter_negligible(
        [], kind="shunt", assistant=fake, context_line="ctx",
    )
    assert kept == [] and dropped == []
    assert fake.calls == []  # no LLM call for an empty plan


def test_filter_works_on_series_entries():
    entries = [
        SeriesParasitic(net="g1", resistance_ohm=3e-3, inductance_h=5e-9,
                        capacitance_f=1e-12),
        SeriesParasitic(net="g2", resistance_ohm=3e-3, inductance_h=5e-9,
                        capacitance_f=1e-12),
    ]
    fake = _FakeAssistant(_verdict(("g1", False), ("g2", True)))
    kept, dropped = ParasiticsAgent().filter_negligible(
        entries, kind="series", assistant=fake, context_line="ctx",
    )
    assert [e.net for e in kept] == ["g1"]
    assert dropped[0]["kind"] == "series"


def test_filter_sends_one_call_with_all_candidates():
    entries = [_shunt("A"), _shunt("B"), _shunt("C")]
    fake = _FakeAssistant(_verdict(("A", False), ("B", False), ("C", False)))
    ParasiticsAgent().filter_negligible(
        entries, kind="shunt", assistant=fake, context_line="ctx",
    )
    assert len(fake.calls) == 1
    messages, purpose = fake.calls[0]
    assert purpose == "parasitics.negligibility"
    user_msg = messages[-1]["content"]
    assert "A" in user_msg and "B" in user_msg and "C" in user_msg
