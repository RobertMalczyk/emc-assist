"""Tests for the M2.10.1 feature-keeper / signal-map layer.

Covers:

- ASC FLAG parsing (with cp1252 / latin-1 encoding tolerance),
- .cir net-name heuristic detection,
- merge ordering (user > asc > cir, dedup by expr),
- signal_map_agent deterministic finding (dormant + active path),
- composer emits per-signal .meas directives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from emc_assistant.agents.base import AgentContext
from emc_assistant.agents.signal_map_agent import SignalMapAgent
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.netlist.signals import (
    Signal,
    TargetBand,
    _normalise_name,
    detect_signals,
    detect_signals_from_cir,
    merge_signal_maps,
    parse_asc_flags,
    signals_from_user_context,
)
from emc_assistant.schemas import require_valid
from emc_assistant.testbench.composer import TestbenchPlan, compose_testbench_cir


REPO_ROOT = Path(__file__).resolve().parents[1]
BUCK_DEMO = REPO_ROOT / "examples" / "case_001_buck_conducted_emi" / "input" / "buck_demo.cir"
ADM1281_ASC = REPO_ROOT / "examples" / "case_002_DCDC" / "input" / "ADM1281-3.asc"


# ---- normalise_name ----


@pytest.mark.parametrize(
    "label,expected",
    [
        ("VIN", "Vin"),
        ("VOUT", "Vout"),
        ("vin", "Vin"),
        ("vout", "Vout"),
        ("out", "Vout"),
        ("in", "Vin"),
        ("V_5V", "V_5V"),
        ("VS_AUX", "VS_AUX"),
        ("n_out", "Vout"),
    ],
)
def test_normalise_name(label, expected):
    assert _normalise_name(label) == expected


# ---- parse_asc_flags ----


def test_parse_asc_flags_extracts_user_labels():
    labels = parse_asc_flags(ADM1281_ASC)
    # ADM1281-3 schematic has VIN and VOUT flag labels.
    assert "VIN" in labels
    assert "VOUT" in labels
    # Normalised: VIN -> Vin, VOUT -> Vout
    assert labels["VIN"] == "Vin"
    assert labels["VOUT"] == "Vout"


def test_parse_asc_flags_skips_ground():
    labels = parse_asc_flags(ADM1281_ASC)
    assert "0" not in labels


def test_parse_asc_flags_missing_file_returns_empty(tmp_path):
    assert parse_asc_flags(tmp_path / "does_not_exist.asc") == {}


# ---- detect_signals_from_cir ----


def test_detect_signals_from_cir_buck_demo():
    sigs = detect_signals_from_cir(BUCK_DEMO)
    names = {s.name for s in sigs}
    # `out` net should be detected and normalised to Vout.
    assert "Vout" in names


# ---- merge_signal_maps ----


def test_merge_signal_maps_user_priority():
    user = [Signal(name="Vout", kind="voltage", expr="V(out)", source="user", confidence=1.0)]
    asc = [
        Signal(
            name="Vout",
            kind="voltage",
            expr="V(out)",  # duplicate expr — should be dropped
            source="auto",
            confidence=0.85,
        )
    ]
    cir = [Signal(name="Vin", kind="voltage", expr="V(in)", source="auto", confidence=0.6)]
    merged = merge_signal_maps(asc, cir, user)
    # user entry survives; asc duplicate dropped; cir 'Vin' added.
    assert len(merged) == 2
    assert merged[0].source == "user"
    assert merged[1].name == "Vin"


def test_merge_dedupes_by_expr_and_uniquifies_names():
    asc = [Signal(name="Vout", kind="voltage", expr="V(OUT)", source="auto")]
    cir = [Signal(name="Vout", kind="voltage", expr="V(out)", source="auto")]
    merged = merge_signal_maps(asc, cir, [])
    # Two different expressions, two signals. The .cir one gets uniquified.
    assert len(merged) == 2
    assert merged[1].name == "Vout_2"


# ---- detect_signals (top-level) ----


def test_detect_signals_combines_sources():
    sigs = detect_signals(asc_path=ADM1281_ASC, cir_path=None)
    names = {s.name for s in sigs}
    assert {"Vin", "Vout"}.issubset(names)


# ---- signals_from_user_context ----


def test_signals_from_user_context_reads_block():
    uc = {
        "signals": [
            {
                "name": "Vload",
                "kind": "voltage",
                "expr": "V(load)",
                "unit": "V",
                "target_band": {"min": 4.9, "typ": 5.0, "max": 5.1},
                "rationale": "user-supplied",
            }
        ]
    }
    sigs = signals_from_user_context(uc)
    assert len(sigs) == 1
    s = sigs[0]
    assert s.name == "Vload"
    assert s.source == "user"
    assert s.confidence == 1.0
    assert s.target_band is not None
    assert s.target_band.typ == 5.0


def test_signals_from_user_context_handles_empty():
    assert signals_from_user_context({}) == []
    assert signals_from_user_context({"signals": []}) == []
    assert signals_from_user_context({"signals": "not a list"}) == []


# ---- Signal serialisation against schema ----


def test_signal_to_schema_dict_validates():
    s = Signal(
        name="Vout",
        kind="voltage",
        expr="V(out)",
        unit="V",
        target_band=TargetBand(min=4.9, typ=5.0, max=5.1),
        source="auto",
        confidence=0.85,
        rationale="auto-detected",
        from_label="VOUT",
    )
    require_valid("signal_map.schema.json", s.to_schema_dict())


def test_signal_name_must_be_valid_identifier():
    """Schema enforces ^[A-Za-z_][A-Za-z0-9_]*$ for name."""
    s = Signal(name="3Vout", kind="voltage", expr="V(out)", source="auto")
    # Cannot validate — starts with digit.
    from emc_assistant.schemas import validate_against
    errors = validate_against("signal_map.schema.json", s.to_schema_dict())
    assert errors and any("name" in e for e in errors)


# ---- SignalMapAgent deterministic ----


def _problem_ctx() -> ProblemContext:
    return ProblemContext(
        project_id="t",
        analysis_scope="conducted_emi",
        has_layout=False,
        has_stackup=False,
    )


def test_signal_map_agent_dormant_when_map_empty():
    agent = SignalMapAgent()
    ctx = AgentContext(problem_context=_problem_ctx(), signals=[])
    inputs = agent.select_relevant(ctx)
    finding = agent.deterministic_finding(inputs)
    assert finding.agent == "signal_map"
    assert finding.confidence == 0.3
    assert any("dormant" in f.title.lower() for f in finding.findings)
    require_valid("agent_finding.schema.json", finding.to_schema_dict())


def test_signal_map_agent_active_when_signals_present():
    agent = SignalMapAgent()
    ctx = AgentContext(
        problem_context=_problem_ctx(),
        signals=[
            Signal(name="Vout", kind="voltage", expr="V(out)", source="auto"),
            Signal(name="Vin", kind="voltage", expr="V(in)", source="user", confidence=1.0),
        ],
    )
    inputs = agent.select_relevant(ctx)
    finding = agent.deterministic_finding(inputs)
    assert finding.confidence == 0.45
    # Two signals without target_band -> two band hints.
    band_recs = [
        r for r in finding.recommendations
        if r.proposed_change.get("type") == "signal_add_target_band"
    ]
    assert len(band_recs) == 2
    require_valid("agent_finding.schema.json", finding.to_schema_dict())


# ---- Composer .meas directives for signals ----


def test_composer_emits_per_signal_meas():
    plan = TestbenchPlan(
        title="signals meas test",
        parasitics=[],
        signals=[
            Signal(name="Vout", kind="voltage", expr="V(out)", source="auto"),
            Signal(name="Iload", kind="current", expr="I(Rload)", source="user"),
        ],
    )
    cir = compose_testbench_cir(plan)
    assert ".meas TRAN Vout_peak MAX V(out)" in cir
    assert ".meas TRAN Vout_rms RMS V(out)" in cir
    assert ".meas TRAN Vout_avg AVG V(out)" in cir
    assert ".meas TRAN Iload_peak MAX I(Rload)" in cir
    assert "Tracked user signals" in cir


def test_composer_skips_signal_meas_when_signals_empty():
    plan = TestbenchPlan(title="no signals", parasitics=[], signals=[])
    cir = compose_testbench_cir(plan)
    assert "Tracked user signals" not in cir
