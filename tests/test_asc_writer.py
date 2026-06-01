"""Tests for the M2.10.3 LTspice .asc visualisation emitter."""

from __future__ import annotations

from pathlib import Path

import pytest

from emc_assistant.agents.injection import ParasiticInjection
from emc_assistant.testbench.asc_writer import build_asc, write_asc_bundle
from emc_assistant.testbench.asy_templates import (
    all_static_asy,
    cable_pwr_asy,
    cap_esr_esl_asy,
    dut_fragment_asy,
    lisn50uh_asy,
    trace_rlc_asy,
    via_l_asy,
)


# ---- ASY templates --------------------------------------------------------


@pytest.mark.parametrize("name,fn,expected_pins", [
    ("LISN50UH", lisn50uh_asy, {"HV_IN", "DUT", "MEAS", "0"}),
    ("CABLE_PWR", cable_pwr_asy, {"IN", "OUT", "0"}),
    ("TRACE_RLC", trace_rlc_asy, {"IN", "OUT", "0"}),
    ("VIA_L", via_l_asy, {"IN", "OUT"}),
    ("CAP_ESR_ESL", cap_esr_esl_asy, {"IN", "OUT"}),
])
def test_static_asy_has_header_and_correct_pin_names(name, fn, expected_pins):
    asy = fn()
    assert asy.startswith("Version 4\n")
    assert "SymbolType BLOCK" in asy
    assert "RECTANGLE Normal" in asy
    assert "SYMATTR Prefix X" in asy
    assert f"SYMATTR SpiceModel {name}" in asy
    pins = set()
    for line in asy.splitlines():
        if line.startswith("PINATTR PinName"):
            pins.add(line.split()[-1])
    assert pins == expected_pins, f"{name}: expected {expected_pins}, got {pins}"


def test_all_static_asy_round_trip():
    bundle = all_static_asy()
    assert set(bundle.keys()) == {
        "LISN50UH.asy",
        "CABLE_PWR.asy",
        "TRACE_RLC.asy",
        "VIA_L.asy",
        "CAP_ESR_ESL.asy",
    }
    for fname, body in bundle.items():
        assert body.startswith("Version 4\n"), f"{fname} missing header"
        assert "SYMATTR Prefix X" in body, f"{fname} missing X prefix"


def test_dut_fragment_asy_with_3_pins():
    asy = dut_fragment_asy(["in", "DUT_GND", "sw_ctrl"])
    assert asy.startswith("Version 4\n")
    pins = [line.split()[-1] for line in asy.splitlines() if line.startswith("PINATTR PinName")]
    assert pins == ["in", "DUT_GND", "sw_ctrl"]
    # USER FRAGMENT label is in the symbol
    assert "USER FRAGMENT" in asy


def test_dut_fragment_asy_handles_many_pins():
    """DUT_FRAGMENT should distribute pins across 4 sides without crashing."""
    pin_names = [f"net_{i}" for i in range(10)]
    asy = dut_fragment_asy(pin_names)
    pins = [line.split()[-1] for line in asy.splitlines() if line.startswith("PINATTR PinName")]
    assert pins == pin_names
    # First pin must be on the LEFT side (the supply input convention).
    pin_lines = [line for line in asy.splitlines() if line.startswith("PIN ")]
    assert pin_lines[0].split()[3] == "LEFT"


# ---- ASC writer ----------------------------------------------------------


def test_build_asc_has_required_sections():
    inj = ParasiticInjection(
        instance_name="X_TRACE_VIN",
        subckt_name="TRACE_RLC",
        nets=["n_dut_in_pre", "in", "DUT_GND"],
        rationale="series trace L between cable and DUT supply",
    )
    asc = build_asc(
        title="EMC testbench for test_project",
        v_rail_value="DC 24",
        dut_pins=["in", "DUT_GND"],
        injection=inj,
        user_cir_include="C:/tmp/testbench.cir",
    )
    text = asc.asc_text
    # Header is well-formed and on separate lines (no concatenation bug).
    assert text.startswith("Version 4.1\nSHEET 1 1280 720\n")
    # All composer-emitted symbols are referenced.
    for sym in ("V_RAIL", "X_LISN_P", "X_CABLE", "X_TRACE_VIN", "X_DUT", "X_LISN_N"):
        assert f"SYMATTR InstName {sym}" in text, f"missing symbol {sym}"
    # B-source probes are present.
    for probe in ("B_DM", "B_CM", "B_MEAS"):
        assert f"SYMATTR InstName {probe}" in text
    # FLAG labels for key nets.
    for net in ("HV_IN_RAIL", "HV_DUT_P", "n_dut_in_pre", "DUT_GND", "MEAS_P", "MEAS_N"):
        assert f" {net}\n" in text, f"missing FLAG for {net}"
    # The user .cir is included as a SPICE directive.
    assert "!.include C:/tmp/testbench.cir" in text


def test_build_asc_with_no_injection_omits_trace_symbol():
    asc = build_asc(
        title="t",
        v_rail_value="DC 24",
        dut_pins=["in", "DUT_GND"],
        injection=None,
        user_cir_include="x.cir",
    )
    assert "TRACE_RLC" not in asc.asc_text or "SYMATTR InstName X_TRACE" not in asc.asc_text


def test_build_asc_bundles_all_needed_symbols():
    """build_asc must produce a complete bundle the SYMBOL lines reference."""
    inj = ParasiticInjection(
        instance_name="X_TRACE_VIN",
        subckt_name="TRACE_RLC",
        nets=["n_dut_in_pre", "in", "DUT_GND"],
        rationale="x",
    )
    asc = build_asc(
        title="t",
        v_rail_value="DC 24",
        dut_pins=["in", "DUT_GND", "sw_ctrl"],
        injection=inj,
        user_cir_include="x.cir",
    )
    expected = {"LISN50UH.asy", "CABLE_PWR.asy", "TRACE_RLC.asy", "DUT_FRAGMENT.asy"}
    assert expected.issubset(set(asc.asy_files.keys()))


def test_write_asc_bundle_creates_all_files(tmp_path: Path):
    inj = ParasiticInjection(
        instance_name="X_TRACE_VIN",
        subckt_name="TRACE_RLC",
        nets=["n_dut_in_pre", "in", "DUT_GND"],
        rationale="x",
    )
    asc = build_asc(
        title="t",
        v_rail_value="DC 24",
        dut_pins=["in", "DUT_GND"],
        injection=inj,
        user_cir_include="x.cir",
    )
    out = tmp_path / "gen"
    asc_path = write_asc_bundle(out, asc)
    assert asc_path == out / "testbench.asc"
    assert asc_path.is_file()
    for fname in asc.asy_files:
        assert (out / fname).is_file()
    # Spot-check that an .asy contains a SymbolType line.
    assert "SymbolType BLOCK" in (out / "LISN50UH.asy").read_text(encoding="utf-8")
