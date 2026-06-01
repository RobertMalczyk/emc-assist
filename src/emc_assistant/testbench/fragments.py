"""Small SPICE fragments for individual parasitics.

Each fragment takes a ``ParasiticEstimate`` and emits a ``.SUBCKT`` with
``{value}`` set to the typical value plus ``.param`` ``min_/typ_/max_``
entries that variant sweeps can override. Components are intentionally
simple — no frequency dependence in MVP.
"""

from __future__ import annotations

import math

from emc_assistant.agents.injection import L_DAMP_CORNER_HZ
from emc_assistant.parasitics.model import ParasiticEstimate


def _safe_name(text: str) -> str:
    return "".join(ch if ch.isalnum() else "_" for ch in text)


def _params_block(prefix: str, est: ParasiticEstimate) -> str:
    return (
        f".param {prefix}_min={est.min_value:.6g}\n"
        f".param {prefix}_typ={est.value:.6g}\n"
        f".param {prefix}_max={est.max_value:.6g}\n"
    )


def trace_rlc_fragment(
    *,
    r_est: ParasiticEstimate,
    l_est: ParasiticEstimate,
    c_est: ParasiticEstimate,
    name: str = "TRACE_RLC",
) -> str:
    """Subcircuit ``IN OUT 0`` modelling a trace with R+L+C to return.

    Topology: R in series, L in series, C shunt to GND at the output end.
    The three estimates must describe the same physical trace.
    """
    if r_est.parasitic_type != "R" or l_est.parasitic_type != "L" or c_est.parasitic_type != "C":
        raise ValueError("trace_rlc_fragment requires exactly R, L, C estimates")
    prefix = _safe_name(name).lower()
    return (
        f"* --- Trace parasitic fragment ({name}) ---\n"
        f"* Source rules: R={','.join(r_est.source_ids) or 'engineering_estimate'} "
        f"L={','.join(l_est.source_ids) or 'engineering_estimate'} "
        f"C={','.join(c_est.source_ids) or 'engineering_estimate'}\n"
        f"{_params_block(prefix + '_r', r_est)}"
        f"{_params_block(prefix + '_l', l_est)}"
        f"{_params_block(prefix + '_c', c_est)}"
        f".SUBCKT {name} IN OUT 0\n"
        f"R_par IN n_r {{{prefix}_r_typ}}\n"
        f"L_par n_r OUT {{{prefix}_l_typ}}\n"
        # M2.10.8: parallel Q-damping resistor — makes L_par resistive
        # above L_DAMP_CORNER_HZ so the tiny L/C tank cannot ring at GHz.
        f"Rd_par n_r OUT {{{2.0 * math.pi * L_DAMP_CORNER_HZ:.6g}*{prefix}_l_typ}}\n"
        f"C_par OUT 0 {{{prefix}_c_typ}}\n"
        f".ENDS {name}\n"
    )


def via_fragment(est: ParasiticEstimate, *, name: str = "VIA_L") -> str:
    """Subcircuit ``IN OUT`` adding a series via inductance."""
    if est.parasitic_type != "L" or est.structure != "via":
        raise ValueError("via_fragment requires an L/via estimate")
    prefix = _safe_name(name).lower()
    return (
        f"* --- Via fragment ({name}) ---\n"
        f"* Source rules: {','.join(est.source_ids) or 'engineering_estimate'}\n"
        f"{_params_block(prefix, est)}"
        f".SUBCKT {name} IN OUT\n"
        f"L_via IN OUT {{{prefix}_typ}}\n"
        f".ENDS {name}\n"
    )


def capacitor_with_esr_esl_fragment(
    *,
    capacitance_f: float,
    esr_ohm: float,
    esl_h: float,
    name: str = "CAP_ESR_ESL",
) -> str:
    """Subcircuit for a capacitor model with ESR and ESL (in series).

    Topology: ESL -> ESR -> C between ports ``IN`` and ``OUT``.
    Values come from the user or the supplier; the tool does not guess.
    """
    if capacitance_f <= 0 or esr_ohm < 0 or esl_h < 0:
        raise ValueError("capacitance_f>0, esr_ohm>=0, esl_h>=0")
    return (
        f"* --- Capacitor with ESR/ESL ({name}) ---\n"
        f"* User-supplied values; MVP does not model SRF(T).\n"
        f".SUBCKT {name} IN OUT\n"
        f"L_esl IN n1 {esl_h:.6g}\n"
        f"R_esr n1 n2 {esr_ohm:.6g}\n"
        f"C_main n2 OUT {capacitance_f:.6g}\n"
        f".ENDS {name}\n"
    )
