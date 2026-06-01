"""Tests for parasitic SPICE fragment generators."""

from __future__ import annotations

import pytest

from emc_assistant.parasitics.calculators import (
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)
from emc_assistant.testbench.fragments import (
    capacitor_with_esr_esl_fragment,
    trace_rlc_fragment,
    via_fragment,
)


def test_trace_rlc_fragment_structure():
    r = trace_resistance(length_mm=10.0, width_mm=0.5)
    l = trace_inductance_no_plane(length_mm=10.0, width_mm=0.5)
    c = trace_capacitance_from_z0_delay(length_mm=10.0, z0_ohm=50.0, delay_ps_per_mm=6.7)
    out = trace_rlc_fragment(r_est=r, l_est=l, c_est=c, name="TRACE_X")
    assert ".SUBCKT TRACE_X IN OUT 0" in out
    assert ".ENDS TRACE_X" in out
    for sym in ("trace_x_r", "trace_x_l", "trace_x_c"):
        for kind in ("min", "typ", "max"):
            assert f"{sym}_{kind}" in out
    assert "{trace_x_r_typ}" in out
    assert "{trace_x_l_typ}" in out
    assert "{trace_x_c_typ}" in out


def test_trace_rlc_fragment_rejects_wrong_types():
    r = trace_resistance(length_mm=10.0, width_mm=0.5)
    l = trace_inductance_no_plane(length_mm=10.0, width_mm=0.5)
    with pytest.raises(ValueError):
        trace_rlc_fragment(r_est=r, l_est=l, c_est=l)


def test_via_fragment_basic():
    est = via_inductance(height_mm=1.6, drill_diameter_mm=0.3)
    out = via_fragment(est)
    assert ".SUBCKT VIA_L IN OUT" in out
    assert ".ENDS VIA_L" in out
    assert "via_l_typ" in out


def test_capacitor_fragment_values():
    out = capacitor_with_esr_esl_fragment(
        capacitance_f=10e-6, esr_ohm=20e-3, esl_h=2e-9, name="C_IN"
    )
    assert ".SUBCKT C_IN IN OUT" in out
    assert "1e-05" in out or "1.00000e-05" in out
    assert "0.02" in out
    assert "2e-09" in out


def test_capacitor_fragment_rejects_invalid():
    with pytest.raises(ValueError):
        capacitor_with_esr_esl_fragment(capacitance_f=0.0, esr_ohm=0.0, esl_h=0.0)
