"""Tests for M2.13 — structured simulation / solver settings."""

from __future__ import annotations

import pytest

from emc_assistant.testbench.composer import TestbenchPlan, compose_testbench_cir
from emc_assistant.testbench.sim_settings import SimulationSettings, spice_to_float


# ---- spice_to_float --------------------------------------------------------


@pytest.mark.parametrize("text,expected", [
    ("5m", 5e-3), ("100n", 1e-7), ("1meg", 1e6), ("2.5e-3", 2.5e-3),
    ("250m", 0.25), ("1k", 1e3), ("0", 0.0), ("3u", 3e-6),
])
def test_spice_to_float(text, expected):
    assert spice_to_float(text) == pytest.approx(expected)


def test_spice_to_float_rejects_garbage():
    with pytest.raises(ValueError):
        spice_to_float("not a number")


# ---- defaults + raw override ----------------------------------------------


def test_defaults_match_the_composer_default():
    s = SimulationSettings.from_user_context({})
    assert s.tran_line() == ".tran 0 5m 0 100n"
    assert s.options_line() == ""


def test_raw_tran_directive_wins():
    s = SimulationSettings.from_user_context(
        {"simulation": {"tran_directive": ".tran 0 250m 0 100u"}}
    )
    assert s.tran_line() == ".tran 0 250m 0 100u"


def test_non_string_tran_directive_is_ignored():
    s = SimulationSettings.from_user_context({"simulation": {"tran_directive": 250}})
    assert s.tran_line() == ".tran 0 5m 0 100n"  # falls back to defaults


# ---- structured transient fields ------------------------------------------


def test_structured_tran_line():
    s = SimulationSettings.from_user_context({"simulation": {
        "stop_time": "20m", "max_timestep": "50n", "record_start": "1m",
    }})
    assert s.tran_line() == ".tran 0 20m 1m 50n"


def test_startup_flag_appended():
    s = SimulationSettings.from_user_context(
        {"simulation": {"stop_time": "10m", "startup": True}}
    )
    assert s.tran_line().endswith(" startup")


# ---- options ---------------------------------------------------------------


def test_options_line_method_and_extras():
    s = SimulationSettings.from_user_context({"simulation": {
        "integration_method": "gear",
        "options": {"reltol": "1e-4", "abstol": "1e-12"},
    }})
    line = s.options_line()
    assert line.startswith(".options ")
    assert "method=gear" in line
    assert "reltol=1e-4" in line and "abstol=1e-12" in line


def test_options_line_empty_when_nothing_set():
    assert SimulationSettings.from_user_context({}).options_line() == ""


# ---- validation ------------------------------------------------------------


def test_rejects_unknown_integration_method():
    with pytest.raises(ValueError):
        SimulationSettings.from_user_context(
            {"simulation": {"integration_method": "magic"}}
        )


def test_rejects_timestep_larger_than_stop():
    with pytest.raises(ValueError):
        SimulationSettings.from_user_context(
            {"simulation": {"stop_time": "1m", "max_timestep": "5m"}}
        )


def test_rejects_zero_stop_time():
    with pytest.raises(ValueError):
        SimulationSettings.from_user_context({"simulation": {"stop_time": "0"}})


def test_rejects_record_start_past_stop():
    with pytest.raises(ValueError):
        SimulationSettings.from_user_context(
            {"simulation": {"stop_time": "5m", "record_start": "10m"}}
        )


def test_bad_structured_field_skipped_when_raw_override_present():
    """A raw tran_directive bypasses the structured-field validation."""
    s = SimulationSettings.from_user_context({"simulation": {
        "tran_directive": ".tran 0 1m 0 1u",
        "stop_time": "0",  # invalid, but ignored because the raw override wins
    }})
    assert s.tran_line() == ".tran 0 1m 0 1u"


# ---- composer emits .options ----------------------------------------------


def test_composer_emits_options_before_tran():
    cir = compose_testbench_cir(TestbenchPlan(
        title="t", parasitics=[],
        tran_directive=".tran 0 5m 0 100n",
        options_directive=".options method=gear reltol=1e-4",
    ))
    assert ".options method=gear reltol=1e-4" in cir
    assert cir.index(".options method=gear") < cir.index(".tran 0 5m 0 100n")


def test_composer_omits_options_when_empty():
    cir = compose_testbench_cir(TestbenchPlan(title="t", parasitics=[]))
    assert ".options" not in cir
