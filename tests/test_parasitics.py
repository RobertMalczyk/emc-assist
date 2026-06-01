"""Tests for parasitic calculators."""

from __future__ import annotations

import math

import pytest

from emc_assistant.parasitics.calculators import (
    lc_resonance,
    polygon_plane_capacitance,
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)
from emc_assistant.parasitics.model import ValueBand


def test_value_band_rejects_out_of_order():
    with pytest.raises(ValueError):
        ValueBand(min=2.0, typ=1.0, max=3.0)


def test_trace_resistance_order_of_magnitude():
    r = trace_resistance(length_mm=20.0, width_mm=1.0, copper_oz=1.0)
    # 20 mm * 0.49 mOhm/sq / 1 mm = ~9.8 mOhm
    assert 5e-3 < r.value < 20e-3
    assert r.min_value < r.value < r.max_value
    assert r.unit == "ohm"
    assert "R001" in r.source_ids


def test_trace_resistance_rejects_zero_geometry():
    with pytest.raises(ValueError):
        trace_resistance(length_mm=0.0, width_mm=1.0)
    with pytest.raises(ValueError):
        trace_resistance(length_mm=1.0, width_mm=0.0)


def test_trace_resistance_temperature_dependency():
    r_cold = trace_resistance(length_mm=10.0, width_mm=1.0, temperature_c=0.0)
    r_hot = trace_resistance(length_mm=10.0, width_mm=1.0, temperature_c=85.0)
    assert r_hot.value > r_cold.value


def test_trace_inductance_no_plane_in_reasonable_range():
    l = trace_inductance_no_plane(length_mm=20.0, width_mm=0.5)
    # Rough upper bound ~0.6-1.2 nH/mm, so 20 mm -> 12-24 nH; wide tolerance.
    assert 5e-9 < l.value < 60e-9
    assert l.unit == "H"


def test_trace_capacitance_from_z0_delay():
    # 50 Ohm, td=6.7 ps/mm, L=100 mm: C ≈ 6.7e-9 * 0.1 / 50 = 13.4 pF
    c = trace_capacitance_from_z0_delay(length_mm=100.0, z0_ohm=50.0, delay_ps_per_mm=6.7)
    assert math.isclose(c.value, 6.7e-9 * 0.1 / 50.0, rel_tol=1e-6)
    assert c.unit == "F"


def test_polygon_plane_capacitance_known_geometry():
    # A = 1e-4 m^2 (100 mm^2), d = 0.2 mm, eps_r = 4.3
    # C = 8.854e-12 * 4.3 * 1e-4 / 2e-4 = ~1.903e-11 F
    c = polygon_plane_capacitance(
        area_mm2=100.0, dielectric_height_mm=0.2, relative_permittivity=4.3
    )
    assert math.isclose(c.value, 8.8541878128e-12 * 4.3 * 1e-4 / 2e-4, rel_tol=1e-6)


def test_via_inductance_returns_positive():
    l = via_inductance(height_mm=1.6, drill_diameter_mm=0.3)
    assert l.value > 0.0
    assert l.unit == "H"
    # 1.6 mm via through 0.3 mm drill ≈ 1 nH typical.
    assert 0.2e-9 < l.value < 3e-9


def test_lc_resonance_formula():
    f = lc_resonance(inductance_h=10e-9, capacitance_f=10e-12)
    expected = 1.0 / (2.0 * math.pi * math.sqrt(10e-9 * 10e-12))
    assert math.isclose(f.value, expected, rel_tol=1e-9)
    assert f.unit == "Hz"
    assert f.parasitic_type == "frequency"


def test_all_estimates_provide_assumptions_and_band():
    estimates = [
        trace_resistance(length_mm=10.0, width_mm=0.5),
        trace_inductance_no_plane(length_mm=10.0, width_mm=0.5),
        trace_capacitance_from_z0_delay(length_mm=10.0, z0_ohm=50.0, delay_ps_per_mm=6.7),
        polygon_plane_capacitance(area_mm2=50.0, dielectric_height_mm=0.2),
        via_inductance(height_mm=1.6, drill_diameter_mm=0.3),
        lc_resonance(inductance_h=10e-9, capacitance_f=10e-12),
    ]
    for est in estimates:
        assert est.assumptions, f"{est.id} should carry assumptions"
        assert est.min_value <= est.value <= est.max_value
        d = est.to_schema_dict()
        assert d["unit"]
        assert d["confidence"] in {"low", "medium", "high"}
