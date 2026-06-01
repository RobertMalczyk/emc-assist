"""Tests for the M2.10 parasitic-injection contract.

Covers:

- ``ParasiticInjection.__post_init__`` validation (instance prefix, port count, corner),
- schema validation against ``parasitic_injection.schema.json``,
- the composer renders X-instances given a plan and reroutes the cable to ``n_dut_in_pre``,
- the composer falls back to M2.6.1 wiring when the plan is empty,
- the parasitics agent's deterministic ``_default_injection_plan`` emits a sane plan.
"""

from __future__ import annotations

import pytest

from emc_assistant.agents.base import AgentInputs
from emc_assistant.agents.injection import ParasiticInjection, from_dict
from emc_assistant.agents.parasitics_agent import CABLE_OUT_NET, ParasiticsAgent
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.netlist.topology import TopologyReport
from emc_assistant.parasitics.calculators import (
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)
from emc_assistant.schemas import require_valid
from emc_assistant.testbench.composer import (
    CABLE_OUT_PRE_NET,
    TestbenchPlan,
    TestbenchWiring,
    compose_testbench_cir,
)


def _parasitics_buck_like() -> list:
    return [
        trace_resistance(length_mm=20.0, width_mm=1.0),
        trace_inductance_no_plane(length_mm=20.0, width_mm=1.0),
        trace_capacitance_from_z0_delay(length_mm=20.0, z0_ohm=50.0, delay_ps_per_mm=6.7),
        via_inductance(height_mm=1.6, drill_diameter_mm=0.3),
    ]


# ----- ParasiticInjection dataclass validation -----


def test_injection_requires_X_prefix():
    with pytest.raises(ValueError):
        ParasiticInjection(
            instance_name="TRACE_VIN",  # missing X_
            subckt_name="TRACE_RLC",
            nets=["a", "b", "c"],
            rationale="x",
        )


def test_injection_rejects_unknown_subckt():
    with pytest.raises(ValueError):
        ParasiticInjection(
            instance_name="X_FOO",
            subckt_name="UNKNOWN_SUBCKT",
            nets=["a", "b"],
            rationale="x",
        )


def test_injection_validates_port_count():
    # TRACE_RLC needs 3 nets
    with pytest.raises(ValueError):
        ParasiticInjection(
            instance_name="X_TRACE",
            subckt_name="TRACE_RLC",
            nets=["a", "b"],  # only 2
            rationale="x",
        )
    # VIA_L needs 2 nets
    with pytest.raises(ValueError):
        ParasiticInjection(
            instance_name="X_VIA",
            subckt_name="VIA_L",
            nets=["a", "b", "c"],  # 3 is too many
            rationale="x",
        )


def test_injection_corner_must_be_min_typ_max():
    with pytest.raises(ValueError):
        ParasiticInjection(
            instance_name="X_TRACE",
            subckt_name="TRACE_RLC",
            nets=["a", "b", "c"],
            rationale="x",
            corner="nominal",
        )


def test_injection_to_spice_line():
    inj = ParasiticInjection(
        instance_name="X_TRACE_VIN",
        subckt_name="TRACE_RLC",
        nets=["n_dut_in_pre", "in", "DUT_GND"],
        rationale="x",
    )
    assert inj.to_spice_line() == "X_TRACE_VIN n_dut_in_pre in DUT_GND TRACE_RLC"


# ----- Schema validation -----


def test_injection_schema_validates_minimal_entry():
    data = {
        "instance_name": "X_TRACE_VIN",
        "subckt_name": "TRACE_RLC",
        "nets": ["n_dut_in_pre", "in", "DUT_GND"],
        "rationale": "trace L between cable and DUT input",
    }
    require_valid("parasitic_injection.schema.json", data)


def test_injection_from_dict_round_trip():
    data = {
        "instance_name": "X_VIA_RTN",
        "subckt_name": "VIA_L",
        "nets": ["n1", "n2"],
        "rationale": "return-via inductance",
        "corner": "max",
        "rule_id": "R-010",
        "parasitic_id": "par-via-L",
    }
    inj = from_dict(data)
    out = inj.to_schema_dict()
    assert out["instance_name"] == "X_VIA_RTN"
    assert out["corner"] == "max"
    assert out["rule_id"] == "R-010"


# ----- Composer renders injection plan -----


def test_composer_renders_injection_plan_and_reroutes_cable():
    inj = ParasiticInjection(
        instance_name="X_TRACE_VIN",
        subckt_name="TRACE_RLC",
        nets=[CABLE_OUT_PRE_NET, "in", "DUT_GND"],
        rationale="series trace L between cable and DUT supply",
        parasitic_id="par-trace-L",
    )
    plan = TestbenchPlan(
        title="composer M2.10 test",
        parasitics=_parasitics_buck_like(),
        wiring=TestbenchWiring(
            external_supply_v=24.0, dut_supply_net="in", dut_return_net="0"
        ),
        injection_plan=[inj],
    )
    cir = compose_testbench_cir(plan)
    # Cable lands on the intermediate net, not directly on "in"
    assert f"X_CABLE HV_DUT_P {CABLE_OUT_PRE_NET} DUT_GND CABLE_PWR" in cir
    # X-instance is rendered
    assert "X_TRACE_VIN n_dut_in_pre in DUT_GND TRACE_RLC" in cir
    # Comments include rationale + parasitic id
    assert "* injection: X_TRACE_VIN" in cir
    assert "par-trace-L" in cir


def test_composer_preserves_m261_wiring_when_plan_is_empty():
    plan = TestbenchPlan(
        title="composer M2.6.1 test",
        parasitics=_parasitics_buck_like(),
        wiring=TestbenchWiring(
            external_supply_v=24.0, dut_supply_net="in", dut_return_net="0"
        ),
        # empty injection_plan
    )
    cir = compose_testbench_cir(plan)
    # Cable lands directly on the user supply net (M2.6.1 behaviour)
    assert "X_CABLE HV_DUT_P in DUT_GND CABLE_PWR" in cir
    # No injection block emitted
    assert "Parasitic injection plan" not in cir
    assert CABLE_OUT_PRE_NET not in cir


# ----- ParasiticsAgent deterministic plan -----


def _problem_ctx() -> ProblemContext:
    return ProblemContext(
        project_id="t",
        analysis_scope="conducted_emi",
        has_layout=False,
        has_stackup=False,
    )


def test_parasitics_agent_deterministic_plan_emits_one_injection():
    agent = ParasiticsAgent()
    topology = TopologyReport(
        title="t",
        nets=[],
        power_supply_candidates=["in"],
        return_candidates=["0"],
    )
    inputs = AgentInputs(
        problem_context=_problem_ctx(),
        parasitics=_parasitics_buck_like(),
        topology=topology,
        dut_supply_net="in",
        dut_return_net="DUT_GND",
    )
    plan = agent._default_injection_plan(inputs)
    assert len(plan) == 1
    inj = plan[0]
    assert inj.subckt_name == "TRACE_RLC"
    assert inj.nets[0] == CABLE_OUT_NET
    assert inj.nets[1] == "in"
    assert inj.nets[2] == "DUT_GND"
    # Schema-valid
    require_valid("parasitic_injection.schema.json", inj.to_schema_dict())


def test_parasitics_agent_no_plan_when_no_supply_net_or_topology():
    agent = ParasiticsAgent()
    inputs = AgentInputs(
        problem_context=_problem_ctx(),
        parasitics=_parasitics_buck_like(),
        # no topology, no dut_supply_net
    )
    plan = agent._default_injection_plan(inputs)
    assert plan == []


def test_parasitics_agent_no_plan_when_no_trace_l_estimate():
    agent = ParasiticsAgent()
    inputs = AgentInputs(
        problem_context=_problem_ctx(),
        parasitics=[trace_resistance(length_mm=20.0, width_mm=1.0)],
        dut_supply_net="in",
    )
    plan = agent._default_injection_plan(inputs)
    assert plan == []


def test_parasitics_agent_finding_includes_injections_field():
    agent = ParasiticsAgent()
    topology = TopologyReport(
        title="t",
        nets=[],
        power_supply_candidates=["in"],
        return_candidates=["0"],
    )
    inputs = AgentInputs(
        problem_context=_problem_ctx(),
        parasitics=_parasitics_buck_like(),
        topology=topology,
        dut_supply_net="in",
        dut_return_net="DUT_GND",
    )
    finding = agent.deterministic_finding(inputs)
    assert len(finding.injections) == 1
    # AgentFinding schema-valid
    require_valid("agent_finding.schema.json", finding.to_schema_dict())
