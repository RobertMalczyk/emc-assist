"""Render the CISPR peak / quasi-peak / average detector plot for a run.

Shared by ``scripts/plot_detectors.py`` (CLI) and the report generator
(``service/report.py``). matplotlib is imported **lazily**, so the core
report path does not hard-depend on it: a missing matplotlib — or a run
that cannot be plotted (coarse timestep, missing trace) — degrades to
"no plot", never an error.

The curves are STFT-based engineering estimates (see
``results/detectors.py``), not certified EMI-receiver measurements.
"""

from __future__ import annotations

from pathlib import Path

from emc_assistant.logging_setup import get_logger
from emc_assistant.results import parse_raw
from emc_assistant.results.raw_parser import primary_step_range
from emc_assistant.results.detectors import (
    CISPR_BAND_B,
    VERDICT_SKIP_FRACTION,
    compute_detector_spectrum,
    receiver_sweep,
)
from emc_assistant.results.limits import get_standard, limit_dbuv

_log = get_logger("reports")

PLOT_MODES = ("diagnostic", "receiver")


def render_detector_plot(
    raw_path,
    out_path,
    *,
    trace: str = "V(meas)",
    mode: str = "diagnostic",
    standard_id: str | None = None,
    skip_fraction: float = VERDICT_SKIP_FRACTION,
) -> tuple[bool, str]:
    """Render a CISPR band-B detector plot — peak / quasi-peak / average
    curves plus the standard's quasi-peak + average limit lines — from a
    ``.raw`` file to ``out_path`` (PNG).

    ``mode`` is ``"diagnostic"`` (Mode 1 STFT) or ``"receiver"`` (Mode 3
    receiver-like sweep).

    Returns ``(True, "")`` on success, or ``(False, reason)`` — **without
    raising** — when the run cannot be plotted (matplotlib absent, trace
    missing, band B not resolvable from the timestep, parse error). The
    report generator treats a False as "omit the plot", so a report never
    fails because a plot could not be drawn.
    """
    raw_path, out_path = Path(raw_path), Path(out_path)
    if mode not in PLOT_MODES:
        return False, f"unknown plot mode {mode!r}"

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        return False, "matplotlib is not installed"

    try:
        raw = parse_raw(raw_path)
    except Exception as exc:  # noqa: BLE001 — a plot must never break a report
        return False, f"could not parse {raw_path.name}: {exc}"

    values = raw.traces.get(trace) or raw.traces.get(trace.lower())
    if not values:
        avail = ", ".join(raw.variable_names[1:9])
        return False, f"trace {trace!r} not in the .raw (have: {avail} …)"

    std = get_standard(standard_id)
    if std is None:
        return False, f"unknown compliance standard {standard_id!r}"

    # A stepped .raw (corner sweep) concatenates one transient per corner;
    # the detectors must see a single transient, so restrict to the typ step.
    i0, i1 = primary_step_range(raw.axis)
    axis_seg, values_seg = raw.axis[i0:i1], values[i0:i1]

    if mode == "receiver":
        spec = receiver_sweep(
            axis_seg, values_seg, CISPR_BAND_B, skip_fraction=skip_fraction
        )
    else:
        spec = compute_detector_spectrum(
            axis_seg, values_seg, CISPR_BAND_B, skip_fraction=skip_fraction
        )
    if not spec.usable:
        return False, f"CISPR band B not usable: {spec.note}"

    def _limit_curve(curve) -> "np.ndarray":
        return np.array([
            (v if (v := limit_dbuv(curve, float(f))) is not None else np.nan)
            for f in spec.freq_hz
        ])

    freq_mhz = spec.freq_hz / 1e6
    fig, ax = plt.subplots(figsize=(10.0, 5.5))
    ax.fill_between(
        freq_mhz, spec.average_dbuv, spec.peak_dbuv, color="#3b82f6", alpha=0.08
    )
    ax.plot(
        freq_mhz, spec.peak_dbuv, lw=0.8, color="#ef4444",
        label=f"Peak          (band max {spec.peak_dbuv.max():7.1f} dBµV)",
    )
    ax.plot(
        freq_mhz, spec.quasi_peak_dbuv, lw=1.0, color="#f59e0b",
        label=f"Quasi-peak    (band max {spec.quasi_peak_dbuv.max():7.1f} dBµV)",
    )
    ax.plot(
        freq_mhz, spec.average_dbuv, lw=0.8, color="#22c55e",
        label=f"Average       (band max {spec.average_dbuv.max():7.1f} dBµV)",
    )
    ax.plot(
        freq_mhz, _limit_curve(std.quasi_peak), "--", lw=1.1, color="#a855f7",
        label=f"{std.name} QP limit",
    )
    ax.plot(
        freq_mhz, _limit_curve(std.average), ":", lw=1.1, color="#a855f7",
        label=f"{std.name} avg limit",
    )
    ax.set_xscale("log")
    ax.set_xlabel("Frequency (MHz)")
    ax.set_ylabel("Level (dBµV)")
    ax.set_title(f"CISPR band-B EMI detectors ({mode}) — {trace}", fontsize=10)
    ax.grid(True, which="both", alpha=0.25)
    ax.legend(loc="upper right", fontsize=9, prop={"family": "monospace"})
    fig.text(
        0.01, 0.012,
        "STFT-based engineering estimate from a transient simulation — not a "
        "certified EMI-receiver measurement. Quasi-peak is conservative for "
        "runs shorter than the 160 ms discharge constant.",
        fontsize=7, color="#777",
    )
    fig.tight_layout(rect=(0, 0.04, 1, 1))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, dpi=130)
    plt.close(fig)
    return True, ""
