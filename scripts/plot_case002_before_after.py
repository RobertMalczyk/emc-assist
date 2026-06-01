"""Before/after comparison plots for case_002 ADM1281-3 hot-swap.

Before: ``testbench.raw`` (baseline pipeline output, no mitigation).
After:  ``testbench_damped.raw`` (manually-injected RC damper on the
        DUT input rail, following the filtering agent's M2.9 proposal).

Both .raw files contain three ``.step sweep_corner`` segments (min/typ/max
parasitic corners); we plot the typ corner only — the segment that
matches the agents' analysis input.

Outputs PNG plots to ``examples/case_002_DCDC/reports/``:

- ``case_002_before_after_time.png`` — V(DM) and V(CM) time series.
- ``case_002_before_after_spectrum.png`` — FFT in dBµV vs frequency.
"""

from __future__ import annotations

import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np

# Make Windows console cope with µ / Ω etc. when run standalone.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

from emc_assistant.results import parse_raw
from emc_assistant.results.spectrum import compute_spectrum


REPO_ROOT = Path(__file__).resolve().parents[1]
CASE_DIR = REPO_ROOT / "examples" / "case_002_DCDC"
GEN_DIR = CASE_DIR / "generated"
REPORTS_DIR = CASE_DIR / "reports"


def _typ_segment(axis: list[float], trace: list[float]) -> tuple[np.ndarray, np.ndarray]:
    """Return the typ-corner segment (indices [N..2N) for a 3-step .raw)."""
    axis_arr = np.asarray(axis, dtype=float)
    trace_arr = np.asarray(trace, dtype=float)
    # Detect segment boundaries by monotonicity drops.
    boundaries = [0]
    for i in range(1, len(axis_arr)):
        if axis_arr[i] < axis_arr[i - 1]:
            boundaries.append(i)
    boundaries.append(len(axis_arr))
    if len(boundaries) - 1 == 3:
        # 3-segment .step: pick the middle (typ corner).
        start, end = boundaries[1], boundaries[2]
    else:
        start, end = boundaries[0], boundaries[1]
    return axis_arr[start:end], trace_arr[start:end]


def _load(raw_path: Path) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    raw = parse_raw(raw_path)
    out: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    for key in ("V(dm)", "V(cm)", "V(meas_p)", "V(meas_n)"):
        if key not in raw.traces:
            continue
        out[key] = _typ_segment(raw.axis, raw.traces[key])
    return out


def _plot_time(before: dict, after: dict, out_path: Path) -> None:
    """4-panel layout: DM full + DM zoom (0–5 ms) + CM full + CM zoom."""
    fig, axes = plt.subplots(2, 2, figsize=(13, 7))
    t_b, dm_b = before["V(dm)"]
    t_a, dm_a = after["V(dm)"]
    t_b_cm, cm_b = before["V(cm)"]
    t_a_cm, cm_a = after["V(cm)"]

    def _draw(ax, t_before, y_before, t_after, y_after, title, ylabel, xlim=None):
        ax.plot(t_before * 1e3, y_before, label="Before (baseline)", color="#d62728", linewidth=1.0)
        ax.plot(t_after * 1e3, y_after, label="After (RC damper)", color="#2ca02c", linewidth=1.0)
        if xlim:
            ax.set_xlim(xlim)
        ax.set_title(title, fontsize=10)
        ax.set_ylabel(ylabel)
        ax.grid(True, alpha=0.3)
        ax.legend(loc="upper right", fontsize=8)

    _draw(axes[0, 0], t_b, dm_b, t_a, dm_a, "V(DM) — full 250 ms", "V(DM)  [V]")
    _draw(axes[0, 1], t_b, dm_b, t_a, dm_a, "V(DM) — zoom 0–5 ms (hot-swap turn-on)", "V(DM)  [V]", xlim=(0, 5))
    axes[1, 0].set_xlabel("Time  [ms]")
    axes[1, 1].set_xlabel("Time  [ms]")
    _draw(axes[1, 0], t_b_cm, cm_b, t_a_cm, cm_a, "V(CM) — full 250 ms", "V(CM)  [V]")
    _draw(axes[1, 1], t_b_cm, cm_b, t_a_cm, cm_a, "V(CM) — zoom 0–5 ms", "V(CM)  [V]", xlim=(0, 5))

    fig.suptitle(
        "case_002 ADM1281-3 hot-swap — before/after RC input-damper "
        "(R_damp = 0.5 Ω, C_damp = 10 µF)",
        fontsize=11,
    )
    fig.text(
        0.5,
        0.005,
        "Mitigation = filtering agent's M2.9 proposal, manually injected and re-simulated on real LTspice 26.0.2.  "
        "Hot-swap turn-on is the dominant DM event; the damper reduces V(DM) peak from 17.02 V to 2.70 V (-84%).",
        ha="center",
        fontsize=8,
        color="#555",
    )
    fig.tight_layout(rect=[0, 0.02, 1, 0.96])
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def _plot_spectrum(before: dict, after: dict, out_path: Path) -> None:
    """FFT spectrum of V(DM) and V(CM), dBµV vs Hz."""
    fig, axes = plt.subplots(2, 1, figsize=(11, 7), sharex=True)

    # V(DM) spectrum
    ax = axes[0]
    t_b, dm_b = before["V(dm)"]
    t_a, dm_a = after["V(dm)"]
    spec_before = compute_spectrum(t_b, dm_b, skip_fraction=0.05)
    spec_after = compute_spectrum(t_a, dm_a, skip_fraction=0.05)
    ax.semilogx(
        spec_before.freq_hz,
        spec_before.magnitude_dbuv,
        label=f"Before (Nyquist {spec_before.nyquist_hz:.3g} Hz)",
        color="#d62728",
        linewidth=0.9,
    )
    ax.semilogx(
        spec_after.freq_hz,
        spec_after.magnitude_dbuv,
        label=f"After (Nyquist {spec_after.nyquist_hz:.3g} Hz)",
        color="#2ca02c",
        linewidth=0.9,
    )
    # Mark the CISPR conducted-band edges for orientation.
    ax.axvspan(150_000, 30_000_000, alpha=0.07, color="#1f77b4", label="CISPR conducted band (150 kHz – 30 MHz)")
    ax.set_ylabel("V(DM)  [dBµV]")
    ax.set_title("Differential-mode spectrum — typ corner")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="upper right", fontsize=8)

    # V(CM) spectrum
    ax = axes[1]
    t_b, cm_b = before["V(cm)"]
    t_a, cm_a = after["V(cm)"]
    spec_before = compute_spectrum(t_b, cm_b, skip_fraction=0.05)
    spec_after = compute_spectrum(t_a, cm_a, skip_fraction=0.05)
    ax.semilogx(spec_before.freq_hz, spec_before.magnitude_dbuv, label="Before", color="#d62728", linewidth=0.9)
    ax.semilogx(spec_after.freq_hz, spec_after.magnitude_dbuv, label="After", color="#2ca02c", linewidth=0.9)
    ax.axvspan(150_000, 30_000_000, alpha=0.07, color="#1f77b4")
    ax.set_ylabel("V(CM)  [dBµV]")
    ax.set_xlabel("Frequency  [Hz]")
    ax.set_title("Common-mode spectrum — typ corner")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(loc="upper right", fontsize=8)

    fig.suptitle(
        "case_002 ADM1281-3 hot-swap — FFT spectrum before vs after RC input damper",
        fontsize=11,
    )
    fig.text(
        0.5,
        0.005,
        "Honest Nyquist note: simulation uses a 100 µs max-step (chosen for the 250 ms hot-swap window), "
        "so the spectrum is only valid up to ~5 kHz — well below the CISPR 150 kHz lower edge. "
        "The shaded band shows where conducted-EMI compliance would be evaluated *if* the timestep were finer; "
        "this run cannot speak to it.",
        ha="center",
        fontsize=8,
        color="#555",
        wrap=True,
    )
    fig.tight_layout(rect=[0, 0.04, 1, 0.96])
    fig.savefig(out_path, dpi=130)
    plt.close(fig)


def _peak_table(before: dict, after: dict) -> str:
    lines = ["| Metric | Before (baseline) | After (RC damper) | Δ |", "|---|---:|---:|---:|"]
    for key, label in (("V(dm)", "V(DM) peak  [V]"), ("V(cm)", "V(CM) peak  [V]")):
        _, b = before[key]
        _, a = after[key]
        bpk = float(np.abs(b).max())
        apk = float(np.abs(a).max())
        delta = apk - bpk
        lines.append(f"| {label} | {bpk:.4g} | {apk:.4g} | {delta:+.4g} |")
        rms_b = float(np.sqrt(np.mean(b ** 2)))
        rms_a = float(np.sqrt(np.mean(a ** 2)))
        lines.append(
            f"| {label.replace('peak', 'rms')} | {rms_b:.4g} | {rms_a:.4g} | {rms_a - rms_b:+.4g} |"
        )
    return "\n".join(lines)


def main() -> int:
    before_path = GEN_DIR / "testbench.raw"
    after_path = GEN_DIR / "testbench_damped.raw"
    if not before_path.is_file() or not after_path.is_file():
        print(f"Missing .raw inputs. Need {before_path} and {after_path}.")
        return 1
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    before = _load(before_path)
    after = _load(after_path)
    if "V(dm)" not in before or "V(dm)" not in after:
        print("Missing V(dm) trace — was the dual-LISN composer used?")
        return 1

    time_png = REPORTS_DIR / "case_002_before_after_time.png"
    freq_png = REPORTS_DIR / "case_002_before_after_spectrum.png"
    _plot_time(before, after, time_png)
    _plot_spectrum(before, after, freq_png)

    print(f"Wrote {time_png}")
    print(f"Wrote {freq_png}")
    print()
    print("Peak/RMS comparison (typ corner):")
    print(_peak_table(before, after))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
