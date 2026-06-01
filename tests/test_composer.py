"""Tests for the testbench.cir composer."""

from __future__ import annotations

from pathlib import Path

from emc_assistant.parasitics.calculators import (
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
    via_inductance,
)
from emc_assistant.testbench.composer import (
    TestbenchPlan,
    TestbenchWiring,
    compose_testbench_cir,
)
from emc_assistant.testbench.generators import CableSpec, LisnSpec


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CIR = (
    REPO_ROOT
    / "examples"
    / "case_001_buck_conducted_emi"
    / "input"
    / "placeholder_original.cir"
)


def _parasitics():
    return [
        trace_resistance(length_mm=10.0, width_mm=0.5),
        trace_inductance_no_plane(length_mm=10.0, width_mm=0.5),
        trace_capacitance_from_z0_delay(length_mm=10.0, z0_ohm=50.0, delay_ps_per_mm=6.7),
        via_inductance(height_mm=1.6, drill_diameter_mm=0.3),
    ]


def test_composer_emits_full_structure():
    plan = TestbenchPlan(
        title="Composer test",
        parasitics=_parasitics(),
        user_netlist=EXAMPLE_CIR,
        lisn=LisnSpec(),
        cable=CableSpec(length_m=1.0),
    )
    cir = compose_testbench_cir(plan)
    assert cir.startswith("* Composer test")
    assert ".include" in cir
    assert ".SUBCKT LISN50UH" in cir
    assert ".SUBCKT CABLE_PWR" in cir
    assert ".SUBCKT TRACE_RLC" in cir
    assert ".SUBCKT VIA_L" in cir
    assert ".step param sweep_corner list 0 1 2" in cir
    assert ".end" in cir
    assert cir.strip().endswith(".end")


def test_composer_handles_missing_user_netlist(tmp_path: Path):
    plan = TestbenchPlan(
        title="No user file",
        parasitics=_parasitics(),
        user_netlist=tmp_path / "does_not_exist.cir",
    )
    cir = compose_testbench_cir(plan)
    assert "No user netlist included" in cir
    assert ".include" not in cir


def test_composer_can_disable_sweep():
    plan = TestbenchPlan(
        title="No sweep",
        parasitics=_parasitics(),
        user_netlist=None,
        sweep_corners=False,
    )
    cir = compose_testbench_cir(plan)
    assert "sweep_corner" not in cir
    assert ".tran" in cir


def test_composer_capacitors_appear():
    plan = TestbenchPlan(
        title="With caps",
        parasitics=_parasitics(),
        capacitors=[
            {"name": "CIN_MODEL", "capacitance_f": 10e-6, "esr_ohm": 20e-3, "esl_h": 2e-9},
        ],
    )
    cir = compose_testbench_cir(plan)
    assert ".SUBCKT CIN_MODEL IN OUT" in cir


def test_composer_emits_default_meas_directives():
    plan = TestbenchPlan(title="meas defaults", parasitics=_parasitics())
    cir = compose_testbench_cir(plan)
    # Defaults cover V(MEAS) — the LISN probe port (or its dual-LISN alias).
    assert ".meas TRAN vpeak MAX V(MEAS)" in cir
    assert ".meas TRAN vmin MIN V(MEAS)" in cir
    assert ".meas TRAN vp2p PP V(MEAS)" in cir
    assert ".meas TRAN vrms RMS V(MEAS)" in cir
    # DM probe directives (Phase A).
    assert ".meas TRAN dm_peak MAX V(DM)" in cir
    assert ".meas TRAN dm_p2p PP V(DM)" in cir
    assert ".meas TRAN dm_rms RMS V(DM)" in cir
    # CM probe directives (M2.8.3 — meaningful only in dual-LISN mode, but
    # the keys are emitted unconditionally for schema stability).
    assert ".meas TRAN cm_peak MAX V(CM)" in cir
    assert ".meas TRAN cm_p2p PP V(CM)" in cir
    assert ".meas TRAN cm_rms RMS V(CM)" in cir
    # .meas must appear after .tran and before .end.
    cir_lines = cir.splitlines()
    tran_idx = next(i for i, ln in enumerate(cir_lines) if ln.startswith(".tran"))
    end_idx = next(i for i, ln in enumerate(cir_lines) if ln.strip() == ".end")
    meas_idx = next(i for i, ln in enumerate(cir_lines) if ln.startswith(".meas"))
    assert tran_idx < meas_idx < end_idx


def test_composer_emits_dm_b_source_when_lisn_present():
    plan = TestbenchPlan(title="dm probe", parasitics=_parasitics())
    cir = compose_testbench_cir(plan)
    # Phase A: explicit B-source for DM, derived from V(MEAS).
    assert "B_DM DM 0 V=V(MEAS)" in cir


def test_composer_omits_dm_probe_when_lisn_disabled():
    plan = TestbenchPlan(title="no lisn", parasitics=_parasitics(), lisn=None)
    cir = compose_testbench_cir(plan)
    assert "B_DM" not in cir


def test_composer_allows_overriding_meas_directives():
    custom = [".meas TRAN imax MAX I(R_meas)"]
    plan = TestbenchPlan(
        title="custom meas", parasitics=_parasitics(), meas_directives=custom
    )
    cir = compose_testbench_cir(plan)
    assert ".meas TRAN imax MAX I(R_meas)" in cir
    # Defaults must NOT be present when overridden.
    assert ".meas TRAN vpeak MAX V(MEAS)" not in cir


def test_composer_meas_can_be_disabled():
    plan = TestbenchPlan(
        title="no meas", parasitics=_parasitics(), meas_directives=[]
    )
    cir = compose_testbench_cir(plan)
    assert ".meas" not in cir


def test_composer_emits_dual_lisn_wiring_by_default():
    """Default lisn_mode is "dual" (CISPR-style for low-voltage DC)."""
    wiring = TestbenchWiring(
        external_supply_v=12.0,
        dut_supply_net="n_vin",
        dut_return_net="0",
    )
    plan = TestbenchPlan(
        title="wired",
        parasitics=_parasitics(),
        wiring=wiring,
    )
    cir = compose_testbench_cir(plan)
    assert "V_RAIL HV_IN_RAIL 0 DC 12.0" in cir
    # Dual-LISN topology: positive rail LISN, return rail LISN, cable to DUT_GND
    assert "X_LISN_P HV_IN_RAIL HV_DUT_P MEAS_P 0 LISN50UH" in cir
    assert "X_LISN_N 0 DUT_GND MEAS_N 0 LISN50UH" in cir
    assert "X_CABLE HV_DUT_P n_vin DUT_GND CABLE_PWR" in cir
    # DM = MEAS_P - MEAS_N, CM = (MEAS_P + MEAS_N)/2, MEAS aliases MEAS_P
    assert "B_DM DM 0 V=V(MEAS_P)-V(MEAS_N)" in cir
    assert "B_CM CM 0 V=(V(MEAS_P)+V(MEAS_N))/2" in cir
    assert "B_MEAS MEAS 0 V=V(MEAS_P)" in cir


def test_composer_emits_single_lisn_wiring_when_requested():
    """lisn_mode='single' preserves legacy M2.6.1 / M2.7 behaviour."""
    wiring = TestbenchWiring(
        external_supply_v=12.0,
        dut_supply_net="n_vin",
        dut_return_net="0",
        lisn_mode="single",
    )
    plan = TestbenchPlan(
        title="wired single",
        parasitics=_parasitics(),
        wiring=wiring,
    )
    cir = compose_testbench_cir(plan)
    assert "X_LISN HV_IN_RAIL HV_DUT MEAS 0 LISN50UH" in cir
    assert "X_CABLE HV_DUT n_vin 0 CABLE_PWR" in cir
    # Single-LISN probes: DM tracks MEAS, CM is the placeholder half-value
    assert "B_DM DM 0 V=V(MEAS)" in cir
    assert "B_CM CM 0 V=V(MEAS)/2" in cir
    # Dual-LISN markers must NOT be present
    assert "X_LISN_P" not in cir
    assert "X_LISN_N" not in cir
    assert "DUT_GND" not in cir


def test_composer_omits_wiring_when_none():
    plan = TestbenchPlan(title="no wiring", parasitics=_parasitics(), wiring=None)
    cir = compose_testbench_cir(plan)
    assert "X_LISN" not in cir
    assert "V_RAIL" not in cir
    assert "X_CABLE" not in cir


def test_composer_emits_absolute_include_path(tmp_path: Path):
    # LTspice resolves `.include` relative to the .cir file location, not CWD.
    # Emitting an absolute path keeps the include working regardless of where
    # the netlist is invoked from.
    fragment = tmp_path / "user_circuit_fragment.cir"
    fragment.write_text("* dummy user fragment\n", encoding="utf-8")
    plan = TestbenchPlan(
        title="abs include",
        parasitics=_parasitics(),
        user_netlist=fragment,
    )
    cir = compose_testbench_cir(plan)
    include_line = next(ln for ln in cir.splitlines() if ln.startswith(".include"))
    include_path = Path(include_line.removeprefix(".include").strip())
    assert include_path.is_absolute(), include_line
    assert include_path.resolve() == fragment.resolve()
