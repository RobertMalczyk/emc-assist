"""Render the auto-modified EMC testbench as a block diagram.

Reads ``generated/testbench.cir`` + the included user fragment, then
draws a left-to-right block diagram showing the **composer backbone**
(LISN, cable, parasitic injection, source, probes) wired around the
**collapsed user fragment**. The point is visual verification: did the
composer connect the right nets? The user fragment is rendered as a
single labelled box with its supply / return / switch-control ports.

Usage:
    python scripts/plot_schematic.py <project_dir>
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

import matplotlib.patches as mpatches
import matplotlib.pyplot as plt

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


_TOKEN_SPLIT = re.compile(r"\s+")


_KNOWN_SUBCKTS: dict[str, list[str]] = {
    # Port names matching .SUBCKT declarations (dual-LISN composer).
    "LISN50UH": ["HV_IN", "DUT", "MEAS", "0"],
    "CABLE_PWR": ["IN", "OUT", "0"],
    "TRACE_RLC": ["IN", "OUT", "0"],
    "VIA_L": ["IN", "OUT"],
    "CAP_ESR_ESL": ["IN", "OUT"],
}


@dataclass
class CircElement:
    refdes: str
    kind: str
    nodes: list[str]
    value: str = ""
    raw: str = ""
    source_file: str = ""


def _strip_inline_comment(line: str) -> str:
    return line.split(";", 1)[0]


def parse_top_level(text: str, source_file: str) -> list[CircElement]:
    out: list[CircElement] = []
    in_subckt = False
    for raw in text.splitlines():
        line = _strip_inline_comment(raw).rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("*"):
            continue
        head = stripped.split(None, 1)[0].lower() if stripped else ""
        if head == ".subckt":
            in_subckt = True
            continue
        if head == ".ends":
            in_subckt = False
            continue
        if in_subckt or stripped.startswith("."):
            continue
        first = stripped[0].upper()
        if first not in "RLCVIXMDBSQ":
            continue
        tokens = _TOKEN_SPLIT.split(stripped)
        if len(tokens) < 3:
            continue
        refdes = tokens[0]
        if first == "X":
            tail = tokens[1:]
            subckt = ""
            nodes: list[str] = []
            for i in range(len(tail) - 1, -1, -1):
                if tail[i].upper() in _KNOWN_SUBCKTS:
                    subckt = tail[i].upper()
                    nodes = tail[:i]
                    break
            if not subckt:
                subckt = tail[-1].upper()
                nodes = tail[:-1]
            out.append(CircElement(refdes, "X", nodes, subckt, line, source_file))
        elif first in {"R", "L", "C", "V", "I", "D"}:
            out.append(
                CircElement(
                    refdes, first,
                    tokens[1:3],
                    tokens[3] if len(tokens) > 3 else "",
                    line, source_file,
                )
            )
        elif first == "M":
            out.append(
                CircElement(
                    refdes, "M",
                    tokens[1:5],
                    tokens[5] if len(tokens) > 5 else "",
                    line, source_file,
                )
            )
        elif first == "B":
            out.append(
                CircElement(
                    refdes, "B",
                    tokens[1:3],
                    " ".join(tokens[3:]),
                    line, source_file,
                )
            )
        elif first == "S":
            out.append(
                CircElement(
                    refdes, "S",
                    tokens[1:5],
                    tokens[5] if len(tokens) > 5 else "",
                    line, source_file,
                )
            )
    return out


def parse_include_target(testbench_text: str, project_dir: Path) -> Path | None:
    for line in testbench_text.splitlines():
        line = line.strip()
        if line.lower().startswith(".include"):
            rest = line.split(None, 1)[1].strip().strip('"')
            p = Path(rest)
            if not p.is_absolute():
                p = (project_dir / p).resolve()
            return p
    return None


@dataclass
class Testbench:
    tb_elements: list[CircElement] = field(default_factory=list)
    user_elements: list[CircElement] = field(default_factory=list)

    def by_refdes(self, refdes: str) -> CircElement | None:
        for el in self.tb_elements:
            if el.refdes == refdes:
                return el
        return None

    def find_x_by_subckt(self, subckt: str) -> list[CircElement]:
        return [
            el for el in self.tb_elements
            if el.kind == "X" and el.value.upper() == subckt.upper()
        ]

    def find_b_sources(self) -> list[CircElement]:
        return [el for el in self.tb_elements if el.kind == "B"]


def parse_testbench(testbench: Path) -> Testbench:
    tb_text = testbench.read_text(encoding="utf-8")
    tb_elements = parse_top_level(tb_text, "testbench.cir")
    user_path = parse_include_target(tb_text, testbench.parent)
    user_elements: list[CircElement] = []
    if user_path and user_path.is_file():
        user_text = user_path.read_text(encoding="utf-8")
        user_elements = parse_top_level(user_text, "user_circuit_fragment.cir")
    return Testbench(tb_elements=tb_elements, user_elements=user_elements)


# --- Plot primitives --------------------------------------------------------


def _box(ax, x, y, w, h, *, label, sublabel="", fc="#ffffff", ec="#222222", lw=1.8, text_size=10):
    rect = mpatches.FancyBboxPatch(
        (x - w / 2, y - h / 2), w, h,
        boxstyle="round,pad=0.05,rounding_size=0.10",
        linewidth=lw, edgecolor=ec, facecolor=fc, zorder=3,
    )
    ax.add_patch(rect)
    if sublabel:
        ax.text(x, y + 0.08, label, ha="center", va="center",
                fontsize=text_size, weight="bold", color=ec, zorder=4)
        ax.text(x, y - 0.18, sublabel, ha="center", va="center",
                fontsize=text_size - 2, color=ec, zorder=4)
    else:
        ax.text(x, y, label, ha="center", va="center",
                fontsize=text_size, weight="bold", color=ec, zorder=4)


def _wire(ax, p0, p1, *, label="", color="#222", lw=1.3, ls="-", zorder=2,
          label_offset=0.15, label_color=None):
    x0, y0 = p0
    x1, y1 = p1
    ax.plot([x0, x1], [y0, y1], color=color, lw=lw, ls=ls, zorder=zorder)
    if label:
        mx, my = (x0 + x1) / 2, (y0 + y1) / 2
        ax.text(
            mx, my + label_offset, label,
            ha="center", va="bottom",
            fontsize=8, color=label_color or color, weight="bold",
            bbox=dict(boxstyle="round,pad=0.18", facecolor="white", edgecolor="none", alpha=0.95),
            zorder=5,
        )


def _net_label(ax, x, y, name, *, color="#444", side="top"):
    dy = 0.18 if side == "top" else -0.18
    va = "bottom" if side == "top" else "top"
    ax.text(
        x, y + dy, name,
        ha="center", va=va, fontsize=7, style="italic", color=color, zorder=4,
    )


def _draw_user_fragment_expanded(ax, elements: list[CircElement], cx: float, cy: float) -> None:
    """Inside the DUT region, show each user element as a small labeled box.

    Best-effort: arranges elements in a 3-column grid centred at ``(cx, cy)``.
    Width / height of the surrounding frame scales with element count.
    """
    n = len(elements)
    cols = 3
    rows = (n + cols - 1) // cols
    cell_w, cell_h = 0.9, 0.5
    frame_w = cols * cell_w + 0.6
    frame_h = rows * cell_h + 0.8
    # Outer frame
    rect = mpatches.FancyBboxPatch(
        (cx - frame_w / 2, cy - frame_h / 2), frame_w, frame_h,
        boxstyle="round,pad=0.06,rounding_size=0.10",
        linewidth=1.6, edgecolor="#444444", facecolor="#f6f6f6", zorder=2,
    )
    ax.add_patch(rect)
    ax.text(cx, cy + frame_h / 2 - 0.15, "USER FRAGMENT (expanded)",
            ha="center", va="top", fontsize=9, weight="bold",
            color="#444444", zorder=4)
    # Element cells
    for i, el in enumerate(elements):
        r = i // cols
        c = i % cols
        x = cx - (cols - 1) / 2 * cell_w + c * cell_w
        y = cy + (rows - 1) / 2 * cell_h - r * cell_h - 0.15
        kind_color = {
            "R": "#ff7f0e",
            "L": "#1f77b4",
            "C": "#2ca02c",
            "V": "#e377c2",
            "S": "#9467bd",
            "D": "#bcbd22",
        }.get(el.kind, "#888888")
        ax.add_patch(mpatches.FancyBboxPatch(
            (x - cell_w / 2 + 0.05, y - cell_h / 2 + 0.05),
            cell_w - 0.1, cell_h - 0.1,
            boxstyle="round,pad=0.03,rounding_size=0.05",
            linewidth=1.0, edgecolor=kind_color, facecolor="white", zorder=3,
        ))
        ax.text(x, y, f"{el.refdes}\n{el.value or el.kind}",
                ha="center", va="center", fontsize=7,
                color=kind_color, weight="semibold", zorder=4)


def render(tb: Testbench, out_path: Path, *, title: str, expand_user_fragment: bool = False) -> None:
    fig, ax = plt.subplots(figsize=(15, 8))

    # Vertical lanes
    Y_RAIL = 5.5
    Y_GND = 1.0
    Y_MEAS_HI = 7.0
    Y_MEAS_LO = -0.5

    # Resolve key nets from the parsed elements.
    lisn_p = tb.by_refdes("X_LISN_P")
    lisn_n = tb.by_refdes("X_LISN_N")
    cable = tb.by_refdes("X_CABLE")
    inj = next(
        (el for el in tb.tb_elements if el.refdes.startswith("X_TRACE_")
         or el.refdes.startswith("X_VIA_")
         or el.refdes.startswith("X_CAP_")),
        None,
    )
    v_rail = tb.by_refdes("V_RAIL")

    # X positions (left to right)
    X_VR = 0.5
    X_LISN_P = 2.5
    X_CABLE = 5.0
    X_INJ = 7.5
    X_DUT = 11.0
    X_LISN_N = 5.0
    X_PROBES = 13.5

    # --- V_RAIL ---
    _box(ax, X_VR, Y_RAIL, 1.4, 0.9, label="V_RAIL",
         sublabel=v_rail.value if v_rail else "DC 24",
         fc="#fdd0e8", ec="#c92a7a")

    # --- LISN+ ---
    if lisn_p:
        nets_p = lisn_p.nodes  # [HV_IN_RAIL, HV_DUT_P, MEAS_P, 0]
        _box(ax, X_LISN_P, Y_RAIL, 1.8, 1.2,
             label=lisn_p.refdes, sublabel="LISN50UH",
             fc="#cce4f5", ec="#1f77b4")
        # wires: V_RAIL -> X_LISN_P (HV_IN_RAIL)
        _wire(ax, (X_VR + 0.7, Y_RAIL), (X_LISN_P - 0.9, Y_RAIL),
              label=nets_p[0], color="#c92a7a", lw=2.0)
        # MEAS_P stub up (label at endpoint only, no duplicate midline label)
        _wire(ax, (X_LISN_P, Y_RAIL + 0.6), (X_LISN_P, Y_MEAS_HI - 0.3),
              color="#9467bd", lw=1.4, ls="--")
        ax.scatter([X_LISN_P], [Y_MEAS_HI - 0.3], s=70, color="#9467bd", zorder=5)
        ax.text(X_LISN_P, Y_MEAS_HI - 0.05, nets_p[2], ha="center", va="bottom",
                fontsize=9, color="#9467bd", weight="bold", zorder=6,
                bbox=dict(boxstyle="round,pad=0.12", facecolor="white",
                          edgecolor="#9467bd", linewidth=0.8, alpha=0.95))
        # GND stub down to ground rail
        _wire(ax, (X_LISN_P - 0.4, Y_RAIL - 0.6), (X_LISN_P - 0.4, Y_GND),
              color="#222", lw=1.2, ls=":")

    # --- Cable ---
    if cable:
        nets_c = cable.nodes  # [HV_DUT_P, OUT, 0]
        _box(ax, X_CABLE, Y_RAIL, 1.6, 1.0,
             label=cable.refdes, sublabel="CABLE_PWR",
             fc="#cff4f3", ec="#17becf")
        # LISN_P -> Cable
        _wire(ax, (X_LISN_P + 0.9, Y_RAIL), (X_CABLE - 0.8, Y_RAIL),
              label=nets_p[1] if lisn_p else "HV_DUT_P", color="#c92a7a", lw=2.0)
        # GND stub
        _wire(ax, (X_CABLE - 0.4, Y_RAIL - 0.5), (X_CABLE - 0.4, Y_GND),
              color="#222", lw=1.0, ls=":")

    # --- Parasitic injection ---
    if inj:
        nets_i = inj.nodes
        _box(ax, X_INJ, Y_RAIL, 1.8, 1.2,
             label=inj.refdes, sublabel=inj.value + "\n(M2.10 inject)",
             fc="#d4f3d4", ec="#2ca02c", lw=2.4)
        # Cable -> Injection
        _wire(ax, (X_CABLE + 0.8, Y_RAIL), (X_INJ - 0.9, Y_RAIL),
              label=nets_c[1] if cable else nets_i[0], color="#c92a7a", lw=2.0)
        # Injection GND stub
        _wire(ax, (X_INJ - 0.3, Y_RAIL - 0.6), (X_INJ - 0.3, Y_GND),
              label="C_par→" + (nets_i[2] if len(nets_i) > 2 else "0"),
              color="#222", lw=1.0, ls=":", label_offset=-0.6, label_color="#2ca02c")

    # --- DUT (user fragment) ---
    n_user_elements = len(tb.user_elements)
    # Per-net parasitics: each series net (M2.10.6) emits one R_par_* +
    # L_par_* + C_par_*; each shunt-only net (M2.10.5) emits one C_par_*.
    n_series = sum(1 for el in tb.tb_elements if el.refdes.startswith("R_par_"))
    n_shunt = sum(1 for el in tb.tb_elements if el.refdes.startswith("C_par_")) - n_series
    dut_input = (
        inj.nodes[1] if inj and len(inj.nodes) > 1
        else (cable.nodes[1] if cable else "in")
    )
    if expand_user_fragment and tb.user_elements:
        _draw_user_fragment_expanded(ax, tb.user_elements, X_DUT, Y_RAIL)
    else:
        sub = f"{n_user_elements} elements\n(included from\nuser_circuit_fragment.cir)"
        _box(ax, X_DUT, Y_RAIL, 2.4, 2.4,
             label="USER FRAGMENT\n(DUT)",
             sublabel=sub,
             fc="#eeeeee", ec="#444444", lw=1.8, text_size=10)
    if n_series or n_shunt:
        ax.text(X_DUT, Y_RAIL - 1.55,
                f"+ per-net parasitics: {n_series} series R+L+C splice "
                f"(M2.10.6)\n+ {n_shunt} shunt C → DUT_GND (M2.10.5)",
                ha="center", va="top", fontsize=8.5, color="#2c7a2c",
                style="italic", weight="bold", zorder=6)
    # Inject -> DUT
    _wire(ax, (X_INJ + 0.9, Y_RAIL), (X_DUT - 1.2, Y_RAIL),
          label=dut_input, color="#c92a7a", lw=2.0)
    # DUT -> DUT_GND
    _wire(ax, (X_DUT - 1.2, Y_RAIL - 1.0), (X_LISN_N + 0.9, Y_GND),
          label="DUT_GND", color="#222", lw=2.0)

    # --- LISN- on the return path ---
    if lisn_n:
        nets_n = lisn_n.nodes  # [0, DUT_GND, MEAS_N, 0]
        _box(ax, X_LISN_N, Y_GND, 1.8, 1.0,
             label=lisn_n.refdes, sublabel="LISN50UH",
             fc="#cce4f5", ec="#1f77b4")
        # MEAS_N stub down
        _wire(ax, (X_LISN_N, Y_GND - 0.5), (X_LISN_N, Y_MEAS_LO + 0.2),
              label=nets_n[2], color="#9467bd", lw=1.4, ls="--")
        ax.scatter([X_LISN_N], [Y_MEAS_LO + 0.2], s=70, color="#9467bd", zorder=5)
        ax.text(X_LISN_N, Y_MEAS_LO + 0.05, nets_n[2], ha="center", va="top",
                fontsize=9, color="#9467bd", weight="bold", zorder=6)
        # System ground "0" wire back to V_RAIL-
        _wire(ax, (X_LISN_N - 0.9, Y_GND), (X_VR, Y_GND),
              label="0 (SPICE GND)", color="#222", lw=1.6)
        _wire(ax, (X_VR, Y_RAIL - 0.45), (X_VR, Y_GND), color="#c92a7a", lw=1.5)

    # --- Probes (B_DM, B_CM, B_MEAS) ---
    # Draw a single vertical "probe bus" at the probe column that
    # collects MEAS_P (from top) and MEAS_N (from bottom). Each B-source
    # taps the bus on one short stub. Avoids the previous spider-web of
    # crossing dashed lines.
    b_sources = tb.find_b_sources()
    if b_sources:
        x_bus = X_PROBES - 1.2
        # Bus segments
        _wire(ax, (X_LISN_P, Y_MEAS_HI - 0.3), (x_bus, Y_MEAS_HI - 0.3),
              color="#9467bd", lw=1.1, ls="--")
        _wire(ax, (x_bus, Y_MEAS_HI - 0.3), (x_bus, Y_MEAS_LO + 0.2),
              color="#9467bd", lw=1.1, ls="--")
        _wire(ax, (X_LISN_N, Y_MEAS_LO + 0.2), (x_bus, Y_MEAS_LO + 0.2),
              color="#9467bd", lw=1.1, ls="--")
        ax.text(x_bus + 0.05, (Y_MEAS_HI + Y_MEAS_LO) / 2,
                "MEAS_P\n+\nMEAS_N\n(probe bus)",
                fontsize=7, color="#9467bd", style="italic",
                ha="left", va="center", zorder=5)
        for i, b in enumerate(b_sources):
            y_off = Y_MEAS_HI - i * 1.3
            _box(ax, X_PROBES, y_off, 1.4, 0.9,
                 label=b.refdes, sublabel=b.nodes[0],
                 fc="#f1e1f8", ec="#9467bd", text_size=8)
            # short stub from bus to each B-source's left edge
            _wire(ax, (x_bus, y_off), (X_PROBES - 0.7, y_off),
                  color="#9467bd", lw=1.0, ls="--")

    # Title and legend
    ax.set_title(title, fontsize=11, weight="bold")
    legend_handles = [
        mpatches.Patch(facecolor="#fdd0e8", edgecolor="#c92a7a", label="V_RAIL test source"),
        mpatches.Patch(facecolor="#cce4f5", edgecolor="#1f77b4", label="CISPR dual-LISN"),
        mpatches.Patch(facecolor="#cff4f3", edgecolor="#17becf", label="Cable model"),
        mpatches.Patch(facecolor="#d4f3d4", edgecolor="#2ca02c", linewidth=2, label="M2.10 parasitic injection"),
        mpatches.Patch(facecolor="#eeeeee", edgecolor="#444444", label="User DUT fragment"),
        mpatches.Patch(facecolor="#f1e1f8", edgecolor="#9467bd", label="B-source DM/CM/MEAS probes"),
    ]
    ax.legend(handles=legend_handles, loc="lower center", fontsize=8,
              ncol=3, framealpha=0.95, bbox_to_anchor=(0.5, -0.05))

    # Coordinate frame
    ax.set_xlim(-1.0, 15.5)
    ax.set_ylim(-2.5, 8.5)
    ax.set_aspect("equal")
    ax.set_axis_off()
    fig.tight_layout()
    fig.savefig(out_path, dpi=140)
    plt.close(fig)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("project_dir", type=Path)
    ap.add_argument(
        "--expand-user-fragment",
        action="store_true",
        default=False,
        help="Show every user-fragment element as its own labelled cell "
             "inside the DUT region instead of as a single black box.",
    )
    args = ap.parse_args()
    proj = args.project_dir.resolve()
    tb_path = proj / "generated" / "testbench.cir"
    if not tb_path.is_file():
        print(f"missing testbench.cir at {tb_path} — run `pipeline run` first.")
        return 1
    tb = parse_testbench(tb_path)
    suffix = "_expanded" if args.expand_user_fragment else ""
    out = proj / "reports" / f"{proj.name}_schematic{suffix}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    render(
        tb, out,
        title=(
            f"Auto-modified EMC testbench — {proj.name}\n"
            "Composer backbone (LISN + cable + M2.10 parasitic injection + DM/CM probes) "
            "wired around the "
            + ("expanded" if args.expand_user_fragment else "collapsed")
            + " user fragment"
        ),
        expand_user_fragment=args.expand_user_fragment,
    )
    print(f"Wrote {out}")
    # textual backbone trace
    print(f"\nParsed: {len(tb.tb_elements)} testbench-level elements, "
          f"{len(tb.user_elements)} user fragment elements")
    print("\nBackbone (composer-emitted):")
    for el in tb.tb_elements:
        if el.refdes.startswith(("V_", "X_", "B_")):
            ports = " ".join(el.nodes)
            extra = f" -> {el.value}" if el.kind == "X" else f" {el.value}" if el.value else ""
            print(f"  {el.refdes:14s} {ports}{extra}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
