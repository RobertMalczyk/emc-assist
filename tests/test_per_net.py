"""Tests for M2.10.4 per-net parasitic estimation.

Covers:
- net-role classification on the buck demo + synthetic netlists,
- the S/Q/J parser extension (switching node is now parsed),
- RuleOfThumbValueSource produces role-tuned bands,
- estimate_all_nets covers every net + flags 2-element nets injectable,
- ground/return nets are estimated but never injectable,
- the ParasiticValueSource ABC is swappable.
"""

from __future__ import annotations

from pathlib import Path

from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import analyse_fragment, build_topology_report
from emc_assistant.parasitics.per_net import (
    DEFAULT_ROLE_GEOMETRY,
    NetRLC,
    ParasiticValueSource,
    RuleOfThumbValueSource,
    TraceGeometry,
    estimate_all_nets,
)


REPO_ROOT = Path(__file__).resolve().parents[1]
BUCK_DEMO = REPO_ROOT / "examples" / "case_001_buck_conducted_emi" / "input" / "buck_demo.cir"


# ---- net-role classification ----------------------------------------------


def test_net_roles_on_buck_demo():
    report = analyse_fragment(BUCK_DEMO)
    roles = {nu.name: nu.role for nu in report.nets}
    # Ground is a return net.
    assert roles["0"] == "return"
    # The buck's S1 switch makes n_in / n_lx / sw_ctrl switching nodes
    # (the S-element parser extension makes this work).
    assert roles["n_lx"] == "switching_node"
    assert roles["n_in"] == "switching_node"
    # n_bulk / out are high-fanout non-ground -> power_rail.
    assert roles["n_bulk"] == "power_rail"
    assert roles["out"] == "power_rail"


def test_parser_extension_parses_s_element():
    """The S (voltage-controlled switch) element must now be parsed —
    without it the converter's switching node is invisible."""
    src = "* t\nVc c 0 5\nS1 a b c 0 SWMOD\n.model SWMOD SW()\n"
    parsed = parse_cir(src)
    s_elements = parsed.elements_by_kind("S")
    assert len(s_elements) == 1
    assert s_elements[0].nodes == ["a", "b", "c", "0"]


def test_two_element_net_flag():
    src = "* t\nR1 a b 1k\nR2 b c 1k\nR3 c d 1k\nR4 c e 1k\n"
    report = build_topology_report(parse_cir(src))
    by_name = {nu.name: nu for nu in report.nets}
    # `b` touches R1 + R2 = 2 elements -> point-to-point.
    assert by_name["b"].is_two_element is True
    # `c` touches R2 + R3 + R4 = 3 elements -> star.
    assert by_name["c"].is_two_element is False


# ---- RuleOfThumbValueSource -----------------------------------------------


def test_rule_of_thumb_source_returns_rlc_for_each_role():
    src = RuleOfThumbValueSource()
    for role in ("power_rail", "switching_node", "return", "signal"):
        rlc = src.estimate(net_name="n1", role=role)
        assert isinstance(rlc, NetRLC)
        assert rlc.resistance.value > 0
        assert rlc.inductance.value > 0
        assert rlc.capacitance.value > 0


def test_rule_of_thumb_switching_node_is_shorter_than_power_rail():
    """Role-tuned geometry: a switching node defaults to a short trace,
    so its inductance must be lower than a power rail's."""
    src = RuleOfThumbValueSource()
    sw = src.estimate(net_name="sw", role="switching_node")
    rail = src.estimate(net_name="rail", role="power_rail")
    assert sw.inductance.value < rail.inductance.value


def test_rule_of_thumb_unknown_role_falls_back_to_signal():
    src = RuleOfThumbValueSource()
    unknown = src.estimate(net_name="x", role="not_a_role")
    signal = src.estimate(net_name="x", role="signal")
    assert unknown.resistance.value == signal.resistance.value


def test_rule_of_thumb_geometry_override():
    custom = {"power_rail": TraceGeometry(length_mm=100.0, width_mm=1.0)}
    src = RuleOfThumbValueSource(role_geometry=custom)
    overridden = src.estimate(net_name="r", role="power_rail")
    default = RuleOfThumbValueSource().estimate(net_name="r", role="power_rail")
    # A 100 mm trace has more resistance than the 30 mm default.
    assert overridden.resistance.value > default.resistance.value


def test_net_rlc_cites_calculator_sources():
    rlc = RuleOfThumbValueSource().estimate(net_name="n", role="power_rail")
    sources = rlc.cited_sources()
    # The trace calculators cite R001 (R), R002 (L), R004/R005 (C).
    assert "R001" in sources
    assert "R002" in sources


# ---- estimate_all_nets ----------------------------------------------------


def test_estimate_all_nets_covers_every_net():
    report = analyse_fragment(BUCK_DEMO)
    estimates = estimate_all_nets(report)
    assert len(estimates) == len(report.nets)
    est_names = {e.net for e in estimates}
    topo_names = {nu.name for nu in report.nets}
    assert est_names == topo_names


def test_estimate_all_nets_ground_estimated_but_not_injectable():
    report = analyse_fragment(BUCK_DEMO)
    estimates = {e.net: e for e in estimate_all_nets(report)}
    gnd = estimates["0"]
    # The return net is still estimated (ground bounce is real)...
    assert gnd.rlc.resistance.value > 0
    # ...but never injectable.
    assert gnd.injectable is False
    assert any("never injected" in n.lower() for n in gnd.notes)


def test_estimate_all_nets_marks_two_element_nets_injectable():
    src = "* t\nVin a 0 5\nR1 a b 1k\nR2 b 0 1k\n"
    report = build_topology_report(parse_cir(src))
    estimates = {e.net: e for e in estimate_all_nets(report)}
    # `b` is a clean 2-element net (R1 + R2), non-ground -> injectable.
    assert estimates["b"].injectable is True
    # Ground never injectable even if 2-element.
    assert estimates["0"].injectable is False


def test_estimate_all_nets_serialises_to_dict():
    report = analyse_fragment(BUCK_DEMO)
    for est in estimate_all_nets(report):
        d = est.to_dict()
        assert d["net"] and d["role"]
        assert d["r_typ_ohm"] > 0 and d["l_typ_h"] > 0 and d["c_typ_f"] > 0
        assert len(d["r_band"]) == 2 and len(d["l_band"]) == 2
        assert isinstance(d["injectable"], bool)
        # Connectivity surfaced so a UI can name opaque LTspice auto-nets.
        assert "components" in d and isinstance(d["components"], list)
        assert len(d["components"]) == report_net_count(report, d["net"])


def report_net_count(report, net_name):
    return next(nu.element_count for nu in report.nets if nu.name == net_name)


# ---- pluggable value source -----------------------------------------------


def test_value_source_abc_is_swappable():
    """A custom ParasiticValueSource implementation plugs in unchanged —
    this is the seam for a future look-up table / project-KB source."""

    class FixedSource(ParasiticValueSource):
        name = "fixed_test"

        def estimate(self, *, net_name: str, role: str) -> NetRLC:
            return RuleOfThumbValueSource().estimate(net_name=net_name, role="signal")

    report = analyse_fragment(BUCK_DEMO)
    estimates = estimate_all_nets(report, value_source=FixedSource())
    assert all(e.value_source == "fixed_test" for e in estimates)
    # Every net got the 'signal'-role estimate regardless of its real role.
    signal_r = RuleOfThumbValueSource().estimate(net_name="x", role="signal").resistance.value
    assert all(e.rlc.resistance.value == signal_r for e in estimates)


def test_default_role_geometry_has_all_four_roles():
    assert set(DEFAULT_ROLE_GEOMETRY) == {"power_rail", "switching_node", "return", "signal"}
