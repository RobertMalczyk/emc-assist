"""Tests for the CISPR peak / quasi-peak / average detector model."""

from __future__ import annotations

import numpy as np

from emc_assistant.results.detectors import (
    CISPR_BAND_A,
    CISPR_BAND_B,
    CISPR_BAND_C_D,
    CONDUCTED_BANDS,
    MODE_RECEIVER_LIKE_SINGLE_FREQUENCY,
    MODE_RECEIVER_LIKE_SWEEP,
    MODE_TIME_DOMAIN_DIAGNOSTIC,
    compute_detector_spectrum,
    compute_detectors,
    receiver_quasi_peak,
    receiver_sweep,
    _qp_meter,
)


def _cw(freq_hz, amp_v, duration_s, dt_s):
    t = np.arange(0.0, duration_s, dt_s)
    return t, amp_v * np.sin(2 * np.pi * freq_hz * t)


def _burst(freq_hz, amp_v, on_s, total_s, dt_s):
    t = np.arange(0.0, total_s, dt_s)
    v = amp_v * np.sin(2 * np.pi * freq_hz * t)
    v[t > on_s] = 0.0
    return t, v


# ---- the QP charge/discharge meter ----------------------------------------


def test_qp_meter_steady_input_charges_to_peak():
    # Charge constant short vs the run -> the meter reaches the input level.
    envelopes = np.ones((1, 300), dtype=float)
    out = _qp_meter(envelopes, dt_frame=1e-5, charge_s=1e-4, discharge_s=1e-3)
    assert out[0] > 0.99


def test_qp_meter_brief_input_undershoots_peak():
    # Input present for only 2 frames, charge constant much longer than that
    # -> the meter cannot charge to the peak.
    env = np.zeros((1, 80), dtype=float)
    env[0, :2] = 1.0
    out = _qp_meter(env, dt_frame=1e-5, charge_s=5e-3, discharge_s=160e-3)
    assert 0.0 < out[0] < 0.5  # partial charge — well below the input peak


# ---- compute_detectors end-to-end -----------------------------------------


def test_cw_detector_ordering_and_dbuv_scale():
    t, v = _cw(1e6, 0.1, 1e-3, 1e-8)  # 1 MHz, 0.1 V, 1 ms, 10 ns step
    (r,) = compute_detectors(t, v, skip_fraction=0.0)
    assert r.usable
    # Fundamental invariant: average <= quasi-peak <= peak.
    assert r.average_dbuv <= r.quasi_peak_dbuv + 1e-6
    assert r.quasi_peak_dbuv <= r.peak_dbuv + 1e-6
    # 0.1 V amplitude -> ~100 dBuV (20*log10(0.1 * 1e6)); allow window loss.
    assert 94.0 <= r.peak_dbuv <= 104.0


def test_burst_is_weighted_down_more_than_steady_tone():
    """An intermittent burst must read further below peak on the QP
    detector than a steady tone of the same amplitude."""
    t_cw, v_cw = _cw(1e6, 0.1, 1e-3, 1e-8)
    t_b, v_b = _burst(1e6, 0.1, 200e-6, 1e-3, 1e-8)
    (cw,) = compute_detectors(t_cw, v_cw, skip_fraction=0.0)
    (burst,) = compute_detectors(t_b, v_b, skip_fraction=0.0)

    cw_gap = cw.peak_dbuv - cw.quasi_peak_dbuv
    burst_gap = burst.peak_dbuv - burst.quasi_peak_dbuv
    assert burst_gap > cw_gap + 5.0
    # The burst's QP still respects the ordering invariant.
    assert burst.average_dbuv <= burst.quasi_peak_dbuv + 1e-6
    assert burst.quasi_peak_dbuv <= burst.peak_dbuv + 1e-6


def test_coarse_timestep_band_is_unusable():
    # 10 us step -> 50 kHz Nyquist, below the 150 kHz band-B floor.
    t, v = _cw(20e3, 0.1, 5e-3, 1e-5)
    (r,) = compute_detectors(t, v)
    assert r.usable is False
    assert "Nyquist" in r.note or "timestep" in r.note


def test_degenerate_trace_is_unusable():
    readings = compute_detectors([0.0, 1.0, 2.0, 3.0], [0.0, 0.0, 0.0, 0.0])
    assert readings and readings[0].usable is False


def test_band_constants_match_en55016_1_1():
    # Verified against EN 55016-1-1 ed. 3 (CISPR 16-1-1).
    assert CISPR_BAND_B.f_low == 150e3 and CISPR_BAND_B.f_high == 30e6
    assert CISPR_BAND_B.rbw_hz == 9e3
    assert CISPR_BAND_B.qp_charge_s == 1e-3
    assert CISPR_BAND_B.qp_discharge_s == 160e-3
    assert CISPR_BAND_B.meter_s == 160e-3
    assert (CISPR_BAND_A.rbw_hz, CISPR_BAND_A.qp_charge_s,
            CISPR_BAND_A.qp_discharge_s, CISPR_BAND_A.meter_s) == (
        200.0, 45e-3, 500e-3, 160e-3)
    assert (CISPR_BAND_C_D.rbw_hz, CISPR_BAND_C_D.qp_charge_s,
            CISPR_BAND_C_D.qp_discharge_s, CISPR_BAND_C_D.meter_s) == (
        120e3, 1e-3, 550e-3, 100e-3)
    # Verification principle: Band B is the default conducted-EMI band.
    assert CONDUCTED_BANDS == (CISPR_BAND_B,)


def test_reading_is_tagged_as_mode_1_unfiltered():
    t, v = _cw(1e6, 0.1, 1e-3, 1e-8)
    (r,) = compute_detectors(t, v, skip_fraction=0.0)
    assert r.mode == MODE_TIME_DOMAIN_DIAGNOSTIC
    assert r.receiver_filtered is False


# ---- verification principles (concept note §13) ---------------------------


def test_step_response_matches_charge_time():
    # Verification principle: a step response should rise on the charge
    # time scale — after one charge time constant it reaches ~1 - 1/e.
    dt_frame, charge_s = 1e-5, 2e-3
    n_frames = round(charge_s / dt_frame)  # exactly one charge constant
    out = _qp_meter(np.ones((1, n_frames)), dt_frame, charge_s, discharge_s=1.0)
    assert 0.58 < out[0] < 0.68  # 1 - 1/e ≈ 0.632


def test_quasi_peak_increases_with_pulse_repetition_rate():
    # Verification principle: QP rises with repetition rate. The discharge
    # constant sets how far the meter falls between pulses, so closer-spaced
    # pulses (higher PRF) keep it charged higher.
    dt_frame, charge_s, discharge_s = 1e-4, 1e-3, 20e-3

    def train(gap_frames, n_pulses=10):
        env: list[float] = []
        for _ in range(n_pulses):
            env += [1.0, 1.0, 1.0]          # a short pulse
            env += [0.0] * gap_frames        # the inter-pulse gap
        return np.array(env, dtype=float).reshape(1, -1)

    qp_fast = _qp_meter(train(2), dt_frame, charge_s, discharge_s)[0]
    qp_mid = _qp_meter(train(20), dt_frame, charge_s, discharge_s)[0]
    qp_slow = _qp_meter(train(200), dt_frame, charge_s, discharge_s)[0]
    assert qp_fast > qp_mid > qp_slow > 0.0


def test_cw_peak_converges_to_quasi_peak_on_a_long_run():
    # Verification principle: a continuous-wave (sustained) input should
    # give similar peak and quasi-peak readings — the QP detector charges
    # fully to the peak.
    t, v = _cw(1e6, 0.1, 6e-3, 1e-8)  # 6 ms CW — many charge constants
    (r,) = compute_detectors(t, v, skip_fraction=0.0)
    assert r.usable
    assert r.peak_dbuv - r.quasi_peak_dbuv < 2.0


def test_quasi_peak_never_exceeds_peak():
    # Verification principle: QP must not exceed the peak for the same
    # (here, identically-processed) input.
    signals = [
        _cw(1e6, 0.1, 1e-3, 1e-8),
        _burst(1e6, 0.1, 200e-6, 1e-3, 1e-8),
    ]
    for t, v in signals:
        for r in compute_detectors(t, v, skip_fraction=0.0):
            if not r.usable:
                continue
            assert r.average_dbuv <= r.quasi_peak_dbuv + 1e-6
            assert r.quasi_peak_dbuv <= r.peak_dbuv + 1e-6


def test_detector_spectrum_per_frequency_curves():
    t, v = _cw(1e6, 0.1, 1e-3, 1e-8)
    spec = compute_detector_spectrum(t, v, skip_fraction=0.0)
    assert spec.usable
    n = spec.freq_hz.size
    assert n > 0
    assert spec.peak_dbuv.size == n == spec.quasi_peak_dbuv.size == spec.average_dbuv.size
    # Every frequency bin sits inside the band.
    assert spec.freq_hz.min() >= CISPR_BAND_B.f_low
    assert spec.freq_hz.max() <= CISPR_BAND_B.f_high
    # The ordering invariant holds at every frequency.
    assert (spec.average_dbuv <= spec.quasi_peak_dbuv + 1e-6).all()
    assert (spec.quasi_peak_dbuv <= spec.peak_dbuv + 1e-6).all()


def test_detector_spectrum_degenerate_trace_unusable():
    spec = compute_detector_spectrum([0.0, 1.0, 2.0, 3.0], [0.0, 0.0, 0.0, 0.0])
    assert spec.usable is False
    assert spec.freq_hz.size == 0


# ---- Mode 2 — receiver_like_single_frequency ------------------------------


def test_receiver_mode_reads_an_on_band_tone():
    t, v = _cw(1e6, 0.1, 2e-3, 1e-8)  # 1 MHz, 0.1 V tone
    r = receiver_quasi_peak(t, v, center_hz=1e6)
    assert r.usable
    assert r.mode == MODE_RECEIVER_LIKE_SINGLE_FREQUENCY
    assert r.receiver_filtered is True
    # 0.1 V -> ~100 dBµV; ordering avg <= qp <= peak holds.
    assert 94.0 <= r.peak_dbuv <= 104.0
    assert r.average_dbuv <= r.quasi_peak_dbuv + 1e-6
    assert r.quasi_peak_dbuv <= r.peak_dbuv + 1e-6


def test_receiver_mode_rejects_an_off_band_emission():
    # A 1 MHz tone, measured 100 kHz away — far outside the 9 kHz RBW.
    t, v = _cw(1e6, 0.1, 2e-3, 1e-8)
    on_band = receiver_quasi_peak(t, v, center_hz=1e6)
    off_band = receiver_quasi_peak(t, v, center_hz=1.1e6)
    # The receiver-bandwidth filter must reject the off-band tone.
    assert on_band.peak_dbuv - off_band.peak_dbuv > 60.0


def test_receiver_mode_selects_between_two_tones():
    t = np.arange(0.0, 2e-3, 1e-8)
    v = 0.1 * np.sin(2 * np.pi * 1e6 * t) + 0.1 * np.sin(2 * np.pi * 5e6 * t)
    at_1mhz = receiver_quasi_peak(t, v, center_hz=1e6)
    at_5mhz = receiver_quasi_peak(t, v, center_hz=5e6)
    at_3mhz = receiver_quasi_peak(t, v, center_hz=3e6)
    # Each tone is seen at its own frequency...
    assert 94.0 <= at_1mhz.peak_dbuv <= 104.0
    assert 94.0 <= at_5mhz.peak_dbuv <= 104.0
    # ...and the empty gap between them reads far lower.
    assert at_1mhz.peak_dbuv - at_3mhz.peak_dbuv > 40.0


def test_receiver_mode_center_above_nyquist_is_unusable():
    t, v = _cw(1e6, 0.1, 2e-3, 1e-8)  # dt 10 ns -> 50 MHz Nyquist
    r = receiver_quasi_peak(t, v, center_hz=80e6)
    assert r.usable is False
    assert "Nyquist" in r.note


def test_receiver_mode_degenerate_trace_is_unusable():
    r = receiver_quasi_peak([0.0, 1.0, 2.0, 3.0], [0.0, 0.0, 0.0, 0.0], center_hz=1e6)
    assert r.usable is False


# ---- Mode 3 — receiver_like_sweep ------------------------------------------


def test_receiver_sweep_produces_a_band_spectrum():
    t, v = _cw(1e6, 0.1, 2e-3, 1e-8)
    sweep = receiver_sweep(t, v, n_points=48)
    assert sweep.usable
    assert sweep.mode == MODE_RECEIVER_LIKE_SWEEP
    assert sweep.receiver_filtered is True
    n = sweep.freq_hz.size
    assert n == 48
    assert (
        sweep.peak_dbuv.size
        == n
        == sweep.quasi_peak_dbuv.size
        == sweep.average_dbuv.size
    )
    # Swept frequencies stay inside CISPR Band B.
    assert sweep.freq_hz.min() >= CISPR_BAND_B.f_low
    assert sweep.freq_hz.max() <= CISPR_BAND_B.f_high
    # Ordering invariant holds at every swept point.
    assert (sweep.average_dbuv <= sweep.quasi_peak_dbuv + 1e-6).all()
    assert (sweep.quasi_peak_dbuv <= sweep.peak_dbuv + 1e-6).all()
    # The 1 MHz tone shows up near 1 MHz in the swept spectrum.
    i_peak = int(np.argmax(sweep.peak_dbuv))
    assert 0.5e6 < sweep.freq_hz[i_peak] < 2.0e6


def test_receiver_sweep_coarse_timestep_is_unusable():
    t, v = _cw(20e3, 0.1, 5e-3, 1e-5)  # 50 kHz Nyquist < Band B
    sweep = receiver_sweep(t, v)
    assert sweep.usable is False
    assert "Nyquist" in sweep.note or "timestep" in sweep.note


def test_receiver_sweep_degenerate_trace_is_unusable():
    sweep = receiver_sweep([0.0, 1.0, 2.0, 3.0], [0.0, 0.0, 0.0, 0.0])
    assert sweep.usable is False
