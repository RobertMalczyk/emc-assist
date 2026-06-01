"""Net-structure analysis on a parsed user fragment.

Used by the M2.10 parasitics agent to understand which nets carry power,
which is ground/return, and which look like switching nodes — without
running a SPICE simulation. Purely heuristic; the agent treats the
output as a hint, not as truth.

The returned :class:`TopologyReport` is small and JSON-serialisable so
it can land in ``generated/topology.json`` for audit and be passed into
agent prompts.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

from emc_assistant.netlist.parser import NetlistElement, ParsedNetlist, parse_cir


_GROUND_TOKENS: frozenset[str] = frozenset({"0", "gnd", "GND", "DUT_GND", "dut_gnd"})


NET_ROLES: tuple[str, ...] = ("return", "switching_node", "power_rail", "signal")
"""Net roles, used by the M2.10.4 per-net parasitic estimator to pick
rule-of-thumb trace geometry."""


@dataclass
class NetUsage:
    """How a net is used across the parsed elements."""

    name: str
    element_count: int = 0
    """Total elements referencing this net."""
    element_kinds: list[str] = field(default_factory=list)
    """First letters of element kinds touching this net (R/L/C/V/I/M/S/Q/D/X)."""
    components: list[str] = field(default_factory=list)
    """Reference designators of elements touching this net (e.g. R3, C7, L1).
    Lets a UI identify an opaque LTspice auto-name (N004) by what it wires."""
    is_v_source_positive: bool = False
    """True when the net is the positive terminal of any V source."""
    is_ground: bool = False
    """True when the net is one of the canonical ground tokens."""
    on_switch_element: bool = False
    """True when the net is wired to an S/Q/M element (likely a switching node)."""

    @property
    def role(self) -> str:
        """Coarse net role for parasitic estimation.

        ``return`` — a canonical ground net.
        ``switching_node`` — touches an S/Q/M element (fast dv/dt edge).
        ``power_rail`` — a V-source positive terminal, or a non-ground
        high-fanout net (>= 3 elements).
        ``signal`` — everything else (low-fanout interconnect).
        """
        if self.is_ground:
            return "return"
        if self.on_switch_element:
            return "switching_node"
        if self.is_v_source_positive or self.element_count >= 3:
            return "power_rail"
        return "signal"

    @property
    def is_two_element(self) -> bool:
        """True for a clean point-to-point net (exactly 2 elements).

        Only 2-element nets can take an unambiguous series parasitic
        splice; 3+-element star/bus nets need layout to place the
        injection point (M2.10.4 design note)."""
        return self.element_count == 2


@dataclass
class TopologyReport:
    """Summary of the user fragment's net structure.

    All fields are derived from the parsed `.cir` only; no SPICE
    simulation is involved. The report is meant to be cheap to compute
    and easy to forward to the parasitics agent.
    """

    title: str
    nets: list[NetUsage] = field(default_factory=list)
    power_supply_candidates: list[str] = field(default_factory=list)
    """Nets that look like a supply rail (V-source positive terminals,
    high fanout, not ground). Ordered most-likely first."""
    return_candidates: list[str] = field(default_factory=list)
    """Nets that look like the DUT return path. Includes the canonical
    ground tokens that appear in the netlist."""
    switching_node_candidates: list[str] = field(default_factory=list)
    """Nets attached to S/Q/M elements — possible switching nodes."""
    capacitor_terminals: list[tuple[str, str]] = field(default_factory=list)
    """Pairs (net_pos, net_neg) for every capacitor in the fragment."""
    element_count_by_kind: dict[str, int] = field(default_factory=dict)
    """Histogram of element kinds for quick orientation."""

    def to_schema_dict(self) -> dict:
        return {
            "title": self.title,
            "power_supply_candidates": list(self.power_supply_candidates),
            "return_candidates": list(self.return_candidates),
            "switching_node_candidates": list(self.switching_node_candidates),
            "capacitor_terminals": [
                {"pos": p, "neg": n} for p, n in self.capacitor_terminals
            ],
            "element_count_by_kind": dict(self.element_count_by_kind),
            "nets": [
                {
                    "name": nu.name,
                    "element_count": nu.element_count,
                    "element_kinds": list(nu.element_kinds),
                    "components": list(nu.components),
                    "is_v_source_positive": nu.is_v_source_positive,
                    "is_ground": nu.is_ground,
                    "on_switch_element": nu.on_switch_element,
                }
                for nu in self.nets
            ],
        }


_SWITCH_ELEMENT_KINDS: frozenset[str] = frozenset({"S", "Q", "M"})


def _classify_nets(elements: Iterable[NetlistElement]) -> dict[str, NetUsage]:
    usage: dict[str, NetUsage] = {}

    def _touch(net: str, kind: str, refdes: str) -> NetUsage:
        nu = usage.get(net)
        if nu is None:
            nu = NetUsage(name=net, is_ground=net in _GROUND_TOKENS)
            usage[net] = nu
        nu.element_count += 1
        if kind not in nu.element_kinds:
            nu.element_kinds.append(kind)
        if refdes and refdes not in nu.components:
            nu.components.append(refdes)
        if kind in _SWITCH_ELEMENT_KINDS:
            nu.on_switch_element = True
        return nu

    for el in elements:
        kind = el.kind.upper()
        for idx, net in enumerate(el.nodes):
            nu = _touch(net, kind, el.refdes)
            # First node of a V source is the positive terminal.
            if kind == "V" and idx == 0:
                nu.is_v_source_positive = True
    return usage


def build_topology_report(parsed: ParsedNetlist) -> TopologyReport:
    """Compute a :class:`TopologyReport` from a parsed netlist.

    Power-supply candidates ranked by:
    1. V-source positive terminals (always first),
    2. then non-ground nets by descending element_count.

    Return candidates: canonical ground tokens that appear, ordered by
    fanout descending. Switching-node candidates: nets on S/Q/M elements
    excluding canonical ground.
    """
    usage = _classify_nets(parsed.elements)

    v_positives = [nu.name for nu in usage.values() if nu.is_v_source_positive]
    other_nets = [
        nu
        for nu in usage.values()
        if not nu.is_v_source_positive and not nu.is_ground
    ]
    other_nets.sort(key=lambda n: (-n.element_count, n.name))

    power_supply_candidates: list[str] = []
    for n in v_positives:
        if n not in power_supply_candidates:
            power_supply_candidates.append(n)
    for n in other_nets:
        if n.name not in power_supply_candidates:
            power_supply_candidates.append(n.name)

    return_candidates = [
        nu.name for nu in usage.values() if nu.is_ground
    ]
    return_candidates.sort(key=lambda name: -usage[name].element_count)

    switching = [
        nu.name
        for nu in usage.values()
        if nu.on_switch_element and not nu.is_ground
    ]
    switching.sort(key=lambda name: -usage[name].element_count)

    cap_terminals: list[tuple[str, str]] = []
    for el in parsed.elements:
        if el.kind.upper() == "C" and len(el.nodes) >= 2:
            cap_terminals.append((el.nodes[0], el.nodes[1]))

    kind_hist: dict[str, int] = {}
    for el in parsed.elements:
        kind_hist[el.kind] = kind_hist.get(el.kind, 0) + 1

    nets_list = sorted(usage.values(), key=lambda n: (-n.element_count, n.name))
    return TopologyReport(
        title=parsed.title,
        nets=nets_list,
        power_supply_candidates=power_supply_candidates,
        return_candidates=return_candidates,
        switching_node_candidates=switching,
        capacitor_terminals=cap_terminals,
        element_count_by_kind=kind_hist,
    )


def analyse_fragment(path: Path) -> TopologyReport:
    """Read a `.cir` fragment from disk and build a topology report."""
    parsed = parse_cir(Path(path))
    return build_topology_report(parsed)
