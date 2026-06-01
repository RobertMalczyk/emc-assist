"""CISPR-style FFT post-processing for `.tran` outputs.

Standard conducted-EMI analysis (per SRC-001 LTspice EMC methodology and
related Würth slides indexed under SRC-021 / SRC-022 in our knowledge
base) needs frequency-domain output in **dBµV** vs **Hz**, not the
time-domain peak we produced through M2.6. This module does that
post-processing.

Pipeline:

1. Take a `.raw` axis (time) + voltage trace.
2. Optionally skip a startup transient window (the first `skip_fraction`
   of the run) so we FFT a stable region.
3. Resample to a uniform time grid (numpy `interp`) so `numpy.fft.rfft`
   gives a coherent spectrum.
4. Apply a Hann window to reduce spectral leakage.
5. FFT → single-sided magnitude (`|X(f)| / N * 2`), convert to **dBµV**
   via `20 * log10(V * 1e6)`.
6. Compute the maximum dBµV inside user-supplied frequency bands.
7. Report the achievable Nyquist honestly so callers know whether the
   simulated timestep was fine enough for the band they care about.

Pure numpy + math. No external EMC libraries.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Sequence

import numpy as np


DEFAULT_BANDS_HZ: tuple[tuple[float, float], ...] = (
    (150_000.0, 30_000_000.0),  # CISPR-25 / CISPR-32 conducted low band
    (30_000_000.0, 108_000_000.0),  # CISPR-25 FM-broadcast band overlap
)


# Internal floor to keep `20 * log10(0)` from exploding.
_LOG10_FLOOR_V = 1e-12  # 1 pV → -180 dBV → -60 dBµV — well below any noise floor


@dataclass
class SpectrumResult:
    freq_hz: np.ndarray
    """1-D float64 array of frequency bins (Hz), monotonic from 0 to Nyquist."""

    magnitude_dbuv: np.ndarray
    """Single-sided amplitude spectrum in dBµV (20·log10(V·1e6)). Same length as ``freq_hz``."""

    nyquist_hz: float
    """Highest frequency the spectrum is valid for, given the resampled rate."""

    sample_count: int
    """Number of points in the resampled time series."""

    skip_seconds: float
    """How much of the original `.tran` axis was skipped before the FFT window."""

    band_peaks: dict[str, float] = field(default_factory=dict)
    """``{band_key: peak_dbuv}`` produced by ``compute_band_peaks``."""


def _to_dbuv(linear_volts: np.ndarray) -> np.ndarray:
    floored = np.maximum(np.abs(linear_volts), _LOG10_FLOOR_V)
    return 20.0 * np.log10(floored * 1e6)


def compute_spectrum(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    *,
    skip_fraction: float = 0.1,
    max_resample_n: int = 1 << 20,
) -> SpectrumResult:
    """Resample → window → FFT → dBµV.

    ``skip_fraction`` chops off the initial transient (default 10%);
    pass ``0.0`` to FFT the whole window. ``max_resample_n`` caps the
    resampled length so we don't blow memory on multi-million-point
    traces (we still keep the highest-frequency information by setting
    a uniform step that resolves the original max rate).
    """
    axis = np.asarray(axis_seconds, dtype=np.float64)
    values = np.asarray(values_volts, dtype=np.float64)
    if axis.shape != values.shape:
        raise ValueError(
            f"axis and values shape mismatch: {axis.shape} vs {values.shape}"
        )
    if axis.size < 8:
        # Degenerate: tiny series, nothing useful to FFT. Return empty result.
        return SpectrumResult(
            freq_hz=np.zeros(0),
            magnitude_dbuv=np.zeros(0),
            nyquist_hz=0.0,
            sample_count=0,
            skip_seconds=0.0,
        )

    # Strip non-monotonic prefix (LTspice `.step` produces multi-segment
    # axes after `abs()`; we use the LAST monotonic run).
    diffs = np.diff(axis)
    if np.any(diffs <= 0):
        # Find the last index where axis resets (non-positive delta)
        reset_idx = int(np.where(diffs <= 0)[0][-1]) + 1
        axis = axis[reset_idx:]
        values = values[reset_idx:]
        if axis.size < 8:
            return SpectrumResult(
                freq_hz=np.zeros(0),
                magnitude_dbuv=np.zeros(0),
                nyquist_hz=0.0,
                sample_count=0,
                skip_seconds=0.0,
            )

    t0, t_end = float(axis[0]), float(axis[-1])
    if t_end <= t0:
        return SpectrumResult(
            freq_hz=np.zeros(0),
            magnitude_dbuv=np.zeros(0),
            nyquist_hz=0.0,
            sample_count=0,
            skip_seconds=0.0,
        )
    skip_seconds = max(0.0, (t_end - t0) * float(skip_fraction))
    window_t0 = t0 + skip_seconds

    # Pick the resampling step from the median dt of the input so we
    # roughly preserve its native resolution.
    median_dt = float(np.median(np.diff(axis)))
    if median_dt <= 0:
        return SpectrumResult(
            freq_hz=np.zeros(0),
            magnitude_dbuv=np.zeros(0),
            nyquist_hz=0.0,
            sample_count=0,
            skip_seconds=skip_seconds,
        )
    duration = t_end - window_t0
    if duration <= median_dt:
        return SpectrumResult(
            freq_hz=np.zeros(0),
            magnitude_dbuv=np.zeros(0),
            nyquist_hz=0.0,
            sample_count=0,
            skip_seconds=skip_seconds,
        )
    n = int(min(max_resample_n, max(8, math.floor(duration / median_dt))))
    dt = duration / max(1, n - 1)
    uniform_t = window_t0 + np.arange(n) * dt
    uniform_v = np.interp(uniform_t, axis, values)

    # Hann window then FFT
    window = np.hanning(n)
    windowed = (uniform_v - uniform_v.mean()) * window
    spectrum_c = np.fft.rfft(windowed)
    # Window amplitude correction: Hann normalises to sum(window) / 2 = N/4 effectively;
    # for single-sided amplitude we use 2/N (since hanning sums to N/2, factor 2 already).
    magnitudes_v = (np.abs(spectrum_c) * 2.0) / np.sum(window)
    freqs = np.fft.rfftfreq(n, d=dt)
    nyquist = 0.5 / dt
    magnitudes_dbuv = _to_dbuv(magnitudes_v)

    return SpectrumResult(
        freq_hz=freqs,
        magnitude_dbuv=magnitudes_dbuv,
        nyquist_hz=float(nyquist),
        sample_count=n,
        skip_seconds=skip_seconds,
    )


def compute_band_peaks(
    spec: SpectrumResult,
    bands_hz: Sequence[tuple[float, float]] | None = None,
) -> dict[str, float]:
    """Return ``{band_key: peak_dbuv}`` for each (f_low, f_high) band.

    Band key format: ``"<int_low_hz>_<int_high_hz>"`` for stable
    downstream consumption. A band entirely above the spectrum's
    Nyquist is reported as ``-math.inf`` so callers know the band is
    out of reach without the FFT failing silently.
    """
    bands_hz = tuple(bands_hz) if bands_hz else DEFAULT_BANDS_HZ
    out: dict[str, float] = {}
    if spec.freq_hz.size == 0:
        for f_low, f_high in bands_hz:
            key = f"{int(f_low)}_{int(f_high)}"
            out[key] = float("-inf")
        return out
    for f_low, f_high in bands_hz:
        key = f"{int(f_low)}_{int(f_high)}"
        if f_low > spec.nyquist_hz:
            out[key] = float("-inf")
            continue
        f_high_effective = min(f_high, spec.nyquist_hz)
        mask = (spec.freq_hz >= f_low) & (spec.freq_hz <= f_high_effective)
        if not mask.any():
            out[key] = float("-inf")
            continue
        out[key] = float(np.max(spec.magnitude_dbuv[mask]))
    spec.band_peaks = dict(out)
    return out


@dataclass
class SpectrumSummary:
    """Compact, JSON-friendly summary suitable for the metrics dict."""

    nyquist_hz: float
    sample_count: int
    skip_seconds: float
    band_peaks_dbuv: dict[str, float] = field(default_factory=dict)


def summarise_spectrum(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    *,
    bands_hz: Sequence[tuple[float, float]] | None = None,
    skip_fraction: float = 0.1,
) -> SpectrumSummary:
    """One-shot: FFT + band peaks → small struct for the report."""
    spec = compute_spectrum(axis_seconds, values_volts, skip_fraction=skip_fraction)
    peaks = compute_band_peaks(spec, bands_hz=bands_hz)
    return SpectrumSummary(
        nyquist_hz=spec.nyquist_hz,
        sample_count=spec.sample_count,
        skip_seconds=spec.skip_seconds,
        band_peaks_dbuv=peaks,
    )
