"""Tests for the LISN and cable generators."""

from __future__ import annotations

from emc_assistant.testbench.generators import (
    CableSpec,
    LisnSpec,
    generate_cable_fragment,
    generate_lisn_subckt,
)


def test_lisn_contains_expected_components():
    out = generate_lisn_subckt(LisnSpec())
    assert ".SUBCKT LISN50UH HV_IN DUT MEAS 0" in out
    assert ".ENDS LISN50UH" in out
    assert "L_lisn" in out
    assert "C_couple" in out
    assert "R_meas" in out
    # Comment noting that the topology is not normative.
    assert "Educational" in out


def test_lisn_inductance_value_present():
    out = generate_lisn_subckt(LisnSpec(inductance_h=50e-6))
    assert "5e-05" in out or "5.00000e-05" in out or "5e-5" in out


def test_cable_fragment_segments():
    spec = CableSpec(length_m=2.0, segments=4)
    out = generate_cable_fragment(spec)
    assert ".SUBCKT CABLE_PWR IN OUT 0" in out
    assert ".ENDS CABLE_PWR" in out
    # 4 segments → R_seg1..R_seg4 etc.
    for i in range(1, 5):
        assert f"R_seg{i}" in out
        assert f"L_seg{i}" in out
        assert f"C_seg{i}" in out
    assert "R_seg5" not in out


def test_cable_fragment_default_assumptions_documented():
    spec = CableSpec()
    assumptions = spec.assumptions()
    assert any("nH/m" in a for a in assumptions)
    assert any("no cm model" in a.lower() for a in assumptions)
