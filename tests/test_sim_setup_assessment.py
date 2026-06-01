"""Tests for the deterministic simulation-setup integrity check
(``assess_simulation_setup``): band/Nyquist, edge resolution, frequency
resolution + cycles, and raw-.tran parsing."""

from __future__ import annotations

from emc_assistant.testbench.sim_settings import (
    SimulationSettings,
    assess_simulation_setup,
)


def _ids(assessment, severity=None):
    return {c.id for c in assessment.checks if severity is None or c.severity == severity}


def test_effective_times_parses_raw_tran():
    s = SimulationSettings(raw_tran_directive=".tran 0 1m 0 5n")
    stop, step, start = s.effective_times()
    assert stop == 1e-3 and step == 5e-9 and start == 0.0


def test_effective_times_from_structured_fields():
    s = SimulationSettings(stop_time="5m", max_timestep="100n", record_start="1m")
    stop, step, start = s.effective_times()
    assert abs(stop - 5e-3) < 1e-12
    assert abs(step - 1e-7) < 1e-15
    assert abs(start - 1e-3) < 1e-12


def test_coarse_timestep_aliases_band_is_high():
    s = SimulationSettings(stop_time="5m", max_timestep="100n")  # Nyquist 5 MHz
    a = assess_simulation_setup(s)  # default band max 30 MHz
    assert a.ok is False
    assert "timestep_aliases_band" in _ids(a, "high")
    assert a.recommended_max_timestep_s <= 1 / (2 * 30e6)


def test_fine_timestep_for_band_is_ok():
    s = SimulationSettings(raw_tran_directive=".tran 0 1m 0 5n")  # 5 ns → 100 MHz Nyquist
    a = assess_simulation_setup(s)            # no f_sw, no edge
    assert a.ok is True
    assert "timestep_aliases_band" not in _ids(a)


def test_fast_edge_needs_finer_timestep_is_high():
    # 5 ns step is fine for the 30 MHz band but far too coarse for a 2 ns edge.
    s = SimulationSettings(raw_tran_directive=".tran 0 5m 0 5n")
    a = assess_simulation_setup(s, switching_frequency_hz=400e3, edge_rise_time_s=2e-9)
    assert a.ok is False
    assert "timestep_misses_edge" in _ids(a, "high")
    # recommended step is edge-driven (t_rise/10 = 200 ps), tighter than the band one.
    assert a.recommended_max_timestep_s <= 2e-9 / 10 + 1e-15


def test_too_few_cycles_flagged():
    # 10 µs window at 400 kHz = 4 cycles → too few.
    s = SimulationSettings(stop_time="10u", max_timestep="5n")
    a = assess_simulation_setup(s, switching_frequency_hz=400e3)
    assert "too_few_cycles" in _ids(a, "medium")
    assert a.recommended_stop_time_s >= 20 / 400e3


def test_no_switching_frequency_skips_periodic_checks():
    # Aperiodic event (hot-swap): no f_sw → no cycles/startup checks.
    s = SimulationSettings(raw_tran_directive=".tran 0 1m 0 5n")
    a = assess_simulation_setup(s, switching_frequency_hz=None)
    assert "too_few_cycles" not in _ids(a)
    assert "startup_included" not in _ids(a)


def test_unset_timestep_is_flagged():
    s = SimulationSettings(raw_tran_directive=".tran 0 5m")  # no dTmax
    a = assess_simulation_setup(s)
    assert "timestep_unset" in _ids(a, "medium")
