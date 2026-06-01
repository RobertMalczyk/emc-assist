"""Compose a complete ``testbench.cir`` from parasitics + LISN + cable.

Rules:
- The user file is never modified; it is included via ``.include`` (when
  the path exists) and LTspice resolves models relative to the project
  directory.
- Parasitics are added as ``.SUBCKT`` blocks with ``.param`` min/typ/max
  entries.
- The min/typ/max sweep is realised with
  ``.step param sweep_corner list 0 1 2`` and a convention that
  ``sweep_corner==0`` → min, ``==1`` → typ, ``==2`` → max.
- For MVP we leave the actual X-instances of parasitic subcircuits empty
  — the user (or a future `.asc` editing module) inserts them manually.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import ClassVar, Iterable

from emc_assistant.agents.injection import (
    ParasiticInjection,
    SeriesParasitic,
    ShuntParasitic,
)
from emc_assistant.netlist.signals import Signal
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.testbench.fragments import (
    capacitor_with_esr_esl_fragment,
    trace_rlc_fragment,
    via_fragment,
)
from emc_assistant.testbench.generators import (
    CableSpec,
    LisnSpec,
    generate_cable_fragment,
    generate_lisn_subckt,
)


CABLE_OUT_PRE_NET: str = "n_dut_in_pre"
"""M2.10 convention: when an injection plan is provided, the cable's
downstream port lands on this net instead of the user's supply net.
The parasitics agent's first injection bridges
``CABLE_OUT_PRE_NET`` → user supply with a series TRACE_RLC so the
parasitic L band actually sits in the signal path."""


@dataclass
class TestbenchWiring:
    """How the LISN+cable chain is wired between an external supply and the DUT.

    When supplied to a ``TestbenchPlan``, the composer emits the X-instances
    so ``V(MEAS)`` exists as a real node and the default ``.meas`` directives
    have a signal to measure. The user fragment is expected to have its
    primary V-source stripped (see ``netlist.fragment.write_user_fragment``)
    so the LISN chain owns the DUT supply.

    ``lisn_mode`` selects the LISN topology:

    - ``"dual"`` (default, CISPR-style for low-voltage DC): one LISN on
      the supply rail, a second LISN on the return rail. Source ground
      stays as SPICE's universal ``0`` while the DUT's local ground is
      lifted to a separate ``DUT_GND`` node (the fragment preprocessor
      renames the user's ``0`` references in node positions). Enables
      true DM = V(MEAS_P) − V(MEAS_N) and CM = (V(MEAS_P) + V(MEAS_N))/2
      separation per the ADI / Würth LTspice-EMC methodology indexed at
      SRC-001 / SRC-021 / SRC-022.
    - ``"single"``: legacy mode, a single LISN on the positive rail; the
      DUT shares SPICE ground. CM separation is not physically modellable;
      V(DM) collapses to V(MEAS). Use for backwards compatibility with
      M2.6.1 / M2.7 behaviour.

    Future: an M2.10 specialist agent reading the user schematic should
    pick the right mode automatically. Until then the choice is per-project.
    """

    __test__: ClassVar[bool] = False  # not a pytest test class (name starts with "Test")
    external_supply_v: float = 24.0
    dut_supply_net: str = "DUT_SUPPLY"
    dut_return_net: str = "0"
    lisn_mode: str = "dual"


@dataclass
class TestbenchPlan:
    """All inputs to ``compose_testbench_cir``."""

    __test__: ClassVar[bool] = False  # not a pytest test class (name starts with "Test")
    title: str
    parasitics: list[ParasiticEstimate]
    user_netlist: Path | None = None
    lisn: LisnSpec | None = field(default_factory=LisnSpec)
    cable: CableSpec | None = field(default_factory=CableSpec)
    capacitors: list[dict] = field(default_factory=list)
    """List of ``{'name': str, 'capacitance_f': float, 'esr_ohm': float, 'esl_h': float}``."""
    tran_directive: str = ".tran 0 5m 0 100n"
    options_directive: str = ""
    """M2.13 — optional ``.options`` line (integration method + solver
    tolerances), built from the structured simulation settings. Emitted
    just before ``.tran`` when non-empty."""
    sweep_corners: bool = True
    meas_directives: list[str] | None = None
    """Optional ``.meas`` directives. If ``None``, defaults are emitted for the
    LISN measurement net ``V(MEAS)`` so the resulting ``.log`` carries metrics
    that the ranking/report can consume even without ``.raw``."""
    wiring: TestbenchWiring | None = None
    """Optional LISN/cable wiring. When set, the composer instantiates
    ``V_RAIL``, ``X_LISN`` and ``X_CABLE`` so the DUT supply rail is fed
    through the LISN and ``V(MEAS)`` becomes a measurable node."""
    injection_plan: list[ParasiticInjection] = field(default_factory=list)
    """M2.10 parasitic-injection plan. When non-empty AND ``wiring`` is
    set, the cable's downstream port lands on ``CABLE_OUT_PRE_NET``
    instead of the user supply net, and the listed X-instances are
    emitted after the subcircuit definitions. When empty, the composer
    falls back to M2.6.1 wiring (cable directly to user supply)."""
    series_plan: list[SeriesParasitic] = field(default_factory=list)
    """M2.10.6 per-net series parasitics. For each clean 2-element net
    the fragment preprocessor cut, the composer emits bare R+L+C
    elements (series R+L between ``<net>__pre`` and ``<net>``, shunt C
    to the return node). Requires the matching ``series_split_nets`` to
    have been passed to the fragment preprocessor."""
    shunt_plan: list[ShuntParasitic] = field(default_factory=list)
    """M2.10.5 per-net shunt parasitics. One ``C_par_<net>`` capacitor
    per user net (to the return node), so every net carries a parasitic
    even when it cannot take a series splice. Emitted after the
    injection plan; independent of ``injection_plan`` and ``wiring``."""
    signals: list[Signal] = field(default_factory=list)
    """M2.10.1 tracked user signals. When non-empty, the composer
    appends per-signal ``.meas TRAN <name>_peak MAX <expr>`` directives
    so the resulting ``.log`` carries the metrics in the user's
    vocabulary (e.g. ``Vout_peak`` alongside the canonical
    ``vpeak`` / ``dm_peak``)."""


DEFAULT_MEAS_DIRECTIVES: tuple[str, ...] = (
    ".meas TRAN vpeak MAX V(MEAS)",
    ".meas TRAN vmin MIN V(MEAS)",
    ".meas TRAN vp2p PP V(MEAS)",
    ".meas TRAN vrms RMS V(MEAS)",
    ".meas TRAN dm_peak MAX V(DM)",
    ".meas TRAN dm_p2p PP V(DM)",
    ".meas TRAN dm_rms RMS V(DM)",
    ".meas TRAN cm_peak MAX V(CM)",
    ".meas TRAN cm_p2p PP V(CM)",
    ".meas TRAN cm_rms RMS V(CM)",
)
"""Default ``.meas`` directives covering the raw measurement node
``V(MEAS)`` plus the explicit ``V(DM)`` and ``V(CM)`` probes the composer
emits as behavioural sources.

These map 1:1 to the metric keys the report ranks against:
``v_meas_peak``, ``v_meas_min``, ``v_meas_peak_to_peak``, ``v_meas_rms``
plus ``dm_peak`` / ``dm_p2p`` / ``dm_rms`` and (for dual-LISN topologies)
``cm_peak`` / ``cm_p2p`` / ``cm_rms``.

In ``lisn_mode='single'`` (legacy), CM separation is not physically
modellable so ``V(CM)`` simply collapses to half of ``V(MEAS)``; the
metric is emitted for schema stability but should not be treated as a
real CM measurement.
"""


SINGLE_LISN_PROBE_FRAGMENT: str = (
    "* --- Single-LISN probes (legacy mode) ---\n"
    "* V(DM) tracks V(MEAS); V(CM) is not physically separable in single mode.\n"
    "B_DM DM 0 V=V(MEAS)\n"
    "B_CM CM 0 V=V(MEAS)/2"
)


DUAL_LISN_PROBE_FRAGMENT: str = (
    "* --- Dual-LISN DM/CM probes (CISPR-style) ---\n"
    "* DM = V(MEAS_P) - V(MEAS_N), CM = (V(MEAS_P) + V(MEAS_N))/2.\n"
    "B_DM DM 0 V=V(MEAS_P)-V(MEAS_N)\n"
    "B_CM CM 0 V=(V(MEAS_P)+V(MEAS_N))/2\n"
    "B_MEAS MEAS 0 V=V(MEAS_P)"
)
"""B_MEAS keeps a ``V(MEAS)`` alias so legacy `.meas TRAN ... V(MEAS)`
directives and downstream metric keys keep working. The alias is the
positive-rail LISN output, matching the legacy single-rail meaning."""


def _pick(
    parasitics: Iterable[ParasiticEstimate],
    *,
    structure: str,
    parasitic_type: str,
) -> ParasiticEstimate | None:
    for p in parasitics:
        if p.structure == structure and p.parasitic_type == parasitic_type:
            return p
    return None


def compose_testbench_cir(plan: TestbenchPlan) -> str:
    """Return the contents of ``testbench.cir`` as a string."""
    parts: list[str] = []
    parts.append(f"* {plan.title}")
    parts.append("* Auto-generated by emc-assistant. Do not edit by hand; regenerate.")
    parts.append("* Pre-compliance engineering aid only — not a normative receiver model.")
    parts.append("")

    if plan.user_netlist is not None and plan.user_netlist.is_file():
        parts.append("* User input netlist (read-only include)")
        parts.append(f".include {plan.user_netlist.resolve().as_posix()}")
        parts.append("")
    else:
        parts.append("* No user netlist included (path missing or empty).")
        parts.append("")

    if plan.lisn is not None:
        parts.append(generate_lisn_subckt(plan.lisn).rstrip())
        parts.append("")
    if plan.cable is not None:
        parts.append(generate_cable_fragment(plan.cable).rstrip())
        parts.append("")

    if plan.wiring is not None:
        w = plan.wiring
        mode = (getattr(w, "lisn_mode", "dual") or "dual").lower()
        # M2.10: when an injection plan is present, the cable lands on
        # the intermediate net CABLE_OUT_PRE_NET so the plan's first
        # X-instance can sit in series between it and the user supply.
        cable_target = CABLE_OUT_PRE_NET if plan.injection_plan else w.dut_supply_net
        if mode == "dual":
            parts.append("* --- Auto-wiring (dual-LISN, CISPR-style): supply+ and return through their own LISNs ---")
            parts.append("* User-confirmed via testbench_wiring in user_context.json.")
            parts.append(f"V_RAIL HV_IN_RAIL 0 DC {w.external_supply_v}")
            parts.append("X_LISN_P HV_IN_RAIL HV_DUT_P MEAS_P 0 LISN50UH")
            parts.append("X_LISN_N 0 DUT_GND MEAS_N 0 LISN50UH")
            parts.append(
                f"X_CABLE HV_DUT_P {cable_target} DUT_GND CABLE_PWR"
            )
            parts.append("")
        else:
            parts.append("* --- Auto-wiring (single-LISN, legacy): supply+ through LISN; DUT shares SPICE ground ---")
            parts.append("* User-confirmed via testbench_wiring in user_context.json.")
            parts.append(f"V_RAIL HV_IN_RAIL 0 DC {w.external_supply_v}")
            parts.append("X_LISN HV_IN_RAIL HV_DUT MEAS 0 LISN50UH")
            parts.append(
                f"X_CABLE HV_DUT {cable_target} {w.dut_return_net} CABLE_PWR"
            )
            parts.append("")

    trace_r = _pick(plan.parasitics, structure="trace", parasitic_type="R")
    trace_l = _pick(plan.parasitics, structure="trace", parasitic_type="L")
    trace_c = _pick(plan.parasitics, structure="trace", parasitic_type="C")
    if trace_r and trace_l and trace_c:
        parts.append(
            trace_rlc_fragment(r_est=trace_r, l_est=trace_l, c_est=trace_c).rstrip()
        )
        parts.append("")

    via_l = _pick(plan.parasitics, structure="via", parasitic_type="L")
    if via_l:
        parts.append(via_fragment(via_l).rstrip())
        parts.append("")

    for cap in plan.capacitors:
        parts.append(
            capacitor_with_esr_esl_fragment(
                capacitance_f=float(cap["capacitance_f"]),
                esr_ohm=float(cap.get("esr_ohm", 0.0)),
                esl_h=float(cap.get("esl_h", 0.0)),
                name=str(cap.get("name", "CAP_ESR_ESL")),
            ).rstrip()
        )
        parts.append("")

    if plan.injection_plan:
        parts.append("* --- Parasitic injection plan (M2.10) ---")
        parts.append(
            f"* {len(plan.injection_plan)} X-instance(s) splicing composer subcircuits "
            "into the testbench between the cable output and the user fragment."
        )
        for inj in plan.injection_plan:
            parts.append(
                f"* injection: {inj.instance_name} | {inj.subckt_name} | "
                f"rationale: {inj.rationale}"
            )
            if inj.parasitic_id:
                parts.append(f"*   parasitic_id={inj.parasitic_id}, corner={inj.corner}")
            if inj.rule_id:
                parts.append(f"*   rule={inj.rule_id}")
            parts.append(inj.to_spice_line())
        parts.append("")

    if plan.series_plan:
        n_override = sum(1 for s in plan.series_plan if s.source == "project_override")
        parts.append("* --- Per-net series parasitics (M2.10.6) ---")
        parts.append(
            f"* {len(plan.series_plan)} clean 2-element net(s) get a series R+L "
            f"splice + shunt C ({n_override} from project override, "
            f"{len(plan.series_plan) - n_override} rule-of-thumb estimate). "
            "The fragment preprocessor cut each net at its first element."
        )
        for se in plan.series_plan:
            parts.append(f"* series: {se.net} | {se.source} | {se.rationale}")
            parts.extend(se.to_spice_lines())
        parts.append("")

    if plan.shunt_plan:
        n_override = sum(1 for s in plan.shunt_plan if s.source == "project_override")
        parts.append("* --- Per-net shunt parasitics (M2.10.5) ---")
        parts.append(
            f"* {len(plan.shunt_plan)} shunt capacitor(s): first-order stray C from "
            f"each user net to its return node ({n_override} from project override, "
            f"{len(plan.shunt_plan) - n_override} rule-of-thumb estimate). "
            "Engineering estimates — verify against layout extraction."
        )
        for sh in plan.shunt_plan:
            parts.append(f"* shunt: {sh.net} | {sh.source} | {sh.rationale}")
            parts.append(sh.to_spice_line())
        parts.append("")

    if plan.lisn is not None:
        wiring_mode = "dual"
        if plan.wiring is not None:
            wiring_mode = (getattr(plan.wiring, "lisn_mode", "dual") or "dual").lower()
        if wiring_mode == "dual" and plan.wiring is not None:
            parts.append(DUAL_LISN_PROBE_FRAGMENT)
        else:
            parts.append(SINGLE_LISN_PROBE_FRAGMENT)
        parts.append("")

    if plan.sweep_corners:
        parts.append("* Sweep corners: 0=min, 1=typ, 2=max")
        parts.append(".step param sweep_corner list 0 1 2")

    if plan.options_directive.strip():
        parts.append(plan.options_directive.strip())
    parts.append(plan.tran_directive)

    meas = plan.meas_directives if plan.meas_directives is not None else list(DEFAULT_MEAS_DIRECTIVES)
    if meas:
        parts.append("* Measurements emitted into .log (parsed without .raw):")
        parts.extend(meas)

    if plan.signals:
        parts.append("* --- Tracked user signals (M2.10.1) ---")
        for s in plan.signals:
            if s.kind in {"voltage", "current", "power"}:
                # Each signal emits _peak / _rms / _avg metrics for consistent reporting.
                parts.append(f".meas TRAN {s.name}_peak MAX {s.expr}")
                parts.append(f".meas TRAN {s.name}_rms RMS {s.expr}")
                parts.append(f".meas TRAN {s.name}_avg AVG {s.expr}")

    parts.append(".end")
    parts.append("")
    return "\n".join(parts)
