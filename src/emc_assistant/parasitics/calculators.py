"""First-order PCB parasitic calculators.

All calculators return a ``ParasiticEstimate`` with a min/typ/max band.
Formulas are first-order approximations only; canonical sources live in
``knowledge/seed/baza_pasozyty_pcb_rules.jsonl`` and are referenced by
``source_ids``.

Known gaps vs. the PCB-parasitics source set (S032-S036) and the
proposed staging rules in
``knowledge/seed/staging_pcb_parasitic_trace_rules.jsonl``. These are
documented, not implemented — adding them is a separate, scoped task
and must not drift into field solving:

* TODO: trace inductance *with* a close return plane. Today
  ``trace_inductance_no_plane`` is the isolated-conductor case;
  trace-over-plane is only reachable indirectly via Z0 and delay
  (see the note on that function). A direct loop-inductance helper
  for the trace-over-plane case is missing. (rule PCB_TRACE_L_001)
* TODO: loop inductance from enclosed loop area — no calculator
  exists; ``lc_resonance`` consumes an L but does not derive it from
  geometry. (rule PCB_LOOP_001)
* TODO: via *array* inductance. ``via_inductance`` covers a single
  via and only notes that a pair roughly halves L; an N-via parallel
  helper is missing. (rule PCB_VIA_L_001)
* TODO: transmission-line trace *inductance* from Z0 and delay
  (L' = Z0 * td). The capacitance dual exists
  (``trace_capacitance_from_z0_delay``); the L' form does not.
* polygon-to-plane capacitance is already covered by
  ``polygon_plane_capacitance`` — no gap. (rule PCB_POLY_C_001)
"""

from __future__ import annotations

import math

from emc_assistant.parasitics.model import ParasiticEstimate, ValueBand
from emc_assistant.units import (
    EPS0_F_PER_M,
    RHO_CU_OHM_M,
    oz_to_meters,
)


def _band(typ: float, *, tol_low: float = 0.7, tol_high: float = 1.4) -> ValueBand:
    """Build a min/typ/max band from tolerance multipliers."""
    return ValueBand(min=typ * tol_low, typ=typ, max=typ * tol_high)


def trace_resistance(
    *,
    length_mm: float,
    width_mm: float,
    copper_oz: float = 1.0,
    temperature_c: float = 25.0,
) -> ParasiticEstimate:
    """DC resistance of a copper trace.

    R = ρ · L / (W · t) with linear temperature correction
    α_Cu ≈ 0.00393/°C relative to 20 °C. First-order only —
    AC resistance, skin effect and via drops are ignored.
    """
    if length_mm <= 0 or width_mm <= 0:
        raise ValueError("length_mm and width_mm must be positive")
    if copper_oz <= 0:
        raise ValueError("copper_oz must be positive")

    thickness_m = oz_to_meters(copper_oz)
    length_m = length_mm * 1e-3
    width_m = width_mm * 1e-3

    alpha = 0.00393
    rho = RHO_CU_OHM_M * (1.0 + alpha * (temperature_c - 20.0))
    r_typ = rho * length_m / (width_m * thickness_m)

    return ParasiticEstimate(
        id=f"par-trace-R-{length_mm:g}x{width_mm:g}-{copper_oz:g}oz",
        structure="trace",
        parasitic_type="R",
        band=_band(r_typ, tol_low=0.8, tol_high=1.25),
        unit="ohm",
        confidence="high",
        assumptions=[
            "Solid smooth copper, rho=1.724e-8 Ohm·m at 20 °C",
            "No skin effect (DC/LF)",
            f"Temperature {temperature_c} °C, alpha≈0.00393/°C",
            "Via and solder-joint resistance ignored",
        ],
        formula="R = rho * L / (W * t); rho = rho0 * (1 + alpha*(T-20))",
        inputs={
            "length_mm": length_mm,
            "width_mm": width_mm,
            "copper_oz": copper_oz,
            "temperature_c": temperature_c,
        },
        source_ids=["R001"],
        ltspice_representation="Rser in series with the trace segment",
        notes="±20% band captures typical copper-thickness manufacturing tolerance.",
    )


def trace_inductance_no_plane(
    *,
    length_mm: float,
    width_mm: float,
    copper_oz: float = 1.0,
) -> ParasiticEstimate:
    """Self-inductance of a trace with no close return plane.

    L[nH] = 0.2 · l · (ln(2l/(w+t)) + 0.5 + 0.2235·(w+t)/l).
    Formula for an isolated flat conductor. For a trace over a plane
    prefer ``trace_capacitance_from_z0_delay`` together with Z0·td.
    """
    if length_mm <= 0 or width_mm <= 0:
        raise ValueError("length_mm and width_mm must be positive")
    l = length_mm
    w = width_mm
    t = oz_to_meters(copper_oz) * 1e3  # mm
    arg = 2.0 * l / (w + t)
    if arg <= 0:
        raise ValueError("Invalid geometry for the inductance formula")
    l_nh = 0.2 * l * (math.log(arg) + 0.5 + 0.2235 * (w + t) / l)
    l_typ = l_nh * 1e-9  # H

    return ParasiticEstimate(
        id=f"par-trace-L-iso-{length_mm:g}x{width_mm:g}",
        structure="trace",
        parasitic_type="L",
        band=ValueBand(min=l_typ * 0.5, typ=l_typ, max=l_typ * 1.5),
        unit="H",
        confidence="medium",
        assumptions=[
            "No close return plane near the trace",
            "Isolated flat-strip conductor formula",
            "Neighbour-coupling and capacitive loading ignored",
        ],
        formula="L[nH] = 0.2 * l_mm * (ln(2l/(w+t)) + 0.5 + 0.2235*(w+t)/l)",
        inputs={
            "length_mm": length_mm,
            "width_mm": width_mm,
            "copper_oz": copper_oz,
        },
        source_ids=["R002"],
        ltspice_representation="Lser in series with the trace segment",
        notes=(
            "Conservative upper bound; actual loop inductance depends on the "
            "return-path geometry. For trace-over-plane use L'=Z0·td."
        ),
    )


def trace_capacitance_from_z0_delay(
    *,
    length_mm: float,
    z0_ohm: float,
    delay_ps_per_mm: float,
) -> ParasiticEstimate:
    """Distributed trace capacitance from Z0 and propagation delay.

    C' = td / Z0, where td is propagation delay per unit length.
    Use for traces over a continuous return plane.
    """
    if length_mm <= 0 or z0_ohm <= 0 or delay_ps_per_mm <= 0:
        raise ValueError("All inputs must be positive")

    td_s_per_m = delay_ps_per_mm * 1e-9  # ps/mm = 1e-12 s / 1e-3 m = 1e-9 s/m
    c_per_m = td_s_per_m / z0_ohm
    c_typ = c_per_m * (length_mm * 1e-3)

    return ParasiticEstimate(
        id=f"par-trace-C-Z0-{length_mm:g}-{z0_ohm:g}",
        structure="trace",
        parasitic_type="C",
        band=ValueBand(min=c_typ * 0.7, typ=c_typ, max=c_typ * 1.3),
        unit="F",
        confidence="high",
        assumptions=[
            "Trace runs over a continuous return plane",
            "Propagation delay derived from stack-up / Er",
            "Discontinuities and termination effects ignored",
        ],
        formula="C = (td_ps_per_mm * 1e-9 / Z0) * L[m]",
        inputs={
            "length_mm": length_mm,
            "z0_ohm": z0_ohm,
            "delay_ps_per_mm": delay_ps_per_mm,
        },
        source_ids=["R004", "R005"],
        ltspice_representation="Shunt C to the return plane (or TLINE)",
    )


def polygon_plane_capacitance(
    *,
    area_mm2: float,
    dielectric_height_mm: float,
    relative_permittivity: float = 4.3,
) -> ParasiticEstimate:
    """Polygon-to-plane parallel-plate capacitance.

    C = eps0 * eps_r * A / d. First-order — fringe effects ignored.
    eps_r=4.3 is typical FR-4.
    """
    if area_mm2 <= 0 or dielectric_height_mm <= 0 or relative_permittivity <= 0:
        raise ValueError("All inputs must be positive")

    area_m2 = area_mm2 * 1e-6
    d_m = dielectric_height_mm * 1e-3
    c_typ = EPS0_F_PER_M * relative_permittivity * area_m2 / d_m

    return ParasiticEstimate(
        id=f"par-poly-C-{area_mm2:g}mm2-h{dielectric_height_mm:g}",
        structure="plane_pair",
        parasitic_type="C",
        band=ValueBand(min=c_typ * 0.8, typ=c_typ, max=c_typ * 1.25),
        unit="F",
        confidence="medium",
        assumptions=[
            f"eps_r={relative_permittivity} (typical FR-4)",
            "Fringe effects and frequency dependence of eps_r ignored",
            "Planes parallel and uniform",
        ],
        formula="C = eps0 * eps_r * A / d",
        inputs={
            "area_mm2": area_mm2,
            "dielectric_height_mm": dielectric_height_mm,
            "relative_permittivity": relative_permittivity,
        },
        source_ids=["R012"],
        ltspice_representation="C between planes (shunt C)",
    )


def via_inductance(
    *,
    height_mm: float,
    drill_diameter_mm: float,
) -> ParasiticEstimate:
    """Single-via inductance (Howard W. Johnson approximation).

    L[nH] ≈ 5.08 · h_inch · (ln(4h/d) + 1) with h, d in inches.
    Classical approximation; treated as a ±30% engineering estimate.
    Antipads and pads are ignored.
    """
    if height_mm <= 0 or drill_diameter_mm <= 0:
        raise ValueError("height_mm and drill_diameter_mm must be positive")
    h_in = height_mm / 25.4
    d_in = drill_diameter_mm / 25.4
    l_nh = 5.08 * h_in * (math.log(4.0 * h_in / d_in) + 1.0)
    if l_nh <= 0:
        # Log formula can return a negative value when h<<d.
        l_nh = 0.05 * h_in
    l_typ = l_nh * 1e-9

    return ParasiticEstimate(
        id=f"par-via-L-h{height_mm:g}-d{drill_diameter_mm:g}",
        structure="via",
        parasitic_type="L",
        band=ValueBand(min=l_typ * 0.7, typ=l_typ, max=l_typ * 1.4),
        unit="H",
        confidence="medium",
        assumptions=[
            "Howard Johnson classical approximation",
            "Single via — no parallel pairs",
            "Pad and discontinuity inductance ignored",
        ],
        formula="L[nH] = 5.08 * h_in * (ln(4h/d) + 1)",
        inputs={
            "height_mm": height_mm,
            "drill_diameter_mm": drill_diameter_mm,
        },
        source_ids=["R010"],
        ltspice_representation="Lser in series with the via",
        notes="A pair of parallel vias roughly halves L.",
    )


def lc_resonance(
    *,
    inductance_h: float,
    capacitance_f: float,
) -> ParasiticEstimate:
    """Series/parallel LC resonance frequency.

    f = 1 / (2π√(LC)). Returned in Hz and tagged as a diagnostic
    ``frequency`` parasitic; it is *not* placed in the netlist.
    """
    if inductance_h <= 0 or capacitance_f <= 0:
        raise ValueError("inductance_h and capacitance_f must be positive")
    f_typ = 1.0 / (2.0 * math.pi * math.sqrt(inductance_h * capacitance_f))

    return ParasiticEstimate(
        id=f"par-LC-fres-{inductance_h:g}-{capacitance_f:g}",
        structure="loop",
        parasitic_type="frequency",
        band=_band(f_typ, tol_low=0.8, tol_high=1.25),
        unit="Hz",
        confidence="high",
        assumptions=[
            "Lossless (R=0); ESR/ESL absorbed into L and C",
            "First dominant resonance only",
        ],
        formula="f = 1 / (2*pi*sqrt(L*C))",
        inputs={"inductance_h": inductance_h, "capacitance_f": capacitance_f},
        source_ids=["R030"],
        ltspice_representation="Diagnostic frequency; not emitted in the netlist",
        notes=(
            "Sanity check: verify that switching/filter frequencies do not "
            "overlap the parasitic resonance."
        ),
    )
