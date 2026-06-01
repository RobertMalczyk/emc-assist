"""Tests for ``emc_assistant.units``.

Trivial conversions, but ``oz_to_meters`` feeds every PCB trace/plane
parasitic estimate in ``parasitics/calculators.py`` — a wrong constant
would corrupt those silently, so it gets a direct test rather than only
transitive coverage.
"""

from __future__ import annotations

import math

import pytest

from emc_assistant import units


def test_oz_to_meters_nominal_1oz():
    # 1 oz/ft² copper ≈ 34.79 µm (IPC-2152 nominal).
    assert units.oz_to_meters(1.0) == pytest.approx(34.79e-6)


@pytest.mark.parametrize("oz, expected_um", [(0.5, 17.395), (2.0, 69.58)])
def test_oz_to_meters_scales_linearly(oz, expected_um):
    assert units.oz_to_meters(oz) == pytest.approx(expected_um * 1e-6)


def test_oz_to_meters_zero():
    assert units.oz_to_meters(0.0) == 0.0


def test_mm_m_round_trip():
    assert units.mm_to_m(12.5) == pytest.approx(0.0125)
    assert units.m_to_mm(0.0125) == pytest.approx(12.5)
    assert units.m_to_mm(units.mm_to_m(3.3)) == pytest.approx(3.3)


def test_speed_of_light_consistency():
    """c₀ = 1 / √(µ₀·ε₀) — the three EM constants must agree."""
    derived = 1.0 / math.sqrt(units.MU0_H_PER_M * units.EPS0_F_PER_M)
    assert derived == pytest.approx(units.C0_M_PER_S, rel=1e-6)


def test_constants_have_expected_magnitudes():
    assert units.OZ_TO_UM == pytest.approx(34.79)
    assert units.RHO_CU_OHM_M == pytest.approx(1.724e-8)
    assert units.MU0_H_PER_M == pytest.approx(4e-7 * math.pi)
