"""Plot the CISPR peak / quasi-peak / average EMI detectors for a run.

Usage:
    python scripts/plot_detectors.py <project-or-raw> [--trace V(meas)]
                                     [--out PATH] [--skip 0.0]
                                     [--mode diagnostic|receiver]
                                     [--standard en55022_class_b]

``<project-or-raw>`` is either an ``.emcproj`` directory (uses
``generated/testbench.raw``) or a direct path to a ``.raw`` file.

Produces a band-B (150 kHz – 30 MHz) plot with the three detector
curves vs frequency plus the standard's limit lines. The rendering is
shared with the report generator — see
``src/emc_assistant/reports/detector_plot.py``. The curves are STFT-based
**engineering estimates**, not certified EMI-receiver measurements.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emc_assistant.reports.detector_plot import render_detector_plot  # noqa: E402


def _safe(name: str) -> str:
    return "".join(c if c.isalnum() else "_" for c in name.lower()).strip("_")


def _resolve_raw(arg: str) -> Path:
    p = Path(arg)
    if p.is_dir():
        cand = p / "generated" / "testbench.raw"
        if not cand.is_file():
            raise SystemExit(
                f"No testbench.raw under {p / 'generated'} — run "
                "`testbench compose` + `simulate run` first."
            )
        return cand
    if p.is_file():
        return p
    raise SystemExit(f"Not found: {arg}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Plot peak / quasi-peak / average EMI detectors."
    )
    ap.add_argument("project_or_raw", help=".emcproj directory or a .raw file")
    ap.add_argument("--trace", default="V(meas)", help="Trace name (default: V(meas))")
    ap.add_argument("--out", default=None, help="Output PNG path")
    ap.add_argument(
        "--skip", type=float, default=0.0,
        help="Fraction of the startup transient to skip (default: 0.0)",
    )
    ap.add_argument(
        "--standard", default=None,
        help="Compliance limit-line standard (default: en55022_class_b)",
    )
    ap.add_argument(
        "--mode", choices=("diagnostic", "receiver"), default="diagnostic",
        help="diagnostic = Mode 1 STFT; receiver = Mode 3 receiver-like sweep",
    )
    args = ap.parse_args(argv)

    raw_path = _resolve_raw(args.project_or_raw)
    out = (
        Path(args.out)
        if args.out
        else raw_path.parent.parent / "reports" / f"detectors_{_safe(args.trace)}.png"
    )
    ok, detail = render_detector_plot(
        raw_path, out,
        trace=args.trace, mode=args.mode,
        standard_id=args.standard, skip_fraction=args.skip,
    )
    if not ok:
        raise SystemExit(detail)
    print(f"Wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
