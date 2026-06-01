"""Tests for the CISPR average detector (``emc_assistant.results.detectors``).

The average detector is the meter-time-constant counterpart of the
quasi-peak detector: the envelope through a linear τ_meter low-pass, then
max-held. The low-pass is seeded with the envelope mean so a transient
simulation far shorter than the 160 ms meter constant degrades
gracefully to that mean instead of under-reading from a cold start.

These exercise the detector core directly (``_meter_average``,
``_meter_average_running_max``, ``_avg_meter``) plus its flow through the
three receiver modes. The quasi-peak core has its own suite
(``test_quasi_peak_detector.py``).
"""

from __future__ import annotations

import numpy as np
import pytest

from emc_assistant.results import detectors


# ---- _meter_average — the one-pole low-pass core ---------------------------


def test_meter_average_constant_input_seeded_at_that_value_is_flat():
    env = np.full(200, 2.0)
    traj = detectors._meter_average(env, dt=1e-3, tau=0.1, initial=2.0)
    assert traj == pytest.approx(2.0)
    assert traj.shape == (200,)


def test_meter_average_converges_toward_the_input_level():
    """Seeded cold, the meter rises monotonically toward a constant input
    and settles after many time constants."""
    env = np.full(100_000, 1.0)
    traj = detectors._meter_average(env, dt=1e-3, tau=0.1, initial=0.0)
    assert traj[0] < traj[100] < traj[-1]
    assert traj[-1] == pytest.approx(1.0, abs=1e-6)  # dt·n = 1000·tau


def test_meter_average_never_overshoots_the_input():
    env = np.full(500, 1.0)
    traj = detectors._meter_average(env, dt=1e-3, tau=0.05, initial=0.0)
    assert traj.max() <= 1.0


# ---- _meter_average_running_max — the detector indication ------------------


def test_running_max_of_a_steady_signal_equals_its_mean():
    """A steady emission: the meter stays at the seeded mean → the
    detector reads that mean (the correct steady-state average)."""
    envelope = np.full(20_000, 0.7)
    reading = detectors._meter_average_running_max(envelope, dt=1e-5, tau=0.16)
    assert reading == pytest.approx(0.7, rel=1e-6)


def test_running_max_catches_an_intermittent_burst_above_the_whole_mean():
    """The headline behaviour: unlike a naive whole-window mean, the
    meter-based detector catches an intermittent burst and reads above
    that mean — while still never exceeding the envelope peak."""
    dt = 1e-5
    envelope = np.concatenate([np.full(5_000, 1.0), np.zeros(45_000)])
    whole_window_mean = float(envelope.mean())  # 0.10
    reading = detectors._meter_average_running_max(envelope, dt, tau=0.16)
    assert reading > whole_window_mean
    assert reading <= float(envelope.max())


def test_running_max_of_empty_envelope_is_zero():
    assert detectors._meter_average_running_max(np.zeros(0), dt=1e-5, tau=0.16) == 0.0


# ---- _avg_meter — the vectorised STFT (Mode 1) variant ---------------------


def test_avg_meter_constant_envelopes_return_the_per_bin_mean():
    envelopes = np.array([[1.0, 1.0, 1.0], [3.0, 3.0, 3.0], [0.0, 0.0, 0.0]])
    out = detectors._avg_meter(envelopes, dt_frame=1e-3, tau=0.1)
    assert out == pytest.approx([1.0, 3.0, 0.0])


def test_avg_meter_returns_one_value_per_bin():
    envelopes = np.random.default_rng(0).random((7, 25))
    out = detectors._avg_meter(envelopes, dt_frame=1e-3, tau=0.1)
    assert out.shape == (7,)
    # Each bin's max-hold cannot exceed that bin's peak frame.
    assert np.all(out <= envelopes.max(axis=1) + 1e-9)


# ---- integration through the receiver modes --------------------------------


def _cw_tone(freq_hz: float, fs: float, n: int) -> tuple[list[float], list[float]]:
    t = np.arange(n) / fs
    return list(t), list(np.sin(2.0 * np.pi * freq_hz * t))


def test_mode2_average_bounded_by_quasi_peak_and_peak_for_a_cw_tone():
    """receiver_quasi_peak — average ≤ quasi-peak ≤ peak, and for a steady
    tone the average detector lands close to the others."""
    axis, values = _cw_tone(1e6, fs=20e6, n=20_000)
    reading = detectors.receiver_quasi_peak(axis, values, center_hz=1e6)
    assert reading.usable
    assert reading.average_dbuv <= reading.quasi_peak_dbuv + 1e-6
    assert reading.quasi_peak_dbuv <= reading.peak_dbuv + 1e-6
    # A steady CW tone reads near-equal on all three detectors.
    assert reading.peak_dbuv - reading.average_dbuv < 6.0


def test_mode1_average_bounded_by_quasi_peak_and_peak():
    """compute_detectors — the band-max average sits below QP and peak."""
    axis, values = _cw_tone(1e6, fs=20e6, n=20_000)
    [reading] = detectors.compute_detectors(axis, values, skip_fraction=0.0)
    assert reading.usable
    assert reading.average_dbuv <= reading.quasi_peak_dbuv + 1e-6
    assert reading.quasi_peak_dbuv <= reading.peak_dbuv + 1e-6


def test_mode3_average_curve_bounded_elementwise():
    """receiver_sweep — average ≤ quasi-peak ≤ peak at every swept point."""
    axis, values = _cw_tone(1e6, fs=20e6, n=20_000)
    sweep = detectors.receiver_sweep(axis, values, n_points=24, skip_fraction=0.0)
    assert sweep.usable
    assert np.all(sweep.average_dbuv <= sweep.quasi_peak_dbuv + 1e-6)
    assert np.all(sweep.quasi_peak_dbuv <= sweep.peak_dbuv + 1e-6)
