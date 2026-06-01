"""Tests for the PDF report export (``emc_assistant.reports.pdf``).

Covers the rendering primitive (`markdown_to_pdf`), the
asset-resolution callback (images embedded from a sibling directory),
and the service-layer integration that flips
:func:`generate_report` on when ``options.pdf`` is True.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("xhtml2pdf")          # the whole file needs the extra

from emc_assistant.reports.pdf import _resolve_relative_assets, markdown_to_pdf
from emc_assistant.service.results import ServiceError


def test_markdown_to_pdf_writes_a_valid_pdf_file(tmp_path: Path):
    """A real PDF starts with ``%PDF-`` and ends with ``%%EOF``. We're
    not parsing the file — just verifying the renderer produced one."""
    md = (
        "# EMC report\n\n"
        "This is a **pre-compliance** engineering aid.\n\n"
        "| Net | R (mΩ) | L (nH) |\n"
        "|---|---|---|\n"
        "| VIN | 18 | 8 |\n"
    )
    out = tmp_path / "report.pdf"
    result = markdown_to_pdf(md, out, title="Test report")
    assert result == out
    assert out.is_file()
    blob = out.read_bytes()
    assert blob.startswith(b"%PDF-")
    assert b"%%EOF" in blob[-256:]


def test_link_callback_rewrites_relative_filename_to_absolute(tmp_path: Path):
    """Verify the asset-resolution closure directly: a bare filename
    that exists in the reports directory must be rewritten to the
    absolute path so xhtml2pdf can find detector plots embedded by
    ``_emi_detector_section``."""
    (tmp_path / "detector_plot_diagnostic.png").write_bytes(b"\x89PNG\r\n")
    cb = _resolve_relative_assets(tmp_path)
    abs_path = cb("detector_plot_diagnostic.png", "")
    assert Path(abs_path) == (tmp_path / "detector_plot_diagnostic.png").resolve()


def test_link_callback_passes_through_absolute_and_external_urls(tmp_path: Path):
    cb = _resolve_relative_assets(tmp_path)
    assert cb("https://example.org/x.png", "") == "https://example.org/x.png"
    assert cb("data:image/png;base64,abc", "") == "data:image/png;base64,abc"
    assert cb("missing.png", "") == "missing.png"   # no rewrite when no file


def test_markdown_to_pdf_missing_xhtml2pdf_raises_service_error(monkeypatch):
    """If the [pdf] extra is absent, the renderer fails fast with a
    user-actionable install hint — never a bare ImportError."""
    import builtins

    real_import = builtins.__import__

    def _fake_import(name, *args, **kwargs):
        if name == "xhtml2pdf" or name.startswith("xhtml2pdf."):
            raise ImportError("simulated missing extra")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fake_import)
    with pytest.raises(ServiceError, match=r"\[pdf\]"):
        markdown_to_pdf("# x", "/tmp/nope.pdf")


# ---- integration with service.report.generate_report -----------------------


def test_generate_report_with_pdf_option_writes_report_pdf(tmp_path: Path):
    """End-to-end check: a deterministic dry-run pipeline + report with
    ``options.pdf=True`` produces ``reports/report.pdf`` and sets
    ``ReportResult.pdf_path``."""
    import shutil

    from emc_assistant.service import report as report_service
    from emc_assistant.service.options import CommandOptions

    examples = Path(__file__).resolve().parents[1] / "examples"
    src = examples / "case_001_buck_conducted_emi"
    if not (src / "project.yaml").is_file():
        pytest.skip("case_001 example not present")
    dst = tmp_path / "case"
    shutil.copytree(src, dst)
    # Drop any pre-existing artefacts so we render from clean state.
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)

    opts = CommandOptions(
        accept_wiring=True, accept_signals=True, accept_parasitics=True,
        pdf=True, html=True,
    )
    result = report_service.generate_report(dst, opts)
    assert result.pdf_path is not None
    assert result.pdf_path.is_file()
    assert result.pdf_path.read_bytes().startswith(b"%PDF-")
    # The HTML report is still produced when both flags are set.
    assert result.html_path is not None and result.html_path.is_file()
