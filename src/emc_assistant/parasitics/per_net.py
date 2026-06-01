"""Per-net parasitic estimation (M2.10.4).

Walks every net in a :class:`~emc_assistant.netlist.topology.TopologyReport`
and assigns each one a rule-of-thumb R / L / C parasitic band. This is
the "estimate every net" half of the parasitics-agent workflow — the
paper (S031) extracts RLCG per net from a 3D model; without layout we
substitute role-tuned rule-of-thumb geometry.

**Extensibility is the point.** The value source is pluggable via the
:class:`ParasiticValueSource` ABC. Today the only implementation is
:class:`RuleOfThumbValueSource` (role-tuned default geometry → the
deterministic trace calculators). The interface is shaped so a future
``LookupTableValueSource`` (a parasitics look-up table keyed by
net role / trace class) or ``ProjectKbValueSource`` (per-project
extracted values pulled from the RAG knowledge base) drops in without
touching the agent or the report.

A net is *injectable* only when it is a clean 2-element point-to-point
trace — a series parasitic splice on a 3+-element star/bus needs layout
to place the cut, so those nets are estimated but not injected.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from emc_assistant.netlist.topology import TopologyReport
from emc_assistant.parasitics.calculators import (
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
)
from emc_assistant.parasitics.model import ParasiticEstimate


@dataclass(frozen=True)
class TraceGeometry:
    """Rule-of-thumb trace geometry for a net role."""

    length_mm: float
    width_mm: float
    copper_oz: float = 1.0
    z0_ohm: float = 50.0
    delay_ps_per_mm: float = 6.7


# Rule-of-thumb geometry per net role. These are deliberately coarse
# first-pass defaults — a power rail is assumed wider and longer than a
# signal trace, a switching node is kept short, a return is wide. The
# user can override per project later; layout extraction (M7) replaces
# them outright.
DEFAULT_ROLE_GEOMETRY: dict[str, TraceGeometry] = {
    "power_rail": TraceGeometry(length_mm=30.0, width_mm=2.0),
    "switching_node": TraceGeometry(length_mm=8.0, width_mm=1.5),
    "return": TraceGeometry(length_mm=25.0, width_mm=3.0),
    "signal": TraceGeometry(length_mm=20.0, width_mm=0.5),
}


@dataclass
class NetRLC:
    """The R / L / C parasitic estimates for a single net."""

    resistance: ParasiticEstimate
    inductance: ParasiticEstimate
    capacitance: ParasiticEstimate

    def cited_sources(self) -> list[str]:
        seen: list[str] = []
        for est in (self.resistance, self.inductance, self.capacitance):
            for sid in est.source_ids:
                if sid not in seen:
                    seen.append(sid)
        return seen


@dataclass
class NetParasitics:
    """Per-net parasitic estimate + role + injectability."""

    net: str
    role: str
    rlc: NetRLC
    injectable: bool
    value_source: str = "rule_of_thumb"
    components: list[str] = field(default_factory=list)
    """Reference designators wired to this net — surfaced so a UI can
    identify an opaque LTspice auto-name (e.g. N004) by what it connects."""
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        r, l, c = self.rlc.resistance, self.rlc.inductance, self.rlc.capacitance
        return {
            "net": self.net,
            "role": self.role,
            "injectable": self.injectable,
            "value_source": self.value_source,
            "components": list(self.components),
            "r_typ_ohm": r.value,
            "l_typ_h": l.value,
            "c_typ_f": c.value,
            "r_band": [r.min_value, r.max_value],
            "l_band": [l.min_value, l.max_value],
            "c_band": [c.min_value, c.max_value],
            "cited_sources": self.rlc.cited_sources(),
            "notes": list(self.notes),
        }


class ParasiticValueSource(ABC):
    """Produces a :class:`NetRLC` for a net. Pluggable.

    The current implementation is :class:`RuleOfThumbValueSource`.
    Future sources (look-up tables, per-project extracted values from
    the RAG knowledge base, or real 3D-extracted RLCG) implement the
    same interface and slot in unchanged.
    """

    name: str = "abstract"

    @abstractmethod
    def estimate(self, *, net_name: str, role: str) -> NetRLC:
        """Return the R / L / C parasitic estimates for one net."""


class RuleOfThumbValueSource(ParasiticValueSource):
    """Role-tuned default geometry → the deterministic trace calculators.

    No layout, no measurement — every estimate is an
    ``engineering_estimate``. ``role_geometry`` can be overridden (e.g.
    from ``user_context``) without subclassing.
    """

    name = "rule_of_thumb"

    def __init__(self, role_geometry: dict[str, TraceGeometry] | None = None) -> None:
        self.role_geometry = dict(DEFAULT_ROLE_GEOMETRY)
        if role_geometry:
            self.role_geometry.update(role_geometry)

    def estimate(self, *, net_name: str, role: str) -> NetRLC:
        geom = self.role_geometry.get(role) or self.role_geometry["signal"]
        r = trace_resistance(length_mm=geom.length_mm, width_mm=geom.width_mm,
                             copper_oz=geom.copper_oz)
        l = trace_inductance_no_plane(length_mm=geom.length_mm, width_mm=geom.width_mm,
                                      copper_oz=geom.copper_oz)
        c = trace_capacitance_from_z0_delay(length_mm=geom.length_mm, z0_ohm=geom.z0_ohm,
                                            delay_ps_per_mm=geom.delay_ps_per_mm)
        return NetRLC(resistance=r, inductance=l, capacitance=c)


def estimate_all_nets(
    topology: TopologyReport,
    *,
    value_source: ParasiticValueSource | None = None,
) -> list[NetParasitics]:
    """Estimate parasitics for every net in the topology report.

    Ground/return nets are estimated too (the return path has its own
    parasitics — ground bounce) but are never marked ``injectable`` — a
    series splice into the global reference node would break the
    circuit. Only clean 2-element non-ground nets are injectable.
    """
    source = value_source or RuleOfThumbValueSource()
    out: list[NetParasitics] = []
    for nu in topology.nets:
        rlc = source.estimate(net_name=nu.name, role=nu.role)
        injectable = nu.is_two_element and not nu.is_ground
        notes: list[str] = []
        if nu.is_ground:
            notes.append("Return/reference net — estimated, never injected.")
        elif not nu.is_two_element:
            notes.append(
                f"{nu.element_count}-element star/bus — splice point is "
                "layout-dependent; estimated but not injected."
            )
        out.append(
            NetParasitics(
                net=nu.name,
                role=nu.role,
                rlc=rlc,
                injectable=injectable,
                value_source=source.name,
                components=list(nu.components),
                notes=notes,
            )
        )
    return out
