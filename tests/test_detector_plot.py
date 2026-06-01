"""Tests for the detector-vs-limit plot embedded in the report.

Covers the three pieces of the feature: ``render_detector_plot`` (the
shared rendering used by both ``scripts/plot_detectors.py`` and the
report generator), the Markdown embed in the EMI-detector section, and
the HTML renderer's ``<img>`` support.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

# The whole file needs matplotlib (a declared dependency); skip cleanly
# in a bare environment rather than reporting spurious failures.
pytest.importorskip("matplotlib")

from emc_assistant.reports.detector_plot import render_detector_plot
from emc_assistant.reports.html import markdown_to_html
from emc_assistant.reports.markdown import _emi_detector_section


def _write_raw(path: Path, dt: float, n: int, freq_hz: float,
               trace: str = "V(meas)") -> Path:
    """Write a synthetic ASCII ``.raw`` — one sine trace at ``freq_hz``."""
    t = np.arange(n) * dt
    v = np.sin(2.0 * np.pi * freq_hz * t)
    header = (
        "Title: * synthetic\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 2\n"
        f"No. Points: {n}\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        f"\t1\t{trace}\tvoltage\n"
        "Values:\n"
    )
    body: list[str] = []
    for i in range(n):
        body.append(f"{i}\t{t[i]}")
        body.append(f"\t{v[i]}")
    path.write_text(header + "\n".join(body) + "\n", encoding="utf-8")
    return path


# ---- render_detector_plot --------------------------------------------------


def test_render_rejects_an_unknown_mode(tmp_path: Path):
    ok, detail = render_detector_plot(
        tmp_path / "x.raw", tmp_path / "o.png", mode="bogus"
    )
    assert ok is False
    assert "mode" in detail


def test_render_reports_a_missing_trace(tmp_path: Path):
    raw = _write_raw(tmp_path / "r.raw", 5e-9, 2048, 1e6, trace="V(other)")
    ok, detail = render_detector_plot(raw, tmp_path / "o.png", trace="V(meas)")
    assert ok is False
    assert "trace" in detail


def test_render_reports_a_band_too_coarse_to_resolve(tmp_path: Path):
    """A 100 us timestep (5 kHz Nyquist) cannot resolve CISPR band B —
    render must decline gracefully, not raise."""
    raw = _write_raw(tmp_path / "r.raw", 100e-6, 64, 1e3)
    ok, detail = render_detector_plot(raw, tmp_path / "o.png")
    assert ok is False
    assert "band B not usable" in detail


def test_render_diagnostic_mode_writes_a_png(tmp_path: Path):
    raw = _write_raw(tmp_path / "r.raw", 5e-9, 2048, 1e6)
    out = tmp_path / "detector.png"
    ok, detail = render_detector_plot(raw, out, mode="diagnostic")
    assert ok is True, detail
    assert out.is_file() and out.stat().st_size > 0


def test_render_receiver_mode_writes_a_png(tmp_path: Path):
    raw = _write_raw(tmp_path / "r.raw", 5e-9, 2048, 1e6)
    out = tmp_path / "detector.png"
    ok, detail = render_detector_plot(raw, out, mode="receiver")
    assert ok is True, detail
    assert out.is_file()


# ---- Markdown embed in the EMI-detector section ----------------------------


def _measurements_with_band_readings() -> list[dict]:
    return [{
        "label": "baseline",
        "metrics": {"v_meas_band_quasi_peak_dbuv_150000_30000000": 60.0},
    }]


def test_emi_detector_section_embeds_each_plot(tmp_path: Path):
    lines = _emi_detector_section(
        _measurements_with_band_readings(),
        [("Diagnostic plot", "detector_plot_diagnostic.png"),
         ("Receiver plot", "detector_plot_receiver.png")],
    )
    text = "\n".join(lines)
    assert "**Diagnostic plot**" in text
    assert "![Diagnostic plot](detector_plot_diagnostic.png)" in text
    assert "![Receiver plot](detector_plot_receiver.png)" in text


def test_emi_detector_section_without_plots_embeds_no_image():
    text = "\n".join(_emi_detector_section(_measurements_with_band_readings(), None))
    assert "## EMI detector" in text
    assert "![" not in text


# ---- HTML renderer image support -------------------------------------------


def test_markdown_image_renders_as_img_tag():
    html = markdown_to_html("![a detector plot](detector_plot_diagnostic.png)")
    assert '<img alt="a detector plot" src="detector_plot_diagnostic.png">' in html


def test_html_renderer_still_escapes_plain_text():
    # The image rule must not disturb ordinary inline rendering.
    html = markdown_to_html("**bold** and `code`")
    assert "<strong>bold</strong>" in html
    assert "<code>code</code>" in html
