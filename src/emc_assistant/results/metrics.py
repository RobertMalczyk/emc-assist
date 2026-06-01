"""First-order metrics over a ``.raw`` trace.

Pure Python (no numpy). All functions require ``axis`` and ``values``
to have equal length; otherwise we raise ``ValueError``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

from emc_assistant.results.raw_parser import RawFile


CONDUCTED_EMI_BAND_HZ: tuple[float, float] = (150e3, 30e6)
"""Default conducted-EMI band (150 kHz – 30 MHz) used when the .raw axis is
frequency. Tracks the common CISPR-25-class band envelope without
reproducing any normative text."""


@dataclass(frozen=True)
class TraceMetrics:
    max: float
    min: float
    peak: float
    peak_to_peak: float
    rms: float

    def to_dict(self, prefix: str = "") -> dict[str, float]:
        prefix = f"{prefix}_" if prefix else ""
        return {
            f"{prefix}max": self.max,
            f"{prefix}min": self.min,
            f"{prefix}peak": self.peak,
            f"{prefix}peak_to_peak": self.peak_to_peak,
            f"{prefix}rms": self.rms,
        }


def compute_trace_metrics(values: Sequence[float]) -> TraceMetrics:
    if not values:
        raise ValueError("Empty value sequence")
    vmax = max(values)
    vmin = min(values)
    peak = max(abs(vmax), abs(vmin))
    rms = math.sqrt(sum(v * v for v in values) / len(values))
    return TraceMetrics(
        max=vmax,
        min=vmin,
        peak=peak,
        peak_to_peak=vmax - vmin,
        rms=rms,
    )


def max_in_band(
    axis: Sequence[float],
    values: Sequence[float],
    *,
    axis_min: float,
    axis_max: float,
) -> float | None:
    """Return ``max(|values|)`` over the closed interval ``[axis_min, axis_max]``.

    Works for time and frequency axes alike. Returns ``None`` when no
    sample falls inside the band.
    """
    if len(axis) != len(values):
        raise ValueError("axis and values must have the same length")
    if axis_min > axis_max:
        raise ValueError("axis_min must be <= axis_max")
    selected = [abs(v) for a, v in zip(axis, values) if axis_min <= a <= axis_max]
    if not selected:
        return None
    return max(selected)


def pick_default_trace(raw: RawFile) -> str | None:
    """Heuristic: prefer ``V(meas)`` / ``V(meas_lisn)`` / ``V(out)``,
    fall back to the first non-axis voltage trace."""
    names = raw.variable_names
    if len(names) <= 1:
        return None
    lowered = {n.lower(): n for n in names[1:]}
    for preferred in ("v(meas)", "v(meas_lisn)", "v(out)"):
        if preferred in lowered:
            return lowered[preferred]
    for var in raw.header.variables[1:]:
        if var.kind.lower() == "voltage":
            return var.name
    return names[1]


def _axis_is_frequency(raw: RawFile) -> bool:
    if not raw.header.variables:
        return False
    return raw.header.variables[0].kind.lower() == "frequency"


def summarize_default_metrics(
    raw: RawFile,
    *,
    trace: str | None = None,
    bands_hz: tuple[tuple[float, float], ...] | None = None,
) -> dict[str, float]:
    """Convenience "give me something useful" summary for report/ranking.

    Returns a dict of metrics for the chosen (or heuristically default)
    trace plus axis bounds. When the .raw axis is frequency, also adds
    ``max_in_band_<fmin>_<fmax>`` entries for each band in ``bands_hz``
    (default: conducted-EMI 150 kHz – 30 MHz).

    When the .raw axis is **time** and the trace is a voltage, additionally
    runs FFT post-processing (per the M2.8.2 CISPR-style spectrum module)
    and adds ``<trace>_band_peak_dbuv_<flow>_<fhigh>`` entries for each band
    plus a ``<trace>_spectrum_nyquist_hz`` entry. The Nyquist key tells
    callers when the timestep was too coarse for the band of interest.
    """
    out: dict[str, float] = {}
    name = trace or pick_default_trace(raw)
    if name is None:
        return out
    values = raw.traces.get(name)
    if not values:
        return out
    metrics = compute_trace_metrics(values)
    safe = "".join(ch if ch.isalnum() else "_" for ch in name.lower()).strip("_")
    out.update(metrics.to_dict(prefix=safe))
    out[f"{safe}_n_points"] = float(len(values))
    if raw.axis:
        out["axis_min"] = float(min(raw.axis))
        out["axis_max"] = float(max(raw.axis))

    if _axis_is_frequency(raw):
        for band in (bands_hz or (CONDUCTED_EMI_BAND_HZ,)):
            fmin, fmax = band
            peak = max_in_band(raw.axis, values, axis_min=fmin, axis_max=fmax)
            if peak is not None:
                key = f"{safe}_max_in_band_{int(fmin)}_{int(fmax)}"
                out[key] = float(peak)
    else:
        # Time-axis voltage trace → FFT-based spectrum + dBµV band peaks.
        # See `results/spectrum.py` for the CISPR-style methodology.
        try:
            from emc_assistant.results.spectrum import summarise_spectrum
        except ImportError:  # pragma: no cover — numpy is a runtime dep
            return out
        is_voltage = False
        for var in raw.header.variables:
            if var.name == name and var.kind.lower() == "voltage":
                is_voltage = True
                break
        if is_voltage and raw.axis:
            spectrum_bands = bands_hz if bands_hz else None
            summary = summarise_spectrum(raw.axis, values, bands_hz=spectrum_bands)
            out[f"{safe}_spectrum_nyquist_hz"] = float(summary.nyquist_hz)
            out[f"{safe}_spectrum_sample_count"] = float(summary.sample_count)
            for band_key, peak_dbuv in summary.band_peaks_dbuv.items():
                # -inf means the band is entirely above the achievable Nyquist
                # (the timestep was too coarse). Skip the key so json.dump
                # doesn't emit a non-strict `-Infinity` token.
                if not math.isfinite(peak_dbuv):
                    continue
                out[f"{safe}_band_peak_dbuv_{band_key}"] = float(peak_dbuv)

            # CISPR-style peak / quasi-peak / average detector estimates
            # (band B) + the worst per-frequency margin vs the default
            # compliance standard. Engineering estimates, not certified
            # receiver readings — see results/detectors.py.
            try:
                from emc_assistant.results.detectors import (
                    CISPR_BAND_B,
                    conducted_emi_spectrum,
                )
                from emc_assistant.results.limits import get_standard, worst_margin
            except ImportError:  # pragma: no cover — numpy is a runtime dep
                return out
            # Canonical conducted-EMI detector (Mode 3 receiver-like sweep,
            # skip 0.0) — the single source of truth shared with the UI chart
            # and the report plot, so the verdict/table cannot disagree with
            # the spectrum (see detectors.conducted_emi_spectrum).
            spec = conducted_emi_spectrum(raw.axis, values, CISPR_BAND_B)
            if spec.usable:
                band_key = f"{int(CISPR_BAND_B.f_low)}_{int(CISPR_BAND_B.f_high)}"
                # The detector's receiver-sweep peak is the EMI peak-detector
                # reading; it supersedes the plain full-window FFT peak for this
                # band so the three detectors stay consistent
                # (peak >= quasi_peak >= average).
                out[f"{safe}_band_peak_dbuv_{band_key}"] = float(
                    spec.peak_dbuv.max()
                )
                out[f"{safe}_band_quasi_peak_dbuv_{band_key}"] = float(
                    spec.quasi_peak_dbuv.max()
                )
                out[f"{safe}_band_average_dbuv_{band_key}"] = float(
                    spec.average_dbuv.max()
                )
                # Worst per-frequency margin (reading - limit) vs the
                # default standard. Positive = over the limit.
                standard = get_standard(None)
                wq = worst_margin(
                    spec.freq_hz, spec.quasi_peak_dbuv, standard.quasi_peak
                )
                wa = worst_margin(
                    spec.freq_hz, spec.average_dbuv, standard.average
                )
                if wq is not None:
                    out[f"{safe}_qp_worst_margin_db"] = wq.margin_db
                    out[f"{safe}_qp_worst_margin_hz"] = wq.freq_hz
                if wa is not None:
                    out[f"{safe}_avg_worst_margin_db"] = wa.margin_db
                    out[f"{safe}_avg_worst_margin_hz"] = wa.freq_hz
    return out
