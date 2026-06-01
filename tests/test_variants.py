"""Tests for the corner-sweep variant engine."""

from __future__ import annotations

import pytest

from emc_assistant.parasitics.calculators import (
    lc_resonance,
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)
from emc_assistant.testbench.variants import enumerate_corner_variants


def _parasitics():
    return [
        trace_resistance(length_mm=10.0, width_mm=0.5),
        trace_inductance_no_plane(length_mm=10.0, width_mm=0.5),
        trace_capacitance_from_z0_delay(length_mm=10.0, z0_ohm=50.0, delay_ps_per_mm=6.7),
        via_inductance(height_mm=1.6, drill_diameter_mm=0.3),
        lc_resonance(inductance_h=10e-9, capacitance_f=10e-12),  # type=frequency, sweep skip
    ]


def test_at_corner_shifts_typ_value():
    r = trace_resistance(length_mm=10.0, width_mm=0.5)
    rmin = r.at_corner("min")
    rmax = r.at_corner("max")
    assert rmin.value == pytest.approx(r.min_value)
    assert rmax.value == pytest.approx(r.max_value)
    # corner="typ" returns the same object.
    assert r.at_corner("typ") is r


def test_at_corner_rejects_invalid():
    r = trace_resistance(length_mm=10.0, width_mm=0.5)
    with pytest.raises(ValueError):
        r.at_corner("foo")


def test_enumerate_variants_cardinality():
    parasitics = _parasitics()
    # 4 R/L/C parasitics swept; 1 frequency-type entry skipped.
    variants = enumerate_corner_variants(parasitics)
    # baseline + 4*2 = 9
    assert len(variants) == 9
    labels = [v.label for v in variants]
    assert labels[0] == "baseline"
    # Each non-baseline variant is "<id>-min" or "<id>-max".
    suffixes = {label.rsplit("-", 1)[-1] for label in labels[1:]}
    assert suffixes == {"min", "max"}


def test_variant_overrides_only_modify_target():
    parasitics = _parasitics()
    variants = enumerate_corner_variants(parasitics)
    for v in variants[1:]:
        non_typ = [p for p, c in v.overrides.items() if c != "typ"]
        assert len(non_typ) == 1
