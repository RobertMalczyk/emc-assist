"""Parasitic-injection dataclasses (M2.10 / M2.10.5).

A :class:`ParasiticInjection` is one entry in the agent → composer
contract: which composer-generated subcircuit to instantiate, with what
nets, and why. Matches ``schemas/parasitic_injection.schema.json``.

A :class:`ShuntParasitic` (M2.10.5) is the per-net counterpart. A
series splice needs a clean 2-element cut point; a shunt capacitance to
the return node attaches to *any* net — star/bus nets included —
without rerouting, so it is the universal per-net parasitic.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass

from emc_assistant.netlist.fragment import series_pre_net


L_DAMP_CORNER_HZ: float = 200e6
"""Q-damping corner for every parasitic inductance (M2.10.8).

A parallel resistor ``Rd = 2*pi*L_DAMP_CORNER_HZ*L`` across each
parasitic L makes the branch behave as the inductor below this corner
and as a plain resistor above it. The corner sits well above the
conducted-EMI band (9 kHz - 30 MHz) so in-band results are preserved,
but it kills the undamped GHz LC tanks that the tiny pF/nH per-net
parasitics would otherwise form — those tanks force LTspice's adaptive
transient timestep down to picoseconds and blow the run up (a 6 s /
40 MB buck sim became a >120 s / 3.4 GB runaway before damping)."""


def damping_resistance_ohm(inductance_h: float) -> float:
    """Parallel Q-damping resistor for a parasitic inductance (M2.10.8)."""
    return 2.0 * math.pi * L_DAMP_CORNER_HZ * inductance_h


def _sanitise_net(net: str) -> str:
    """Net name reduced to ``[A-Za-z0-9_]`` for use in a SPICE refdes."""
    return re.sub(r"[^A-Za-z0-9_]", "_", net)


SUPPORTED_SUBCKTS: frozenset[str] = frozenset({"TRACE_RLC", "VIA_L", "CAP_ESR_ESL"})
"""Subcircuit names the composer knows how to emit. The composer rejects
unknown names rather than guessing port counts."""


_SUBCKT_PORT_COUNT: dict[str, tuple[int, int]] = {
    "TRACE_RLC": (3, 3),  # IN OUT 0
    "VIA_L": (2, 2),  # IN OUT
    "CAP_ESR_ESL": (2, 2),  # IN OUT
}


@dataclass
class ParasiticInjection:
    """One agent-proposed splice."""

    instance_name: str
    subckt_name: str
    nets: list[str]
    rationale: str
    rule_id: str = ""
    parasitic_id: str = ""
    corner: str = "typ"
    agent: str = "parasitics"

    def __post_init__(self) -> None:
        if not self.instance_name.startswith("X_"):
            raise ValueError(
                f"ParasiticInjection.instance_name must start with 'X_'; got {self.instance_name!r}"
            )
        if self.subckt_name not in SUPPORTED_SUBCKTS:
            raise ValueError(
                f"Unsupported subckt {self.subckt_name!r}; allowed: {sorted(SUPPORTED_SUBCKTS)}"
            )
        if self.corner not in {"min", "typ", "max"}:
            raise ValueError(f"corner must be min|typ|max; got {self.corner!r}")
        n_min, n_max = _SUBCKT_PORT_COUNT[self.subckt_name]
        if not (n_min <= len(self.nets) <= n_max):
            raise ValueError(
                f"{self.subckt_name} expects {n_min}..{n_max} nets; got {self.nets}"
            )

    def to_schema_dict(self) -> dict:
        out: dict = {
            "instance_name": self.instance_name,
            "subckt_name": self.subckt_name,
            "nets": list(self.nets),
            "rationale": self.rationale,
            "corner": self.corner,
            "agent": self.agent,
        }
        if self.rule_id:
            out["rule_id"] = self.rule_id
        if self.parasitic_id:
            out["parasitic_id"] = self.parasitic_id
        return out

    def to_spice_line(self) -> str:
        """Render the SPICE X-instance line."""
        return f"{self.instance_name} {' '.join(self.nets)} {self.subckt_name}"


@dataclass
class ShuntParasitic:
    """A per-net shunt parasitic capacitance to the return node (M2.10.5).

    Emitted by the composer as a bare ``C_par_<net>`` capacitor between
    ``net`` and ``return_net``. Unlike :class:`ParasiticInjection` it
    needs no clean cut point, so it applies to every user net regardless
    of fanout. Ground/return nets are never shunt targets and the
    parasitics agent filters them out before building the plan.
    """

    net: str
    capacitance_f: float
    return_net: str = "DUT_GND"
    rule_id: str = "engineering_estimate"
    source: str = "rule_of_thumb"  # rule_of_thumb | project_override
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.net:
            raise ValueError("ShuntParasitic.net must be non-empty")
        if self.capacitance_f <= 0:
            raise ValueError(
                f"ShuntParasitic.capacitance_f must be positive; got {self.capacitance_f!r}"
            )
        if self.source not in {"rule_of_thumb", "project_override"}:
            raise ValueError(
                f"source must be rule_of_thumb|project_override; got {self.source!r}"
            )

    def refdes(self) -> str:
        """SPICE refdes — ``C_par_`` + the net name sanitised to [A-Za-z0-9_]."""
        return f"C_par_{_sanitise_net(self.net)}"

    def to_spice_line(self) -> str:
        return f"{self.refdes()} {self.net} {self.return_net} {self.capacitance_f:.6g}"

    def to_schema_dict(self) -> dict:
        return {
            "net": self.net,
            "refdes": self.refdes(),
            "capacitance_f": self.capacitance_f,
            "return_net": self.return_net,
            "rule_id": self.rule_id,
            "source": self.source,
            "rationale": self.rationale,
        }


@dataclass
class SeriesParasitic:
    """A per-net series-parasitic splice on a clean 2-element net (M2.10.6).

    The fragment preprocessor renames the net to ``<net>__pre`` on one
    element (see :func:`emc_assistant.netlist.fragment.split_series_nets`).
    The composer then emits three bare elements — series R and L between
    ``<net>__pre`` and ``<net>``, and a shunt C from ``<net>`` to the
    return node:

        R_par_<net>  <net>__pre  n_par_<net>  <r>
        L_par_<net>  n_par_<net> <net>        <l>
        C_par_<net>  <net>       <return>     <c>

    This is the internal-net counterpart to the input-rail ``TRACE_RLC``
    injection; bare elements (not a subckt) keep per-net values literal
    and free of global-param collisions.
    """

    net: str
    resistance_ohm: float
    inductance_h: float
    capacitance_f: float
    return_net: str = "DUT_GND"
    rule_id: str = "engineering_estimate"
    source: str = "rule_of_thumb"  # rule_of_thumb | project_override
    rationale: str = ""

    def __post_init__(self) -> None:
        if not self.net:
            raise ValueError("SeriesParasitic.net must be non-empty")
        for label, val in (
            ("resistance_ohm", self.resistance_ohm),
            ("inductance_h", self.inductance_h),
            ("capacitance_f", self.capacitance_f),
        ):
            if val <= 0:
                raise ValueError(f"SeriesParasitic.{label} must be positive; got {val!r}")
        if self.source not in {"rule_of_thumb", "project_override"}:
            raise ValueError(
                f"source must be rule_of_thumb|project_override; got {self.source!r}"
            )

    def pre_net(self) -> str:
        """Cut-off side of the splice — must match the fragment rename."""
        return series_pre_net(self.net)

    def mid_net(self) -> str:
        """Internal node between the series R and L."""
        return f"n_par_{_sanitise_net(self.net)}"

    def damping_ohm(self) -> float:
        """Parallel Q-damping resistor across ``L_par`` (M2.10.8)."""
        return damping_resistance_ohm(self.inductance_h)

    def to_spice_lines(self) -> list[str]:
        s = _sanitise_net(self.net)
        return [
            f"R_par_{s} {self.pre_net()} {self.mid_net()} {self.resistance_ohm:.6g}",
            f"L_par_{s} {self.mid_net()} {self.net} {self.inductance_h:.6g}",
            f"Rd_par_{s} {self.mid_net()} {self.net} {self.damping_ohm():.6g}",
            f"C_par_{s} {self.net} {self.return_net} {self.capacitance_f:.6g}",
        ]

    def to_schema_dict(self) -> dict:
        return {
            "net": self.net,
            "pre_net": self.pre_net(),
            "resistance_ohm": self.resistance_ohm,
            "inductance_h": self.inductance_h,
            "damping_ohm": self.damping_ohm(),
            "capacitance_f": self.capacitance_f,
            "return_net": self.return_net,
            "rule_id": self.rule_id,
            "source": self.source,
            "rationale": self.rationale,
        }


def from_dict(data: dict) -> ParasiticInjection:
    """Build a :class:`ParasiticInjection` from a dict (e.g. parsed LLM JSON)."""
    return ParasiticInjection(
        instance_name=str(data["instance_name"]),
        subckt_name=str(data["subckt_name"]),
        nets=[str(n) for n in data["nets"]],
        rationale=str(data["rationale"]),
        rule_id=str(data.get("rule_id", "")),
        parasitic_id=str(data.get("parasitic_id", "")),
        corner=str(data.get("corner", "typ")),
        agent=str(data.get("agent", "parasitics")),
    )
