"""Physical constants and unit-conversion helpers."""

from __future__ import annotations

import math

C0_M_PER_S: float = 2.99792458e8
"""Speed of light in vacuum [m/s]."""

EPS0_F_PER_M: float = 8.8541878128e-12
"""Vacuum permittivity [F/m]."""

MU0_H_PER_M: float = 4.0e-7 * math.pi
"""Vacuum permeability [H/m]."""

RHO_CU_OHM_M: float = 1.724e-8
"""Copper resistivity at 20 °C [Ω·m] (typical engineering value)."""

OZ_TO_UM: float = 34.79
"""Copper layer thickness: 1 oz/ft² ≈ 34.79 µm (IPC-2152 nominal)."""


def oz_to_meters(oz: float) -> float:
    """Convert copper layer weight (oz) to thickness in meters."""
    return oz * OZ_TO_UM * 1e-6


def mm_to_m(value_mm: float) -> float:
    return value_mm * 1e-3


def m_to_mm(value_m: float) -> float:
    return value_m * 1e3
