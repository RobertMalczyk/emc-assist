"""Tests for the netlist topology analyser."""

from __future__ import annotations

from pathlib import Path

from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import (
    analyse_fragment,
    build_topology_report,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BUCK_DEMO = REPO_ROOT / "examples" / "case_001_buck_conducted_emi" / "input" / "buck_demo.cir"


def test_topology_buck_demo_identifies_input_rail():
    report = analyse_fragment(BUCK_DEMO)
    # `in` is the positive terminal of Vin, so it must be the first power-supply candidate.
    assert report.power_supply_candidates[0] == "in"
    # `0` is the only ground-token net used in the buck demo fragment.
    assert "0" in report.return_candidates
    # Capacitor terminals captured.
    cap_pairs = {(p, n) for p, n in report.capacitor_terminals}
    assert ("n_bulk", "0") in cap_pairs
    assert ("n_in", "0") in cap_pairs
    assert ("out", "0") in cap_pairs


def test_topology_serialises_to_schema_dict():
    report = analyse_fragment(BUCK_DEMO)
    data = report.to_schema_dict()
    assert "power_supply_candidates" in data
    assert "return_candidates" in data
    assert "nets" in data
    assert any(net["name"] == "in" for net in data["nets"])
    # Every net carries the reference designators wired to it.
    in_net = next(net for net in data["nets"] if net["name"] == "in")
    assert "components" in in_net
    assert any(rd.upper().startswith("V") for rd in in_net["components"])


def test_topology_components_match_element_count():
    report = build_topology_report(parse_cir(
        "* synthetic\n"
        "R1 a b 1k\n"
        "R2 b c 2k\n"
        "C1 b 0 10n\n"
    ))
    by_name = {nu.name: nu for nu in report.nets}
    # Net `b` is wired to R1, R2 and C1 — three distinct refdes, no dupes.
    assert by_name["b"].components == ["R1", "R2", "C1"]
    assert by_name["b"].element_count == len(by_name["b"].components)
    assert by_name["a"].components == ["R1"]


def test_topology_synthetic_fragment_no_supply_no_caps():
    src = (
        "* synthetic\n"
        "R1 a b 1k\n"
        "R2 b c 2k\n"
    )
    report = build_topology_report(parse_cir(src))
    # No V source, no ground tokens, no caps.
    assert report.power_supply_candidates  # the R-driven nets fall back as candidates
    assert report.return_candidates == []
    assert report.capacitor_terminals == []
    assert report.element_count_by_kind == {"R": 2}


def test_topology_classifies_v_source_positive_net():
    src = (
        "* synthetic\n"
        "V1 vin 0 DC 12\n"
        "R1 vin out 100\n"
    )
    report = build_topology_report(parse_cir(src))
    # vin is V's positive terminal, must come first
    assert report.power_supply_candidates[0] == "vin"
    assert "0" in report.return_candidates
