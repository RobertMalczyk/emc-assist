"""CISPR-style EMI-receiver detectors — peak, quasi-peak, average.

A real EMI receiver does not read the raw FFT. It sweeps with a defined
**resolution bandwidth (RBW)** and applies a **detector** to the envelope
of each spectral component:

- **Peak** — the maximum of the envelope.
- **Average** — the envelope through a linear meter-time-constant
  low-pass, then max-held. For a steady emission this equals the mean of
  the envelope; an intermittent burst reads above that mean.
- **Quasi-peak (QP)** — a charge/discharge weighted detector (CISPR
  16-1-1): it charges fast and discharges slowly, so intermittent /
  impulsive emissions read *lower* than steady ones. QP always lands
  between average and peak.

This module estimates those three detectors from a **transient
simulation** trace via a short-time FFT (STFT): the STFT gives, for every
frequency, how that spectral component evolves over the run — exactly
what a detector weights. The QP charge/discharge meter is then run over
that per-frequency time series with the published CISPR time constants.

:func:`compute_detector_spectrum` returns the three detectors *per
frequency* (for plotting); :func:`compute_detectors` reduces that to one
band-max reading per band.

IMPORTANT — this is a pre-compliance **engineering estimate**, not a
receiver-accurate measurement:

- A transient sim is usually far shorter than the QP discharge constant
  (160 ms for band B). Over a short window the QP meter cannot fully
  discharge, so the QP estimate is **conservative — it tends toward the
  peak**. For a steady switching emission QP ≈ peak is in fact physically
  correct; for a single intermittent event the QP reads meaningfully
  below peak only if the sim also captures quiet time after the event.
- The RBW is modelled by the STFT window length, not a true swept
  super-heterodyne receiver, and the per-bin level is not RBW-integrated.

Treat the QP / average numbers as engineering hypotheses to verify on a
real EMI receiver — never as a compliance result. No normative limit
lines or pass/fail data are reproduced here; only the detector method
and its widely-published time constants are modelled.

This module implements all three modes in
``docs/concepts/quasi_peak_detector_concept.md``:

- **Mode 1 — ``time_domain_diagnostic``** (:func:`compute_detectors`,
  :func:`compute_detector_spectrum`): a QP-like weighting applied to a
  selected waveform via an STFT, with no receiver-bandwidth filter.
- **Mode 2 — ``receiver_like_single_frequency``**
  (:func:`receiver_quasi_peak`): a receiver-bandwidth filter centred at a
  chosen frequency → envelope → QP detector — the receiver-like estimate.
- **Mode 3 — ``receiver_like_sweep``** (:func:`receiver_sweep`): Mode 2
  swept across the conducted band — the closest pre-compliance
  approximation of an EMI-receiver scan.

Band constants are verified against EN 55016-1-1 ed. 3 (CISPR 16-1-1).
The meter / indicator time constant (``meter_s``) drives the average
detector's averaging low-pass. That low-pass is seeded with the envelope
mean, so a transient simulation far shorter than 160 ms degrades
gracefully to that mean — the correct steady-state average — instead of
under-reading from a cold start. The quasi-peak modes do not apply
``meter_s`` as a literal low-pass — their indicator stage is a max-hold.

Pure numpy + math.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Sequence

import numpy as np

# Keep 20*log10(0) from exploding (1 pV floor — far below any noise floor).
_LOG10_FLOOR_V = 1e-12

# Detector modes — see docs/concepts/quasi_peak_detector_concept.md §7.
# Mode 1: compute_detectors / compute_detector_spectrum.
# Mode 2: receiver_quasi_peak.   Mode 3: receiver_sweep.
MODE_TIME_DOMAIN_DIAGNOSTIC = "time_domain_diagnostic"
MODE_RECEIVER_LIKE_SINGLE_FREQUENCY = "receiver_like_single_frequency"  # future
MODE_RECEIVER_LIKE_SWEEP = "receiver_like_sweep"  # future

# Mandatory limitation / disclaimer wording (concept note §12).
DIAGNOSTIC_LIMITATION = (
    "This is a time-domain diagnostic quasi-peak-like metric applied "
    "directly to the selected waveform. It is not equivalent to a CISPR "
    "receiver quasi-peak measurement because no receiver bandwidth filter "
    "was applied."
)
GENERAL_DISCLAIMER = (
    "Quasi-peak results are CISPR-like pre-compliance diagnostics only. "
    "They are not a substitute for a certified EMI receiver or accredited "
    "EMC laboratory measurement."
)


@dataclass(frozen=True)
class CisprBand:
    """An EMI band + its CISPR 16-1-1 / EN 55016-1-1 ed. 3 detector
    parameters: resolution bandwidth and QP charge / discharge / meter
    (indicator) time constants. These are detector parameters — not
    limit lines and not normative pass/fail data.

    ``meter_s`` (the indicator time constant) drives the average
    detector's averaging low-pass in every mode; the quasi-peak
    indicator stage is a max-hold, not a literal ``meter_s`` low-pass."""

    name: str
    f_low: float
    f_high: float
    rbw_hz: float
    qp_charge_s: float
    qp_discharge_s: float
    meter_s: float


# CISPR 16-1-1 / EN 55016-1-1 ed. 3 detector parameters — verified
# against the standard (see docs/concepts/quasi_peak_detector_concept.md §6).
#                          name    f_low  f_high  rbw     charge  discharge  meter
CISPR_BAND_A = CisprBand(   "A",    9e3,   150e3,  200.0,  45e-3,  500e-3,    160e-3)
CISPR_BAND_B = CisprBand(   "B",   150e3,  30e6,   9e3,    1e-3,   160e-3,    160e-3)
CISPR_BAND_C_D = CisprBand( "C/D",  30e6,  1e9,    120e3,  1e-3,   550e-3,    100e-3)

# The conducted-EMI band of interest for DC/DC converters (concept note §6).
CONDUCTED_BANDS: tuple[CisprBand, ...] = (CISPR_BAND_B,)


@dataclass
class DetectorSpectrum:
    """Per-frequency peak / quasi-peak / average curves for one band (dBµV)."""

    band: str
    freq_hz: np.ndarray
    peak_dbuv: np.ndarray
    quasi_peak_dbuv: np.ndarray
    average_dbuv: np.ndarray
    usable: bool
    note: str = ""
    mode: str = MODE_TIME_DOMAIN_DIAGNOSTIC
    receiver_filtered: bool = False


@dataclass
class DetectorReading:
    """Band-max peak / quasi-peak / average reading for one band (dBµV)."""

    band: str
    f_low: float
    f_high: float
    peak_dbuv: float
    quasi_peak_dbuv: float
    average_dbuv: float
    usable: bool
    note: str = ""
    mode: str = MODE_TIME_DOMAIN_DIAGNOSTIC
    receiver_filtered: bool = False

    def to_dict(self) -> dict:
        return {
            "band": self.band,
            "f_low_hz": self.f_low,
            "f_high_hz": self.f_high,
            "peak_dbuv": self.peak_dbuv,
            "quasi_peak_dbuv": self.quasi_peak_dbuv,
            "average_dbuv": self.average_dbuv,
            "usable": self.usable,
            "mode": self.mode,
            "receiver_filtered": self.receiver_filtered,
            "note": self.note,
        }


def _to_dbuv(linear_volts):
    """Volts → dBµV (``20·log10(V·1e6)``); works for scalars and arrays."""
    floored = np.maximum(np.abs(np.asarray(linear_volts, dtype=np.float64)),
                         _LOG10_FLOOR_V)
    return 20.0 * np.log10(floored * 1e6)


def _resample(axis, values, skip_fraction):
    """Resample to a uniform time grid (skipping a startup fraction).
    Returns ``(uniform_values, dt)`` or ``None`` for a degenerate trace."""
    axis = np.asarray(axis, dtype=np.float64)
    values = np.asarray(values, dtype=np.float64)
    if axis.shape != values.shape or axis.size < 16:
        return None
    # Use the last monotonic run (LTspice .step axes reset after abs()).
    diffs = np.diff(axis)
    if np.any(diffs <= 0):
        reset = int(np.where(diffs <= 0)[0][-1]) + 1
        axis, values = axis[reset:], values[reset:]
        if axis.size < 16:
            return None
    t0, t_end = float(axis[0]), float(axis[-1])
    if t_end <= t0:
        return None
    skip = max(0.0, (t_end - t0) * float(skip_fraction))
    window_t0 = t0 + skip
    median_dt = float(np.median(np.diff(axis)))
    if median_dt <= 0:
        return None
    duration = t_end - window_t0
    if duration <= median_dt:
        return None
    n = max(16, int(math.floor(duration / median_dt)))
    n = min(n, 1 << 22)  # cap ~4M points
    dt = duration / (n - 1)
    uniform_t = window_t0 + np.arange(n) * dt
    return np.interp(uniform_t, axis, values), dt


def _qp_meter(
    envelopes: np.ndarray, dt_frame: float, charge_s: float, discharge_s: float
) -> np.ndarray:
    """Run the CISPR quasi-peak charge/discharge meter over an STFT
    envelope. ``envelopes`` is ``[n_bins, n_frames]``; returns the
    per-bin QP value (the meter's running maximum)."""
    alpha_c = 1.0 - math.exp(-dt_frame / charge_s)
    alpha_d = 1.0 - math.exp(-dt_frame / discharge_s)
    meter = np.zeros(envelopes.shape[0])
    meter_max = np.zeros(envelopes.shape[0])
    for frame in range(envelopes.shape[1]):
        x = envelopes[:, frame]
        charging = x > meter
        meter = meter + np.where(charging, (x - meter) * alpha_c, (x - meter) * alpha_d)
        meter_max = np.maximum(meter_max, meter)
    return meter_max


def _avg_meter(envelopes: np.ndarray, dt_frame: float, tau: float) -> np.ndarray:
    """Run the CISPR average-detector meter — a linear τ_meter low-pass —
    over an STFT envelope. ``envelopes`` is ``[n_bins, n_frames]``;
    returns the per-bin max-hold indication.

    Each bin's meter is seeded with that bin's mean, so a simulation far
    shorter than ``tau`` degrades gracefully to the mean of the envelope
    (the correct steady-state average) rather than under-reading from a
    cold start — see :func:`_meter_average_running_max`."""
    alpha = 1.0 - math.exp(-dt_frame / tau)
    meter = envelopes.mean(axis=1).astype(np.float64)
    meter_max = meter.copy()
    for frame in range(envelopes.shape[1]):
        meter = meter + (envelopes[:, frame] - meter) * alpha
        meter_max = np.maximum(meter_max, meter)
    return meter_max


def _empty_spectrum(band: CisprBand, note: str) -> DetectorSpectrum:
    z = np.zeros(0)
    return DetectorSpectrum(band.name, z, z, z, z, usable=False, note=note)


def _unusable(band: CisprBand, note: str) -> DetectorReading:
    return DetectorReading(
        band=band.name, f_low=band.f_low, f_high=band.f_high,
        peak_dbuv=float("-inf"), quasi_peak_dbuv=float("-inf"),
        average_dbuv=float("-inf"), usable=False, note=note,
    )


def _band_spectrum(v: np.ndarray, dt: float, band: CisprBand) -> DetectorSpectrum:
    """Per-frequency detector curves for one band, from a resampled trace."""
    n = v.size
    nyquist = 0.5 / dt
    if band.f_low >= nyquist:
        return _empty_spectrum(
            band,
            f"band starts above the simulated Nyquist ({nyquist:.3g} Hz) — "
            "timestep too coarse for this band",
        )

    # STFT window length ~ the receiver dwell that yields this RBW.
    window_len = int(round((1.5 / band.rbw_hz) / dt))
    window_len = max(16, min(window_len, n))
    note = ""
    if window_len >= n:
        window_len = n
        note = (
            "simulation shorter than the receiver dwell window — "
            "QP ≈ peak (conservative estimate)"
        )
    hop = max(1, window_len // 4)
    n_frames = max(1, 1 + (n - window_len) // hop)
    win = np.hanning(window_len)
    wsum = float(np.sum(win)) or 1.0
    freqs = np.fft.rfftfreq(window_len, d=dt)
    f_high_eff = min(band.f_high, nyquist)
    mask = (freqs >= band.f_low) & (freqs <= f_high_eff)
    if not mask.any():
        return _empty_spectrum(band, "no FFT bins fall inside the band")

    envelopes = np.empty((int(mask.sum()), n_frames), dtype=np.float64)
    for i in range(n_frames):
        seg = v[i * hop : i * hop + window_len]
        if seg.size < window_len:
            seg = np.pad(seg, (0, window_len - seg.size))
        seg = (seg - seg.mean()) * win
        mag = np.abs(np.fft.rfft(seg)) * 2.0 / wsum
        envelopes[:, i] = mag[mask]

    peak_lin = envelopes.max(axis=1)
    avg_lin = np.minimum(_avg_meter(envelopes, hop * dt, band.meter_s), peak_lin)
    qp_lin = _qp_meter(envelopes, hop * dt, band.qp_charge_s, band.qp_discharge_s)
    # QP is bounded average ≤ QP ≤ peak (clamp tiny numerical excursions).
    qp_lin = np.clip(qp_lin, avg_lin, peak_lin)

    return DetectorSpectrum(
        band=band.name,
        freq_hz=freqs[mask],
        peak_dbuv=_to_dbuv(peak_lin),
        quasi_peak_dbuv=_to_dbuv(qp_lin),
        average_dbuv=_to_dbuv(avg_lin),
        usable=True,
        note=note,
    )


def compute_detector_spectrum(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    band: CisprBand = CISPR_BAND_B,
    *,
    skip_fraction: float = 0.1,
) -> DetectorSpectrum:
    """Per-frequency peak / quasi-peak / average curves (dBµV) for one
    band — the data behind a detector plot."""
    resampled = _resample(axis_seconds, values_volts, skip_fraction)
    if resampled is None:
        return _empty_spectrum(band, "trace too short / degenerate to analyse")
    v, dt = resampled
    return _band_spectrum(v, dt, band)


def compute_detectors(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    *,
    bands: Sequence[CisprBand] = CONDUCTED_BANDS,
    skip_fraction: float = 0.1,
) -> list[DetectorReading]:
    """Estimate the band-max peak / quasi-peak / average reading (dBµV)
    for each band. One :class:`DetectorReading` per band."""
    resampled = _resample(axis_seconds, values_volts, skip_fraction)
    if resampled is None:
        return [_unusable(b, "trace too short / degenerate to analyse") for b in bands]
    v, dt = resampled

    out: list[DetectorReading] = []
    for band in bands:
        spec = _band_spectrum(v, dt, band)
        if not spec.usable:
            out.append(_unusable(band, spec.note))
            continue
        out.append(DetectorReading(
            band=band.name,
            f_low=band.f_low,
            f_high=band.f_high,
            peak_dbuv=float(spec.peak_dbuv.max()),
            quasi_peak_dbuv=float(spec.quasi_peak_dbuv.max()),
            average_dbuv=float(spec.average_dbuv.max()),
            usable=True,
            note=spec.note,
        ))
    return out


# ──────────────────────────────────────────────────────────────────────────
# Mode 2 — receiver_like_single_frequency
#
# A receiver-bandwidth filter (RBW, e.g. 9 kHz for Band B) centred at a
# chosen frequency → envelope detector → QP charge/discharge → dBµV. This
# is the receiver-like estimate of the concept note §7 / §9.
#
# The meter / indicator stage (τ_indicator) is modelled as a **max-hold**
# of the QP-detector output — the PC-based-receiver equivalent of the
# mechanical meter. A literal τ_indicator (160 ms) low-pass is NOT applied:
# a transient sim is far shorter than 160 ms, so such a filter would not
# settle and would grossly under-read. ``meter_s`` stays band metadata.
# Mode 2 is still a pre-compliance estimate (concept note §12).
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ReceiverReading:
    """A Mode 2 receiver-like quasi-peak result at one centre frequency (dBµV)."""

    band: str
    center_hz: float
    rbw_hz: float
    peak_dbuv: float
    quasi_peak_dbuv: float
    average_dbuv: float
    usable: bool
    note: str = ""
    mode: str = MODE_RECEIVER_LIKE_SINGLE_FREQUENCY
    receiver_filtered: bool = True

    def to_dict(self) -> dict:
        return {
            "band": self.band,
            "center_hz": self.center_hz,
            "rbw_hz": self.rbw_hz,
            "peak_dbuv": self.peak_dbuv,
            "quasi_peak_dbuv": self.quasi_peak_dbuv,
            "average_dbuv": self.average_dbuv,
            "usable": self.usable,
            "mode": self.mode,
            "receiver_filtered": self.receiver_filtered,
            "note": self.note,
        }


def _analytic_spectrum(v: np.ndarray, dt: float) -> tuple[np.ndarray, np.ndarray]:
    """The analytic-signal spectrum of ``v`` — the FFT with negative
    frequencies zeroed and positive ones doubled — plus the frequency
    axis. Computed once; reused for every centre frequency of a sweep."""
    n = v.size
    spectrum = np.fft.fft(v)
    freqs = np.fft.fftfreq(n, d=dt)
    h = np.zeros(n)
    h[0] = 1.0
    if n % 2 == 0:
        h[n // 2] = 1.0
        h[1 : n // 2] = 2.0
    else:
        h[1 : (n + 1) // 2] = 2.0
    return spectrum * h, freqs


def _envelope_at(
    analytic_x: np.ndarray, freqs: np.ndarray, center_hz: float, rbw_hz: float
) -> np.ndarray:
    """Apply a receiver-bandwidth band-pass at ``center_hz`` to a
    precomputed analytic spectrum → the amplitude envelope. The band-pass
    is a Gaussian whose −6 dB full width equals ``rbw_hz``."""
    sigma = (rbw_hz / 2.0) / math.sqrt(2.0 * math.log(2.0))
    mask = np.exp(-((freqs - center_hz) ** 2) / (2.0 * sigma**2))
    return np.abs(np.fft.ifft(analytic_x * mask))


def _band_envelope(
    v: np.ndarray, dt: float, center_hz: float, rbw_hz: float
) -> np.ndarray:
    """Receiver-bandwidth band-pass at ``center_hz`` → amplitude envelope."""
    analytic_x, freqs = _analytic_spectrum(v, dt)
    return _envelope_at(analytic_x, freqs, center_hz, rbw_hz)


def _charge_discharge(
    envelope: np.ndarray,
    dt: float,
    charge_s: float,
    discharge_s: float,
    initial: float = 0.0,
) -> np.ndarray:
    """The quasi-peak detector **core** — an asymmetric charge/discharge
    weighting. It charges fast toward a rising input and discharges slowly
    away from a falling one (``charge_s`` ≪ ``discharge_s``). Returns the
    full meter trajectory, one value per input sample; ``initial`` seeds
    the meter state.

    This is the directly-verifiable core of the detector — see
    ``tests/test_quasi_peak_detector.py``.
    """
    alpha_c = 1.0 - math.exp(-dt / charge_s)
    alpha_d = 1.0 - math.exp(-dt / discharge_s)
    out = np.empty(len(envelope), dtype=np.float64)
    meter = float(initial)
    for i in range(len(envelope)):
        x = float(envelope[i])
        meter += (x - meter) * (alpha_c if x > meter else alpha_d)
        out[i] = meter
    return out


def _charge_discharge_running_max(
    envelope: np.ndarray, dt: float, charge_s: float, discharge_s: float
) -> float:
    """Charge/discharge an envelope time series and return the running
    maximum of the meter (the max-hold indication)."""
    # The envelope is band-limited to ~RBW; decimate (block-max, so peaks
    # survive) to keep the data-dependent charge/discharge loop cheap.
    target_dt = min(charge_s / 40.0, (envelope.size * dt) / 64.0)
    step = max(1, int(round(target_dt / dt)))
    if step > 1:
        trim = (envelope.size // step) * step
        env = envelope[:trim].reshape(-1, step).max(axis=1)
    else:
        env = envelope
    return float(_charge_discharge(env, step * dt, charge_s, discharge_s).max())


def _meter_average(
    envelope: np.ndarray, dt: float, tau: float, initial: float
) -> np.ndarray:
    """The CISPR average detector's averaging stage — a one-pole linear
    low-pass with the meter (indicator) time constant ``tau``. Returns the
    full meter trajectory; ``initial`` seeds the meter state."""
    alpha = 1.0 - math.exp(-dt / tau)
    out = np.empty(len(envelope), dtype=np.float64)
    meter = float(initial)
    for i in range(len(envelope)):
        meter += (float(envelope[i]) - meter) * alpha
        out[i] = meter
    return out


def _meter_average_running_max(
    envelope: np.ndarray, dt: float, tau: float
) -> float:
    """Run the CISPR average-detector meter (a τ_meter linear low-pass)
    over an envelope time series and return its running maximum — the
    max-hold indication a receiver records during a dwell / sweep.

    The meter is **seeded with the envelope mean**: for a transient sim
    far shorter than ``tau`` (e.g. 5 ms vs a 160 ms meter constant) the
    meter barely moves, so the detector degrades gracefully to that mean
    — the correct steady-state average — instead of under-reading from a
    cold (zero) start. For a longer sim that captures an intermittent
    burst the meter rises above the mean toward the burst's local
    average, and the max-hold records it.
    """
    if envelope.size == 0:
        return 0.0
    mean = float(envelope.mean())
    # The envelope is band-limited; decimate by block-MEAN (an average
    # detector must not be biased high by block-max) to keep the loop cheap.
    target_dt = min(tau / 40.0, (envelope.size * dt) / 64.0)
    step = max(1, int(round(target_dt / dt)))
    if step > 1:
        trim = (envelope.size // step) * step
        env = envelope[:trim].reshape(-1, step).mean(axis=1)
    else:
        env = envelope
    if env.size == 0:
        return mean
    return float(_meter_average(env, step * dt, tau, initial=mean).max())


def receiver_quasi_peak(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    center_hz: float,
    band: CisprBand = CISPR_BAND_B,
    *,
    skip_fraction: float = 0.0,
) -> ReceiverReading:
    """Mode 2 — a receiver-like quasi-peak estimate at one centre frequency.

    Passes the waveform through a receiver-bandwidth filter
    (``band.rbw_hz``) centred at ``center_hz``, takes the envelope, and
    applies the QP charge/discharge detector. Returns peak / quasi-peak /
    average in dBµV.

    Still a pre-compliance estimate — see the module docstring and
    ``docs/concepts/quasi_peak_detector_concept.md``.
    """
    def _bad(note: str) -> ReceiverReading:
        return ReceiverReading(
            band=band.name, center_hz=float(center_hz), rbw_hz=band.rbw_hz,
            peak_dbuv=float("-inf"), quasi_peak_dbuv=float("-inf"),
            average_dbuv=float("-inf"), usable=False, note=note,
        )

    resampled = _resample(axis_seconds, values_volts, skip_fraction)
    if resampled is None:
        return _bad("trace too short / degenerate to analyse")
    v, dt = resampled
    nyquist = 0.5 / dt
    if center_hz <= 0 or center_hz >= nyquist:
        return _bad(
            f"centre frequency {center_hz:.3g} Hz is not below the simulated "
            f"Nyquist ({nyquist:.3g} Hz) — timestep too coarse"
        )
    note = ""
    if not (band.f_low <= center_hz <= band.f_high):
        note = (
            f"centre frequency {center_hz:.3g} Hz is outside CISPR band "
            f"{band.name} ({band.f_low:.3g}–{band.f_high:.3g} Hz)"
        )

    envelope = _band_envelope(v, dt, float(center_hz), band.rbw_hz)
    peak = float(envelope.max())
    average = min(_meter_average_running_max(envelope, dt, band.meter_s), peak)
    qp = _charge_discharge_running_max(
        envelope, dt, band.qp_charge_s, band.qp_discharge_s
    )
    qp = min(max(qp, average), peak)  # average ≤ QP ≤ peak
    return ReceiverReading(
        band=band.name,
        center_hz=float(center_hz),
        rbw_hz=band.rbw_hz,
        peak_dbuv=float(_to_dbuv(peak)),
        quasi_peak_dbuv=float(_to_dbuv(qp)),
        average_dbuv=float(_to_dbuv(average)),
        usable=True,
        note=note,
    )


# ──────────────────────────────────────────────────────────────────────────
# Mode 3 — receiver_like_sweep
#
# Mode 2 repeated across many centre frequencies spanning the conducted
# band — a peak / quasi-peak / average spectrum, the closest
# pre-compliance approximation of an EMI-receiver scan. The analytic
# spectrum is computed once; only the receiver-bandwidth band-pass moves.
# Still a pre-compliance estimate (concept note §12).
# ──────────────────────────────────────────────────────────────────────────


@dataclass
class ReceiverSweep:
    """A Mode 3 receiver-like sweep — peak / quasi-peak / average (dBµV)
    at each swept centre frequency."""

    band: str
    freq_hz: np.ndarray
    peak_dbuv: np.ndarray
    quasi_peak_dbuv: np.ndarray
    average_dbuv: np.ndarray
    usable: bool
    note: str = ""
    mode: str = MODE_RECEIVER_LIKE_SWEEP
    receiver_filtered: bool = True


def receiver_sweep(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    band: CisprBand = CISPR_BAND_B,
    *,
    n_points: int = 128,
    skip_fraction: float = 0.0,
) -> ReceiverSweep:
    """Mode 3 — sweep the Mode 2 receiver-like chain across ``n_points``
    log-spaced centre frequencies over ``band``: a receiver-bandwidth
    filter at each → envelope → QP detector → a peak / quasi-peak /
    average spectrum.

    A CISPR-like pre-compliance estimate — see the module docstring.

    NOTE — like a real swept receiver, a sweep whose step is wider than
    the RBW *under-reads narrow tones that fall between swept points*
    (e.g. switching harmonics). The default ``n_points`` is a coarse band
    overview; raise it for finer coverage, or use Mode 1
    (:func:`compute_detector_spectrum`, gap-free) / Mode 2 at a specific
    frequency for accurate per-tone readings. The returned ``note`` flags
    when the step exceeds the RBW.
    """
    empty = np.zeros(0)

    def _bad(note: str) -> ReceiverSweep:
        return ReceiverSweep(
            band=band.name, freq_hz=empty, peak_dbuv=empty,
            quasi_peak_dbuv=empty, average_dbuv=empty, usable=False, note=note,
        )

    resampled = _resample(axis_seconds, values_volts, skip_fraction)
    if resampled is None:
        return _bad("trace too short / degenerate to analyse")
    v, dt = resampled
    nyquist = 0.5 / dt
    if band.f_low >= nyquist:
        return _bad(
            f"band starts above the simulated Nyquist ({nyquist:.3g} Hz) — "
            "timestep too coarse for this band"
        )
    f_high = min(band.f_high, nyquist)
    n = max(2, int(n_points))
    centers = np.logspace(math.log10(band.f_low), math.log10(f_high), n)
    # Pin the endpoints exactly (logspace leaves a float-rounding epsilon).
    centers[0] = band.f_low
    centers[-1] = f_high
    analytic_x, freqs = _analytic_spectrum(v, dt)

    peak = np.empty(n)
    qp = np.empty(n)
    avg = np.empty(n)
    for i, center_hz in enumerate(centers):
        env = _envelope_at(analytic_x, freqs, float(center_hz), band.rbw_hz)
        p = float(env.max())
        a = min(_meter_average_running_max(env, dt, band.meter_s), p)
        q = _charge_discharge_running_max(
            env, dt, band.qp_charge_s, band.qp_discharge_s
        )
        peak[i] = p
        avg[i] = a
        qp[i] = min(max(q, a), p)  # average ≤ QP ≤ peak

    notes: list[str] = []
    if f_high < band.f_high:
        notes.append(
            f"swept only up to the simulated Nyquist ({nyquist:.3g} Hz); "
            "the band's upper frequencies need a finer timestep"
        )
    max_step = float(np.max(np.diff(centers))) if n > 1 else 0.0
    if max_step > band.rbw_hz:
        notes.append(
            f"sweep step reaches {max_step:.3g} Hz, wider than the "
            f"{band.rbw_hz:.0f} Hz RBW — narrow tones between swept points "
            "are under-read; raise n_points for finer coverage"
        )
    note = "; ".join(notes)
    return ReceiverSweep(
        band=band.name,
        freq_hz=centers,
        peak_dbuv=_to_dbuv(peak),
        quasi_peak_dbuv=_to_dbuv(qp),
        average_dbuv=_to_dbuv(avg),
        usable=True,
        note=note,
    )


# ──────────────────────────────────────────────────────────────────────────
# Canonical conducted-EMI verdict detector  (single source of truth)
#
# ONE detector configuration must feed every consumer-facing quasi-peak /
# average margin: the Results verdict pill, the corner-variant table
# (results/metrics.py), the UI spectrum chart (service/raw.py), and the
# report's margin text + plot (reports/detector_plot.py). Routing them all
# through this helper fixes the historical "two detector code paths disagree"
# bug, where the verdict used Mode 1 / skip 0.1 (read ~-26 dB "within") while
# the chart used Mode 3 / skip 0.0 (read ~+13 dB "over") for the same trace.
#
# Canonical choice (user decision, 2026-05-24): Mode 3 (receiver-like sweep),
# no start-skip — the realistic CISPR-receiver emulation (per-frequency RBW),
# over the full window.
#
# The alternatives are kept and documented so the detector can be made
# *user-selectable* later (see docs/concepts/quasi_peak_detector_concept.md
# and tasks/detector_selectable.md):
#   • mode          — Mode 1 time-domain diagnostic (compute_detector_spectrum:
#                     gap-free, no RBW, reads lower) vs Mode 3 receiver-like
#                     sweep (receiver_sweep: RBW per frequency, canonical).
#   • skip_fraction — 0.0 full window (canonical) vs >0 to drop the start-up
#                     transient for a steady-state-only reading. NOTE: on
#                     case_003, raising skip *raised* the Mode-3 reading — a
#                     non-intuitive effect to investigate before exposing skip
#                     as a user knob (see the task file).
# To retune, change the VERDICT_* constants here — never individual call sites.
# ──────────────────────────────────────────────────────────────────────────
VERDICT_DETECTOR_MODE = MODE_RECEIVER_LIKE_SWEEP
VERDICT_SKIP_FRACTION = 0.0
VERDICT_SWEEP_POINTS = 128


def conducted_emi_spectrum(
    axis_seconds: Sequence[float],
    values_volts: Sequence[float],
    band: CisprBand = CISPR_BAND_B,
) -> ReceiverSweep:
    """The canonical conducted-EMI detector spectrum (see the VERDICT_* block).

    All verdict / corner-table / chart / report consumers go through this so
    they cannot disagree. Today it is Mode 3 (receiver-like sweep) with no
    start-skip; thread a config through here (or change VERDICT_*) when the
    detector becomes user-selectable.
    """
    return receiver_sweep(
        axis_seconds,
        values_volts,
        band,
        n_points=VERDICT_SWEEP_POINTS,
        skip_fraction=VERDICT_SKIP_FRACTION,
    )
