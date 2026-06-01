"""LTspice ``.asy`` symbol templates for composer-emitted subcircuits.

Each composer-side `.SUBCKT` (LISN50UH, CABLE_PWR, TRACE_RLC, VIA_L,
CAP_ESR_ESL) plus the DUT-fragment placeholder gets a hierarchical
block symbol so the auto-generated ``testbench.asc`` opens in LTspice
as a readable schematic instead of a SPICE blob.

LTspice ``.asy`` is a tiny line-based format. We emit minimal symbols:
a rectangle, the instance-name and value windows, the X prefix, and
labelled pins. The user's ``.cir`` fragment is included as a text
``TEXT`` directive in the parent ``.asc`` so simulation still works.

Coordinates use LTspice's 16-pixel grid. Symbols are placed so a 16
divides every pin x/y — this keeps wires straight when LTspice opens
the file.
"""

from __future__ import annotations


def _header(symbol_type: str = "BLOCK") -> list[str]:
    return ["Version 4", f"SymbolType {symbol_type}"]


def _instance_windows(width: int, height: int) -> list[str]:
    """Place the InstName window above the symbol and Value below."""
    return [
        f"WINDOW 0 {width // 2} -8 Bottom 2",
        f"WINDOW 3 {width // 2} {height + 8} Top 2",
    ]


def _box(width: int, height: int) -> list[str]:
    return [f"RECTANGLE Normal 0 0 {width} {height}"]


def _pin(x: int, y: int, name: str, *, order: int, side: str = "LEFT") -> list[str]:
    """Emit a PIN + PINATTR pair.

    ``side`` controls the label position (``LEFT``, ``RIGHT``, ``TOP``,
    ``BOTTOM``, ``NONE``). The numeric offset (8) is in pixels.
    """
    return [
        f"PIN {x} {y} {side} 8",
        f"PINATTR PinName {name}",
        f"PINATTR SpiceOrder {order}",
    ]


def lisn50uh_asy() -> str:
    """4-pin LISN block: HV_IN (left), DUT (right), MEAS (top), 0 (bottom)."""
    W, H = 96, 64
    lines: list[str] = []
    lines += _header()
    lines += _instance_windows(W, H)
    lines += _box(W, H)
    lines += [f"TEXT {W // 2} {H // 2} Center 2 LISN50UH"]
    lines += [
        "SYMATTR Prefix X",
        "SYMATTR Description CISPR-style 50uH/0.1uF/50ohm LISN (educational)",
        "SYMATTR SpiceModel LISN50UH",
    ]
    lines += _pin(0, H // 2, "HV_IN", order=1, side="LEFT")
    lines += _pin(W, H // 2, "DUT", order=2, side="RIGHT")
    lines += _pin(W // 2, 0, "MEAS", order=3, side="TOP")
    lines += _pin(W // 2, H, "0", order=4, side="BOTTOM")
    return "\n".join(lines) + "\n"


def cable_pwr_asy() -> str:
    """3-pin cable block: IN (left), OUT (right), 0 (bottom)."""
    W, H = 96, 48
    lines: list[str] = []
    lines += _header()
    lines += _instance_windows(W, H)
    lines += _box(W, H)
    lines += [f"TEXT {W // 2} {H // 2} Center 2 CABLE_PWR"]
    lines += [
        "SYMATTR Prefix X",
        "SYMATTR Description LC-ladder cable model (5 segments, 1 m)",
        "SYMATTR SpiceModel CABLE_PWR",
    ]
    lines += _pin(0, H // 2, "IN", order=1, side="LEFT")
    lines += _pin(W, H // 2, "OUT", order=2, side="RIGHT")
    lines += _pin(W // 2, H, "0", order=3, side="BOTTOM")
    return "\n".join(lines) + "\n"


def trace_rlc_asy() -> str:
    """3-pin trace-parasitic block: IN, OUT, 0."""
    W, H = 96, 48
    lines: list[str] = []
    lines += _header()
    lines += _instance_windows(W, H)
    lines += _box(W, H)
    lines += [f"TEXT {W // 2} {H // 2} Center 2 TRACE_RLC"]
    lines += [
        "SYMATTR Prefix X",
        "SYMATTR Description Trace R+L+C parasitic (composer subckt)",
        "SYMATTR SpiceModel TRACE_RLC",
    ]
    lines += _pin(0, H // 2, "IN", order=1, side="LEFT")
    lines += _pin(W, H // 2, "OUT", order=2, side="RIGHT")
    lines += _pin(W // 2, H, "0", order=3, side="BOTTOM")
    return "\n".join(lines) + "\n"


def via_l_asy() -> str:
    """2-pin via-inductance block: IN, OUT."""
    W, H = 64, 32
    lines: list[str] = []
    lines += _header()
    lines += _instance_windows(W, H)
    lines += _box(W, H)
    lines += [f"TEXT {W // 2} {H // 2} Center 2 VIA_L"]
    lines += [
        "SYMATTR Prefix X",
        "SYMATTR Description Via inductance (composer subckt)",
        "SYMATTR SpiceModel VIA_L",
    ]
    lines += _pin(0, H // 2, "IN", order=1, side="LEFT")
    lines += _pin(W, H // 2, "OUT", order=2, side="RIGHT")
    return "\n".join(lines) + "\n"


def cap_esr_esl_asy() -> str:
    """2-pin capacitor-with-ESR-ESL block."""
    W, H = 80, 32
    lines: list[str] = []
    lines += _header()
    lines += _instance_windows(W, H)
    lines += _box(W, H)
    lines += [f"TEXT {W // 2} {H // 2} Center 2 CAP_ESR_ESL"]
    lines += [
        "SYMATTR Prefix X",
        "SYMATTR Description Capacitor with ESR + ESL (composer subckt)",
        "SYMATTR SpiceModel CAP_ESR_ESL",
    ]
    lines += _pin(0, H // 2, "IN", order=1, side="LEFT")
    lines += _pin(W, H // 2, "OUT", order=2, side="RIGHT")
    return "\n".join(lines) + "\n"


def dut_fragment_asy(pin_names: list[str]) -> str:
    """Variable-pin DUT placeholder block.

    Pins are placed clockwise starting at the left side. The first pin
    is the supply input (left middle); subsequent pins wrap onto the
    bottom (return), right, and top sides. The user's ``.cir`` is
    included separately via a TEXT directive in the parent ``.asc``;
    this block is just the visual placeholder so the wires terminate
    on something.
    """
    W, H = 160, 128
    lines: list[str] = []
    lines += _header()
    lines += _instance_windows(W, H)
    lines += _box(W, H)
    lines += [f"TEXT {W // 2} {H // 2 - 6} Center 3 USER FRAGMENT"]
    lines += [f"TEXT {W // 2} {H // 2 + 14} Center 2 (.include)"]
    lines += [
        "SYMATTR Prefix X",
        "SYMATTR Description User DUT placeholder; netlist comes from .include",
        "SYMATTR SpiceModel DUT_FRAGMENT",
    ]
    sides_cw = ["LEFT", "BOTTOM", "RIGHT", "TOP"]
    cursor = {"LEFT": 0, "BOTTOM": 0, "RIGHT": 0, "TOP": 0}
    capacity = {"LEFT": 3, "BOTTOM": 4, "RIGHT": 3, "TOP": 4}
    for order, name in enumerate(pin_names, start=1):
        side = sides_cw[(order - 1) % 4]
        i = cursor[side]
        n = capacity[side]
        if side == "LEFT":
            x, y = 0, int(H * (i + 1) / (n + 1)) // 16 * 16
        elif side == "RIGHT":
            x, y = W, int(H * (i + 1) / (n + 1)) // 16 * 16
        elif side == "TOP":
            x, y = int(W * (i + 1) / (n + 1)) // 16 * 16, 0
        else:  # BOTTOM
            x, y = int(W * (i + 1) / (n + 1)) // 16 * 16, H
        cursor[side] = i + 1
        lines += _pin(x, y, name, order=order, side=side)
    return "\n".join(lines) + "\n"


ASY_GENERATORS: dict[str, callable] = {
    "LISN50UH": lisn50uh_asy,
    "CABLE_PWR": cable_pwr_asy,
    "TRACE_RLC": trace_rlc_asy,
    "VIA_L": via_l_asy,
    "CAP_ESR_ESL": cap_esr_esl_asy,
}
"""Map subckt name → zero-arg generator. ``DUT_FRAGMENT`` is handled
separately because its pin count depends on topology."""


def all_static_asy() -> dict[str, str]:
    """Return ``{filename: text}`` for every static composer-subckt symbol."""
    return {f"{name}.asy": gen() for name, gen in ASY_GENERATORS.items()}
