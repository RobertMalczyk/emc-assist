"""Tests for the CISPR-style FFT spectrum module."""

from __future__ import annotations

import math

import numpy as np

from emc_assistant.results.spectrum import (
    DEFAULT_BANDS_HZ,
    compute_band_peaks,
    compute_spectrum,
    summarise_spectrum,
)


def _make_sine(freq_hz: float, *, duration_s: float = 0.001, dt: float = 1e-8,
               amplitude_v: float = 1.0, dc_offset_v: float = 0.0) -> tuple[np.ndarray, np.ndarray]:
    t = np.arange(0, duration_s, dt)
    v = dc_offset_v + amplitude_v * np.sin(2 * np.pi * freq_hz * t)
    return t, v


def test_compute_spectrum_finds_peak_at_known_sine_frequency():
    f0 = 1_000_000.0  # 1 MHz
    t, v = _make_sine(f0, duration_s=0.001, dt=1e-8, amplitude_v=0.1)
    spec = compute_spectrum(t, v, skip_fraction=0.05)
    # Nyquist = 50 MHz (dt=10 ns)
    assert spec.nyquist_hz > 4e7
    # Peak bin should be at 1 MHz ± a few bin-widths.
    peak_idx = int(np.argmax(spec.magnitude_dbuv))
    f_peak = spec.freq_hz[peak_idx]
    df = spec.freq_hz[1] - spec.freq_hz[0]
    assert abs(f_peak - f0) <= 3 * df
    # Amplitude 0.1 V = 100,000 µV = 100 dBµV.
    # With Hann window we expect ~6 dB attenuation relative to a rectangular peak;
    # bound generously.
    assert 80 < spec.magnitude_dbuv[peak_idx] < 110


def test_compute_spectrum_dbuv_for_1v_sine_lands_in_120dbuv_neighbourhood():
    """A 1 V peak sine → 1e6 µV → 120 dBµV at the fundamental.
    Hann windowing eats a few dB; allow generous range."""
    t, v = _make_sine(2_000_000.0, duration_s=0.001, dt=1e-8, amplitude_v=1.0)
    spec = compute_spectrum(t, v, skip_fraction=0.05)
    peak_dbuv = float(np.max(spec.magnitude_dbuv))
    assert 100 < peak_dbuv < 130


def test_compute_spectrum_handles_short_input_gracefully():
    spec = compute_spectrum([0.0, 1e-6], [0.0, 1.0])
    assert spec.freq_hz.size == 0
    assert spec.nyquist_hz == 0.0
    assert spec.sample_count == 0


def test_compute_spectrum_skips_startup_window():
    t = np.linspace(0, 1e-3, 10_000)
    v = np.where(t < 5e-4, 5.0, 0.0)  # huge DC offset in first half
    spec_no_skip = compute_spectrum(t, v, skip_fraction=0.0)
    spec_skip = compute_spectrum(t, v, skip_fraction=0.6)
    # When we skip past the DC step, the low-frequency content drops dramatically.
    assert spec_skip.skip_seconds > 0
    assert spec_skip.skip_seconds > spec_no_skip.skip_seconds
    low_band_no_skip = float(np.max(spec_no_skip.magnitude_dbuv[:100]))
    low_band_skip = float(np.max(spec_skip.magnitude_dbuv[:100]))
    # The skip should reduce low-frequency content.
    assert low_band_skip < low_band_no_skip


def test_compute_band_peaks_default_bands_present():
    t, v = _make_sine(500_000.0, duration_s=0.001, dt=1e-8, amplitude_v=0.5)
    spec = compute_spectrum(t, v)
    peaks = compute_band_peaks(spec)
    assert "150000_30000000" in peaks
    assert "30000000_108000000" in peaks
    # 500 kHz sine sits inside the conducted band → finite peak.
    assert math.isfinite(peaks["150000_30000000"])
    # FM band peak should be tiny (no signal there).
    assert peaks["30000000_108000000"] < peaks["150000_30000000"]


def test_compute_band_peaks_above_nyquist_returns_minus_infinity():
    # Low sample rate → Nyquist below FM band.
    t = np.linspace(0, 0.01, 1000)  # dt = 10 µs → Nyquist = 50 kHz
    v = np.sin(2 * np.pi * 1000 * t)
    spec = compute_spectrum(t, v)
    peaks = compute_band_peaks(spec)
    # Both default bands (starting at 150 kHz) are above 50 kHz Nyquist.
    assert peaks["150000_30000000"] == float("-inf")
    assert peaks["30000000_108000000"] == float("-inf")


def test_compute_band_peaks_custom_bands():
    t, v = _make_sine(2_000_000.0, duration_s=0.001, dt=1e-8, amplitude_v=0.2)
    spec = compute_spectrum(t, v)
    peaks = compute_band_peaks(spec, bands_hz=[(1e6, 5e6), (10e6, 30e6)])
    assert "1000000_5000000" in peaks
    assert "10000000_30000000" in peaks
    # The 2 MHz sine sits in the first band.
    assert peaks["1000000_5000000"] > peaks["10000000_30000000"]


def test_summarise_spectrum_returns_compact_struct():
    t, v = _make_sine(1.5e6, duration_s=0.001, dt=1e-8, amplitude_v=0.3)
    summary = summarise_spectrum(t, v)
    assert summary.nyquist_hz > 0
    assert summary.sample_count > 0
    assert summary.skip_seconds > 0
    assert "150000_30000000" in summary.band_peaks_dbuv
    assert math.isfinite(summary.band_peaks_dbuv["150000_30000000"])


def test_compute_spectrum_handles_step_segmented_axis():
    """Simulate a `.step`-produced axis with a discontinuity (abs() collapses corners).

    Sample density must keep both segment frequencies below Nyquist
    so the FFT isn't aliased. Each segment is 0–1 ms with 20 ns dt
    (Nyquist = 25 MHz), which comfortably resolves the 1 / 2 MHz tones.
    """
    t1 = np.linspace(0, 1e-3, 50_000)
    t2 = np.linspace(0, 1e-3, 50_000)  # repeats — non-monotonic where t2 starts
    axis = np.concatenate([t1, t2])
    v = np.concatenate([
        np.sin(2 * np.pi * 1e6 * t1),
        np.sin(2 * np.pi * 2e6 * t2),
    ])
    spec = compute_spectrum(axis, v)
    # Should pick the LAST monotonic run (t2) → 2 MHz peak, not 1 MHz.
    peak_idx = int(np.argmax(spec.magnitude_dbuv))
    f_peak = spec.freq_hz[peak_idx]
    df = spec.freq_hz[1] - spec.freq_hz[0]
    assert abs(f_peak - 2e6) <= 5 * df


def test_default_bands_hz_matches_documented_cispr_envelope():
    # 150 kHz – 30 MHz conducted, 30 – 108 MHz FM
    assert DEFAULT_BANDS_HZ[0] == (150_000.0, 30_000_000.0)
    assert DEFAULT_BANDS_HZ[1] == (30_000_000.0, 108_000_000.0)
