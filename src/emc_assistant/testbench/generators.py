"""Simple SPICE generators: LISN and cable.

These are first-order engineering approximations used as a pre-compliance
testbench — they do not replace measurement nor a certified EMI receiver
model. The LISN topology follows the standard 50 µH / 50 Ω network
described in publicly available educational material; no normative
CISPR/IEC text is reproduced.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class LisnSpec:
    """Parameters of a simple single-wire LISN for conducted EMI."""

    name: str = "LISN50UH"
    inductance_h: float = 50e-6
    coupling_capacitance_f: float = 0.1e-6
    series_block_capacitance_f: float = 1.0e-6
    measurement_resistance_ohm: float = 50.0
    bleed_resistance_ohm: float = 1.0e3

    def assumptions(self) -> list[str]:
        return [
            "Educational LISN topology (50 uH / 0.1 uF / 50 Ohm)",
            "No real inductor/capacitor parasitics modelled in MVP",
            "Not a certified CISPR/IEC LISN model",
            "EMI-receiver detector (peak/avg/QP) not modelled",
        ]


@dataclass
class CableSpec:
    """Simple segmented power-cable model (LC ladder)."""

    name: str = "CABLE_PWR"
    length_m: float = 1.0
    inductance_per_m_h: float = 800e-9
    capacitance_per_m_f: float = 50e-12
    resistance_per_m_ohm: float = 50e-3
    segments: int = 5

    def assumptions(self) -> list[str]:
        return [
            f"Length {self.length_m} m, {self.segments} LC segments",
            f"L'~{self.inductance_per_m_h*1e9:.0f} nH/m, "
            f"C'~{self.capacitance_per_m_f*1e12:.0f} pF/m, "
            f"R'~{self.resistance_per_m_ohm*1e3:.0f} mOhm/m",
            "Unshielded cable, no CM model (to be added later)",
            "DM ladder only; real cables vary significantly",
        ]


def generate_lisn_subckt(spec: LisnSpec | None = None) -> str:
    """Return the body of a ``.SUBCKT`` LISN.

    Ports: HV_IN (from supply), DUT (to DUT), MEAS (50 Ω probe out), 0 (GND).
    """
    spec = spec or LisnSpec()
    L = spec.inductance_h
    Cc = spec.coupling_capacitance_f
    Cs = spec.series_block_capacitance_f
    Rm = spec.measurement_resistance_ohm
    Rb = spec.bleed_resistance_ohm

    return (
        f"* --- LISN subcircuit ({spec.name}) ---\n"
        f"* Educational 50 uH / 0.1 uF / 50 Ohm topology. Not a normative model.\n"
        f"* Ports: HV_IN DUT MEAS 0\n"
        f".SUBCKT {spec.name} HV_IN DUT MEAS 0\n"
        f"L_lisn  HV_IN DUT   {L:.6g}\n"
        f"C_couple DUT n_meas {Cc:.6g}\n"
        f"C_block  HV_IN 0     {Cs:.6g}\n"
        f"R_meas   n_meas MEAS {Rm:.6g}\n"
        f"R_bleed  MEAS 0      {Rb:.6g}\n"
        f".ENDS {spec.name}\n"
    )


def generate_cable_fragment(spec: CableSpec | None = None) -> str:
    """Return a SPICE fragment with a cable ``.SUBCKT`` (LC ladder)."""
    spec = spec or CableSpec()
    n = max(1, int(spec.segments))
    L_seg = spec.inductance_per_m_h * spec.length_m / n
    C_seg = spec.capacitance_per_m_f * spec.length_m / n
    R_seg = spec.resistance_per_m_ohm * spec.length_m / n

    lines: list[str] = []
    lines.append(f"* --- Cable subcircuit ({spec.name}) ---")
    lines.append(
        f"* Length {spec.length_m} m, LC ladder segments = {n} "
        f"(L_seg={L_seg:.3g} H, C_seg={C_seg:.3g} F, R_seg={R_seg:.3g} Ohm)"
    )
    lines.append(f".SUBCKT {spec.name} IN OUT 0")
    prev = "IN"
    for i in range(1, n + 1):
        node_mid = f"n_c{i}"
        node_next = f"n_c{i}o" if i < n else "OUT"
        lines.append(f"R_seg{i} {prev} {node_mid} {R_seg:.6g}")
        lines.append(f"L_seg{i} {node_mid} {node_next} {L_seg:.6g}")
        lines.append(f"C_seg{i} {node_next} 0 {C_seg:.6g}")
        prev = node_next
    lines.append(f".ENDS {spec.name}")
    return "\n".join(lines) + "\n"
