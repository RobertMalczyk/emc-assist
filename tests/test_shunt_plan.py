"""Tests for M2.10.5 per-net shunt-parasitic injection.

Covers the ShuntParasitic dataclass, the parasitics agent's
default_shunt_plan (every non-ground net gets a shunt C, ground and
series-spliced nets excluded, project overrides applied), and the
composer emitting the shunt section into testbench.cir.
"""

from __future__ import annotations

import pytest

from emc_assistant.agents.base import AgentInputs
from emc_assistant.agents.injection import ShuntParasitic
from emc_assistant.agents.parasitics_agent import ParasiticsAgent
from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import build_topology_report
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.testbench.composer import TestbenchPlan, compose_testbench_cir


# A small DC/DC-ish fragment: `in` is the supply, `0` ground,
# `mid` a 2-element net, `out` a star net.
_FRAGMENT = (
    "* frag\n"
    "Vin in 0 DC 24\n"
    "R1 in mid 1\n"
    "L1 mid out 1u\n"
    "Cout out 0 10u\n"
    "Rload out 0 5\n"
    ".end\n"
)


def _inputs():
    topo = build_topology_report(parse_cir(_FRAGMENT))
    return AgentInputs(
        problem_context=ProblemContext(
            project_id="t", analysis_scope="conducted_emi",
            has_layout=False, has_stackup=False,
        ),
        topology=topo,
    )


# ---- ShuntParasitic dataclass ---------------------------------------------


def test_shunt_refdes_and_spice_line():
    sh = ShuntParasitic(net="n_lx", capacitance_f=2.5e-12, return_net="DUT_GND")
    assert sh.refdes() == "C_par_n_lx"
    assert sh.to_spice_line() == "C_par_n_lx n_lx DUT_GND 2.5e-12"


def test_shunt_refdes_sanitises_net_name():
    sh = ShuntParasitic(net="N002+", capacitance_f=1e-12)
    assert sh.refdes() == "C_par_N002_"


def test_shunt_rejects_non_positive_capacitance():
    with pytest.raises(ValueError):
        ShuntParasitic(net="x", capacitance_f=0.0)


def test_shunt_rejects_bad_source():
    with pytest.raises(ValueError):
        ShuntParasitic(net="x", capacitance_f=1e-12, source="guess")


# ---- default_shunt_plan ----------------------------------------------------


def test_shunt_plan_covers_every_non_ground_net():
    plan = ParasiticsAgent().default_shunt_plan(_inputs(), return_net="DUT_GND")
    nets = {s.net for s in plan}
    # in, mid, out get a shunt C; ground `0` never does.
    assert nets == {"in", "mid", "out"}
    assert "0" not in nets
    assert all(s.capacitance_f > 0 for s in plan)


def test_shunt_plan_excludes_series_spliced_net():
    """A net that already gets a series TRACE_RLC is not also shunted —
    the TRACE_RLC subckt carries its own shunt C."""
    plan = ParasiticsAgent().default_shunt_plan(
        _inputs(), return_net="DUT_GND", series_nets=("in",)
    )
    assert "in" not in {s.net for s in plan}
    assert {s.net for s in plan} == {"mid", "out"}


def test_shunt_plan_override_skip():
    plan = ParasiticsAgent().default_shunt_plan(
        _inputs(), return_net="DUT_GND", overrides={"mid": {"skip": True}}
    )
    assert "mid" not in {s.net for s in plan}


def test_shunt_plan_override_explicit_value():
    plan = ParasiticsAgent().default_shunt_plan(
        _inputs(), return_net="DUT_GND", overrides={"out": {"c_pf": 47.0}}
    )
    out = next(s for s in plan if s.net == "out")
    assert out.capacitance_f == pytest.approx(47e-12)
    assert out.source == "project_override"
    # A non-overridden net keeps the rule-of-thumb source.
    assert next(s for s in plan if s.net == "mid").source == "rule_of_thumb"


def test_shunt_plan_empty_without_topology():
    inp = AgentInputs(
        problem_context=ProblemContext(
            project_id="t", analysis_scope="conducted_emi",
            has_layout=False, has_stackup=False,
        ),
        topology=None,
    )
    assert ParasiticsAgent().default_shunt_plan(inp) == []


# ---- composer emits the shunt section -------------------------------------


def test_composer_emits_shunt_section():
    plan = TestbenchPlan(
        title="t",
        parasitics=[],
        shunt_plan=[
            ShuntParasitic(net="mid", capacitance_f=2e-12),
            ShuntParasitic(net="out", capacitance_f=4e-12, source="project_override"),
        ],
    )
    cir = compose_testbench_cir(plan)
    assert "Per-net shunt parasitics" in cir
    assert "C_par_mid mid DUT_GND 2e-12" in cir
    assert "C_par_out out DUT_GND 4e-12" in cir
    # The header counts the project-override entry.
    assert "1 from project override" in cir


def test_composer_no_shunt_section_when_plan_empty():
    cir = compose_testbench_cir(TestbenchPlan(title="t", parasitics=[]))
    assert "Per-net shunt parasitics" not in cir
