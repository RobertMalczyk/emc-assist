"""Generate an LTspice ``.asc`` schematic for the auto-modified testbench.

The composer-emitted ``.cir`` is canonical for simulation; this ``.asc``
is a **visualisation aid** so the engineer can open the assembled
testbench in LTspice and see the LISN / cable / parasitic injection
wired around the user fragment.

Layout (LTspice grid units, 16 px = 1 grid square):

::

    V_RAIL ── HV_IN_RAIL ── X_LISN_P ── HV_DUT_P ── X_CABLE ──n_dut_in_pre── X_TRACE_VIN ── in ── USER_FRAGMENT
                                            │                                                          │
                                          MEAS_P                                                    DUT_GND
                                                                                                       │
       0  ────────────────────────── X_LISN_N  ────────────────────────────────────────────────────────┘
                                          │
                                        MEAS_N

The user's ``.cir`` is included via a ``TEXT`` directive that LTspice
copies into the run-time netlist. The DUT placeholder block has pins
matching the nets the composer wires to (default: ``in``, ``DUT_GND``,
optionally ``sw_ctrl`` if the topology reports one).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from emc_assistant.agents.injection import ParasiticInjection
from emc_assistant.testbench.asy_templates import all_static_asy, dut_fragment_asy


# --- Layout constants (LTspice pixel units) ------------------------------


GRID = 16
SHEET_W = 1280
SHEET_H = 720


def _g(n: int) -> int:
    """Snap to LTspice grid (16 px)."""
    return n - (n % GRID)


# Symbol anchor positions on the sheet.
POS = {
    "V_RAIL": (3 * GRID, 14 * GRID),
    "X_LISN_P": (14 * GRID, 14 * GRID),
    "X_CABLE": (26 * GRID, 14 * GRID),
    "X_TRACE_VIN": (38 * GRID, 14 * GRID),
    "DUT_FRAGMENT": (54 * GRID, 14 * GRID),
    "X_LISN_N": (26 * GRID, 26 * GRID),
    "B_DM": (74 * GRID, 6 * GRID),
    "B_CM": (74 * GRID, 14 * GRID),
    "B_MEAS": (74 * GRID, 22 * GRID),
}
"""Top-left anchor of each symbol. Pins are offset from this anchor by
amounts defined in ``asy_templates``."""


# Pin coordinates relative to each symbol's anchor (must match the .asy).
PIN_OFFSETS: dict[str, dict[str, tuple[int, int]]] = {
    "LISN50UH": {"HV_IN": (0, 32), "DUT": (96, 32), "MEAS": (48, 0), "0": (48, 64)},
    "CABLE_PWR": {"IN": (0, 24), "OUT": (96, 24), "0": (48, 48)},
    "TRACE_RLC": {"IN": (0, 24), "OUT": (96, 24), "0": (48, 48)},
    "VIA_L": {"IN": (0, 16), "OUT": (64, 16)},
    "CAP_ESR_ESL": {"IN": (0, 16), "OUT": (80, 16)},
    "voltage": {"+": (0, 16), "-": (0, 80)},
    "bv": {"+": (0, 0), "-": (0, 80)},
}


@dataclass
class AscFile:
    asc_text: str
    asy_files: dict[str, str]
    """Map of ``filename → text`` for every ``.asy`` the .asc references."""


def _flag(net: str, x: int, y: int) -> str:
    return f"FLAG {x} {y} {net}\n"


def _wire(x1: int, y1: int, x2: int, y2: int) -> str:
    # LTspice wires are point-to-point; orthogonal routes need two segments.
    if x1 == x2 or y1 == y2:
        return f"WIRE {x1} {y1} {x2} {y2}\n"
    return f"WIRE {x1} {y1} {x2} {y1}\nWIRE {x2} {y1} {x2} {y2}\n"


def _symbol(symbol_type: str, x: int, y: int, *, instance: str, value: str = "") -> str:
    """Emit SYMBOL + SYMATTR lines. ``symbol_type`` is the .asy file stem."""
    parts = [f"SYMBOL {symbol_type} {x} {y} R0\nSYMATTR InstName {instance}\n"]
    if value:
        parts.append(f"SYMATTR Value {value}\n")
    return "".join(parts)


def _resolve_pin(symbol_type: str, anchor: tuple[int, int], pin: str) -> tuple[int, int]:
    offsets = PIN_OFFSETS.get(symbol_type, {})
    if pin not in offsets:
        raise KeyError(f"Unknown pin {pin!r} for symbol {symbol_type!r}")
    dx, dy = offsets[pin]
    return anchor[0] + dx, anchor[1] + dy


def _wire_between(
    sym_a: str, pos_a: tuple[int, int], pin_a: str,
    sym_b: str, pos_b: tuple[int, int], pin_b: str,
) -> str:
    p1 = _resolve_pin(sym_a, pos_a, pin_a)
    p2 = _resolve_pin(sym_b, pos_b, pin_b)
    return _wire(*p1, *p2)


def build_asc(
    *,
    title: str,
    v_rail_value: str,
    dut_pins: list[str],
    injection: ParasiticInjection | None,
    user_cir_include: str,
) -> AscFile:
    """Build the ``testbench.asc`` text + the ``.asy`` files it needs.

    Parameters mirror the relevant ``TestbenchPlan`` fields:

    - ``title`` – sheet title text.
    - ``v_rail_value`` – V_RAIL's value string (e.g. ``"DC 24"``).
    - ``dut_pins`` – list of pin names for the DUT placeholder, e.g.
      ``["in", "DUT_GND", "sw_ctrl"]``. Order matters; first pin is
      the supply input (left side).
    - ``injection`` – the M2.10 ParasiticInjection (must be TRACE_RLC
      on the supply path) or None.
    - ``user_cir_include`` – path to include via TEXT directive.
    """
    lines: list[str] = []
    lines.append("Version 4.1\n")
    lines.append(f"SHEET 1 {SHEET_W} {SHEET_H}\n")

    # --- Symbols ---
    lines.append(_symbol("voltage", *POS["V_RAIL"], instance="V_RAIL", value=v_rail_value))
    lines.append(_symbol("LISN50UH", *POS["X_LISN_P"], instance="X_LISN_P"))
    lines.append(_symbol("CABLE_PWR", *POS["X_CABLE"], instance="X_CABLE"))
    if injection is not None and injection.subckt_name == "TRACE_RLC":
        lines.append(_symbol("TRACE_RLC", *POS["X_TRACE_VIN"], instance=injection.instance_name))
    lines.append(_symbol("DUT_FRAGMENT", *POS["DUT_FRAGMENT"], instance="X_DUT"))
    lines.append(_symbol("LISN50UH", *POS["X_LISN_N"], instance="X_LISN_N"))
    lines.append(_symbol("bv", *POS["B_DM"], instance="B_DM", value="V=V(MEAS_P)-V(MEAS_N)"))
    lines.append(_symbol("bv", *POS["B_CM"], instance="B_CM", value="V=(V(MEAS_P)+V(MEAS_N))/2"))
    lines.append(_symbol("bv", *POS["B_MEAS"], instance="B_MEAS", value="V=V(MEAS_P)"))

    # --- Wires (HV+ chain) ---
    # V_RAIL+ → X_LISN_P.HV_IN
    lines.append(_wire_between("voltage", POS["V_RAIL"], "+",
                               "LISN50UH", POS["X_LISN_P"], "HV_IN"))
    # X_LISN_P.DUT → X_CABLE.IN
    lines.append(_wire_between("LISN50UH", POS["X_LISN_P"], "DUT",
                               "CABLE_PWR", POS["X_CABLE"], "IN"))
    # X_CABLE.OUT → X_TRACE_VIN.IN
    lines.append(_wire_between("CABLE_PWR", POS["X_CABLE"], "OUT",
                               "TRACE_RLC", POS["X_TRACE_VIN"], "IN"))
    # X_TRACE_VIN.OUT → DUT.<first-pin> (we just bring the wire close;
    # the DUT block's first pin is on its LEFT side at y_anchor + 16)
    p_inj = _resolve_pin("TRACE_RLC", POS["X_TRACE_VIN"], "OUT")
    p_dut = (POS["DUT_FRAGMENT"][0], POS["DUT_FRAGMENT"][1] + 32)  # left middle of DUT
    lines.append(_wire(*p_inj, *p_dut))

    # --- Return path (DUT bottom → X_LISN_N.DUT → 0) ---
    dut_bottom = (POS["DUT_FRAGMENT"][0] + 64, POS["DUT_FRAGMENT"][1] + 128)
    lisn_n_dut = _resolve_pin("LISN50UH", POS["X_LISN_N"], "DUT")
    lines.append(_wire(*dut_bottom, *lisn_n_dut))
    # X_LISN_N.HV_IN → 0 (back to V_RAIL-)
    lisn_n_hvin = _resolve_pin("LISN50UH", POS["X_LISN_N"], "HV_IN")
    v_rail_neg = _resolve_pin("voltage", POS["V_RAIL"], "-")
    lines.append(_wire(*lisn_n_hvin, *v_rail_neg))

    # --- TRACE_RLC.0 → DUT_GND (just a stub down to a labelled flag) ---
    p_inj_gnd = _resolve_pin("TRACE_RLC", POS["X_TRACE_VIN"], "0")
    lines.append(_wire(p_inj_gnd[0], p_inj_gnd[1],
                       p_inj_gnd[0], p_inj_gnd[1] + 4 * GRID))

    # --- MEAS_P / MEAS_N stubs feeding the B-sources ---
    p_meas_p = _resolve_pin("LISN50UH", POS["X_LISN_P"], "MEAS")
    p_meas_n = _resolve_pin("LISN50UH", POS["X_LISN_N"], "MEAS")
    # short stub UP from LISN_P MEAS so a FLAG sits on it
    meas_p_flag = (p_meas_p[0], p_meas_p[1] - 4 * GRID)
    lines.append(_wire(*p_meas_p, *meas_p_flag))
    # X_LISN_N's MEAS pin sits on the symbol's TOP edge — route it
    # LEFT then UP so the FLAG doesn't collide with the symbol's "0" pin
    # on the bottom edge.
    meas_n_via = (p_meas_n[0] - 4 * GRID, p_meas_n[1])
    meas_n_flag = (meas_n_via[0], meas_n_via[1] - 4 * GRID)
    lines.append(_wire(*p_meas_n, *meas_n_via))
    lines.append(_wire(*meas_n_via, *meas_n_flag))

    # --- FLAG labels ---
    lines.append(_flag("HV_IN_RAIL", *_resolve_pin("voltage", POS["V_RAIL"], "+")))
    lines.append(_flag("HV_DUT_P", *_resolve_pin("LISN50UH", POS["X_LISN_P"], "DUT")))
    lines.append(_flag("n_dut_in_pre", *_resolve_pin("CABLE_PWR", POS["X_CABLE"], "OUT")))
    lines.append(_flag(dut_pins[0] if dut_pins else "in", *p_dut))
    lines.append(_flag("DUT_GND", *dut_bottom))
    lines.append(_flag("MEAS_P", *meas_p_flag))
    lines.append(_flag("MEAS_N", *meas_n_flag))
    # SPICE GND
    lines.append(_flag("0", *v_rail_neg))
    lines.append(_flag("0", *_resolve_pin("LISN50UH", POS["X_LISN_P"], "0")))
    lines.append(_flag("0", *_resolve_pin("LISN50UH", POS["X_LISN_N"], "0")))
    lines.append(_flag("0", *_resolve_pin("CABLE_PWR", POS["X_CABLE"], "0")))
    lines.append(_flag("DUT_GND", p_inj_gnd[0], p_inj_gnd[1] + 4 * GRID))
    # B-source outputs (named net = instance's first node)
    for name in ("B_DM", "B_CM", "B_MEAS"):
        anchor = POS[name]
        # bv anchor + (0,0) is the "+" pin; we already wrote a SYMBOL line.
        lines.append(_flag(name.replace("B_", ""), *_resolve_pin("bv", anchor, "+")))

    # --- TEXT directive to include the user's .cir ---
    # LTspice executes TEXT directives starting with ! as SPICE directives.
    lines.append(
        f"TEXT {6 * GRID} {35 * GRID} Left 2 ;{title}\n"
    )
    lines.append(
        f"TEXT {6 * GRID} {38 * GRID} Left 2 "
        f"!.include {user_cir_include}\n"
    )
    # The actual .tran / .meas live in the parent testbench.cir, not here —
    # this .asc is for **visualisation**; if you click Run in LTspice it will
    # need the .cir's analysis directives. To make it standalone-runnable we
    # echo a minimal .tran here too.
    lines.append(
        f"TEXT {6 * GRID} {41 * GRID} Left 2 "
        f"!.tran 0 5m 0 100n\n"
    )

    asy_files = dict(all_static_asy())
    asy_files["DUT_FRAGMENT.asy"] = dut_fragment_asy(dut_pins or ["in", "DUT_GND"])
    return AscFile(asc_text="".join(lines), asy_files=asy_files)


def write_asc_bundle(out_dir: Path, asc: AscFile, *, base_name: str = "testbench") -> Path:
    """Write ``base_name.asc`` plus every ``.asy`` next to it. Returns the .asc path."""
    out_dir.mkdir(parents=True, exist_ok=True)
    asc_path = out_dir / f"{base_name}.asc"
    asc_path.write_text(asc.asc_text, encoding="utf-8")
    for fname, text in asc.asy_files.items():
        (out_dir / fname).write_text(text, encoding="utf-8")
    return asc_path
