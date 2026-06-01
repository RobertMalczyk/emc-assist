"""Tests for the M2.18 waveform-trace suggestion agent."""

from __future__ import annotations

import json

from emc_assistant.agents.waveform_trace_agent import WaveformTraceAgent


def _kinds(voltages: list[str], currents: list[str]) -> dict[str, str]:
    k = {n: "voltage" for n in voltages}
    k.update({n: "device_current" for n in currents})
    return k


# A representative case_002-like trace inventory.
VOLT = ["V(meas)", "V(cm)", "V(dm)", "V(vin)", "V(vout)", "V(n005)"]
CURR = ["I(Rload)", "I(V_RAIL)", "I(L1)", "Id(M1)", "I(C1)"]
ALL = VOLT + CURR
KINDS = _kinds(VOLT, CURR)


class _StubAssistant:
    """Minimal LLM stub: returns a canned JSON reply (or raises)."""

    name = "stub"

    def __init__(self, reply: str | None = None, *, raises: bool = False):
        self._reply = reply
        self._raises = raises

    def complete(self, *, messages, purpose, expected_output_tokens=0):
        if self._raises:
            raise RuntimeError("boom")
        return self._reply


def test_default_is_load_current():
    res = WaveformTraceAgent().suggest(available_traces=ALL, kinds=KINDS)
    assert res.default.trace == "I(Rload)"
    assert res.default.unit == "A"
    assert res.default.source == "default"


def test_default_falls_back_to_output_voltage_without_load_current():
    volt = ["V(meas)", "V(vout)", "V(cm)"]
    res = WaveformTraceAgent().suggest(
        available_traces=volt, kinds=_kinds(volt, []),
    )
    assert res.default.trace == "V(vout)"
    assert res.default.unit == "V"


def test_heuristic_picks_emi_relevant_traces():
    res = WaveformTraceAgent().suggest(available_traces=ALL, kinds=KINDS)
    assert res.llm_generated is False
    assert len(res.suggestions) == 4
    chosen = {s.trace for s in res.suggestions}
    # Input current + a switch/inductor current + CM probe are all relevant.
    assert "I(V_RAIL)" in chosen
    assert "V(cm)" in chosen
    assert chosen & {"I(L1)", "Id(M1)"}


def test_suggestions_exclude_primary_and_default():
    res = WaveformTraceAgent().suggest(
        available_traces=ALL, kinds=KINDS, primary_trace="V(meas)",
    )
    names = {s.trace for s in res.suggestions}
    assert "V(meas)" not in names          # primary
    assert res.default.trace not in names  # default


def test_units_track_trace_kind():
    res = WaveformTraceAgent().suggest(available_traces=ALL, kinds=KINDS)
    for s in res.suggestions:
        expected = "A" if s.trace in CURR else "V"
        assert s.unit == expected


def test_llm_path_keeps_valid_traces_and_drops_unknown():
    reply = json.dumps({"suggestions": [
        {"trace": "V(cm)", "label": "CM", "reason": "cm noise"},
        {"trace": "I(DoesNotExist)", "label": "x", "reason": "bogus"},
        {"trace": "V(meas)", "label": "primary", "reason": "should be excluded"},
    ]})
    res = WaveformTraceAgent().suggest(
        available_traces=ALL, kinds=KINDS, assistant=_StubAssistant(reply),
    )
    assert res.llm_generated is True
    names = [s.trace for s in res.suggestions]
    assert "V(cm)" in names              # valid LLM pick kept
    assert "I(DoesNotExist)" not in names  # unknown dropped
    assert "V(meas)" not in names          # primary excluded
    # padded back up to four from the heuristic
    assert len(res.suggestions) == 4
    assert any(s.source == "llm" for s in res.suggestions)


def test_llm_failure_falls_back_to_heuristic():
    res = WaveformTraceAgent().suggest(
        available_traces=ALL, kinds=KINDS, assistant=_StubAssistant(raises=True),
    )
    assert res.llm_generated is False
    assert len(res.suggestions) == 4


def test_to_dict_options_lead_with_default():
    res = WaveformTraceAgent().suggest(available_traces=ALL, kinds=KINDS)
    d = res.to_dict()
    assert d["options"][0]["trace"] == res.default.trace
    assert len(d["options"]) == 1 + len(res.suggestions)
    assert d["llm_generated"] is False
