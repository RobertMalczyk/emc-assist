"""Tests for M2.10.6 per-net series-parasitic splicing.

Covers split_series_nets / write_user_fragment cutting, the
SeriesParasitic dataclass, the parasitics agent's default_series_plan,
and the composer emitting the series section.
"""

from __future__ import annotations

import pytest

from emc_assistant.agents.base import AgentInputs
from emc_assistant.agents.injection import SeriesParasitic
from emc_assistant.agents.parasitics_agent import ParasiticsAgent
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.netlist.fragment import (
    series_pre_net,
    split_series_nets,
    write_user_fragment,
)
from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import build_topology_report
from emc_assistant.testbench.composer import TestbenchPlan, compose_testbench_cir


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


# ---- split_series_nets -----------------------------------------------------


def test_split_renames_net_on_first_element_only():
    src = "* t\nVc c 0 5\nR1 c mid 1k\nR2 mid out 1k\n.end\n"
    text, did = split_series_nets(src, ["mid"])
    # `mid` is renamed on R1 (first element referencing it); R2 keeps `mid`.
    assert "R1 c mid__pre 1k" in text
    assert "R2 mid out 1k" in text
    assert did == ["mid"]


def test_split_uses_series_pre_net_convention():
    text, _ = split_series_nets("* t\nR1 a b 1k\nR2 b c 1k\n", ["b"])
    assert series_pre_net("b") in text


def test_split_skips_net_not_present():
    src = "* t\nR1 a b 1k\n.end\n"
    text, did = split_series_nets(src, ["nonexistent"])
    assert did == []
    assert "R1 a b 1k" in text


def test_split_multiple_nets():
    src = "* t\nR1 a b 1k\nR2 b c 1k\nR3 c d 1k\n.end\n"
    _, did = split_series_nets(src, ["b", "c"])
    assert set(did) == {"b", "c"}


def test_split_does_not_touch_comments_or_directives():
    src = "* keep b\n.model b D()\nR1 a b 1k\nR2 b c 1k\n"
    text, _ = split_series_nets(src, ["b"])
    assert "* keep b" in text
    assert ".model b D()" in text


def test_write_user_fragment_applies_series_split(tmp_path):
    src = tmp_path / "u.cir"
    src.write_text(_FRAGMENT, encoding="utf-8")
    dst = tmp_path / "frag.cir"
    write_user_fragment(src, dst, series_split_nets=["mid"])
    body = dst.read_text(encoding="utf-8")
    assert "R1 in mid__pre 1" in body
    assert "L1 mid out 1u" in body
    assert "Series-splice cuts" in body  # header note


# ---- SeriesParasitic -------------------------------------------------------


def test_series_parasitic_spice_lines():
    se = SeriesParasitic(
        net="sw_ctrl", resistance_ohm=2.7e-3, inductance_h=4.6e-9,
        capacitance_f=1.07e-12, return_net="DUT_GND",
    )
    lines = se.to_spice_lines()
    # R series, L series, Rd parallel-damping across L (M2.10.8), C shunt.
    assert lines[0].startswith("R_par_sw_ctrl sw_ctrl__pre n_par_sw_ctrl ")
    assert lines[1].startswith("L_par_sw_ctrl n_par_sw_ctrl sw_ctrl ")
    assert lines[2].startswith("Rd_par_sw_ctrl n_par_sw_ctrl sw_ctrl ")
    assert lines[3] == "C_par_sw_ctrl sw_ctrl DUT_GND 1.07e-12"
    assert se.pre_net() == "sw_ctrl__pre"
    # The damping resistor sits on the L_par node pair.
    assert se.damping_ohm() > 0


def test_series_parasitic_rejects_non_positive_values():
    with pytest.raises(ValueError):
        SeriesParasitic(net="x", resistance_ohm=0.0, inductance_h=1e-9,
                        capacitance_f=1e-12)


# ---- M2.10.8 Q-damping ------------------------------------------------------


def test_series_parasitic_damping_resistance():
    """The parallel damping R is 2*pi*corner*L (corner = L_DAMP_CORNER_HZ)."""
    from emc_assistant.agents.injection import (
        L_DAMP_CORNER_HZ,
        damping_resistance_ohm,
    )
    import math

    se = SeriesParasitic(net="g", resistance_ohm=3e-3, inductance_h=10e-9,
                         capacitance_f=1e-12)
    expected = 2.0 * math.pi * L_DAMP_CORNER_HZ * 10e-9
    assert se.damping_ohm() == pytest.approx(expected)
    assert damping_resistance_ohm(10e-9) == pytest.approx(expected)
    # The corner sits above the conducted-EMI band so in-band L is preserved.
    assert L_DAMP_CORNER_HZ > 30e6


def test_trace_rlc_fragment_carries_damping_resistor():
    """The composer's TRACE_RLC subckt also gets the parallel damping R."""
    from emc_assistant.parasitics.calculators import (
        trace_capacitance_from_z0_delay,
        trace_inductance_no_plane,
        trace_resistance,
    )
    from emc_assistant.testbench.fragments import trace_rlc_fragment

    frag = trace_rlc_fragment(
        r_est=trace_resistance(length_mm=20, width_mm=1),
        l_est=trace_inductance_no_plane(length_mm=20, width_mm=1),
        c_est=trace_capacitance_from_z0_delay(length_mm=20, z0_ohm=50,
                                              delay_ps_per_mm=6.7),
    )
    assert "Rd_par n_r OUT" in frag  # damping R parallel to L_par


# ---- default_series_plan ---------------------------------------------------


def test_series_plan_covers_injectable_two_element_nets():
    # `mid` (R1 + L1) is a clean 2-element net -> series splice.
    plan = ParasiticsAgent().default_series_plan(_inputs(), return_net="DUT_GND")
    assert "mid" in {s.net for s in plan}
    mid = next(s for s in plan if s.net == "mid")
    assert mid.resistance_ohm > 0 and mid.inductance_h > 0 and mid.capacitance_f > 0


def test_series_plan_excludes_supply_net():
    # `in` is a 2-element net too, but it is the supply -> excluded
    # (it receives the input-rail TRACE_RLC instead).
    plan = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND", exclude_nets=("in",)
    )
    assert "in" not in {s.net for s in plan}


def test_series_plan_skips_star_nets():
    # `out` touches L1 + Cout + Rload = 3 elements -> not injectable.
    plan = ParasiticsAgent().default_series_plan(_inputs(), return_net="DUT_GND")
    assert "out" not in {s.net for s in plan}


def test_series_plan_override_skip_and_value():
    plan = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND",
        overrides={"mid": {"c_pf": 33.0}},
    )
    mid = next(s for s in plan if s.net == "mid")
    assert mid.capacitance_f == pytest.approx(33e-12)
    assert mid.source == "project_override"

    skipped = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND", overrides={"mid": {"skip": True}}
    )
    assert "mid" not in {s.net for s in skipped}


def test_series_plan_override_r_mohm():
    """``r_mohm`` pins the series resistance in milliohm (display unit)."""
    plan = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND",
        overrides={"mid": {"r_mohm": 25.0}},
    )
    mid = next(s for s in plan if s.net == "mid")
    assert mid.resistance_ohm == pytest.approx(25e-3)
    assert mid.source == "project_override"


def test_series_plan_override_l_nh():
    """``l_nh`` pins the series inductance in nanohenry (display unit)."""
    plan = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND",
        overrides={"mid": {"l_nh": 12.5}},
    )
    mid = next(s for s in plan if s.net == "mid")
    assert mid.inductance_h == pytest.approx(12.5e-9)
    assert mid.source == "project_override"


def test_series_plan_override_combines_r_l_c():
    plan = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND",
        overrides={"mid": {"r_mohm": 30.0, "l_nh": 18.0, "c_pf": 22.0}},
    )
    mid = next(s for s in plan if s.net == "mid")
    assert mid.resistance_ohm == pytest.approx(30e-3)
    assert mid.inductance_h == pytest.approx(18e-9)
    assert mid.capacitance_f == pytest.approx(22e-12)
    assert mid.source == "project_override"


def test_series_plan_no_override_keeps_estimated_source():
    """Without an override, source stays ``rule_of_thumb`` — the override
    flag is per-net, not project-wide."""
    plan = ParasiticsAgent().default_series_plan(
        _inputs(), return_net="DUT_GND", overrides={},
    )
    mid = next(s for s in plan if s.net == "mid")
    assert mid.source == "rule_of_thumb"
    assert mid.rule_id == "engineering_estimate"


# ---- composer --------------------------------------------------------------


def test_composer_emits_series_section():
    plan = TestbenchPlan(
        title="t",
        parasitics=[],
        series_plan=[
            SeriesParasitic(net="sw_ctrl", resistance_ohm=3e-3,
                            inductance_h=5e-9, capacitance_f=1e-12),
        ],
    )
    cir = compose_testbench_cir(plan)
    assert "Per-net series parasitics" in cir
    assert "R_par_sw_ctrl sw_ctrl__pre n_par_sw_ctrl 0.003" in cir
    assert "L_par_sw_ctrl n_par_sw_ctrl sw_ctrl 5e-09" in cir
    assert "C_par_sw_ctrl sw_ctrl DUT_GND 1e-12" in cir


# ---- M2.10.8 --parasitics-report-only (CLI) --------------------------------


def test_parasitics_report_only_keeps_per_net_out_of_sim(tmp_path):
    """--parasitics-report-only estimates the per-net parasitics for the
    audit but keeps them out of the simulated testbench.cir."""
    import shutil
    from pathlib import Path
    from emc_assistant.cli import main

    example = Path(__file__).resolve().parents[1] / "examples" / "case_001_buck_conducted_emi"
    project = tmp_path / "case"
    shutil.copytree(example, project)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(project / sub, ignore_errors=True)

    rc = main([
        "testbench", "compose", str(project),
        "--accept-wiring", "--accept-parasitics", "--accept-signals",
        "--parasitics-report-only",
    ])
    assert rc == 0
    cir = (project / "generated" / "testbench.cir").read_text(encoding="utf-8")
    # Per-net series/shunt elements must NOT be in the simulated netlist...
    assert not any(line.startswith(("R_par_", "C_par_"))
                   for line in cir.splitlines())
    # ...but the per-net estimates are still written to the audit JSON.
    assert (project / "generated" / "parasitics_shunt.json").is_file()
