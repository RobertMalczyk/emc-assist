"""HTML → PDF report export.

Reuses the same Markdown → HTML pipeline as the on-disk HTML report
(``reports/html.py``) and runs the result through ``xhtml2pdf`` to
produce a static PDF that travels offline.

``xhtml2pdf`` is a **pure-Python** renderer — no system binary, no
Chromium / wkhtmltopdf — so the PDF dependency is `pip install`-able
on every platform we ship. The trade-off is that CSS support is
limited compared to a real browser: block layouts and tables work,
modern flex / grid don't. Adequate for the report's headings, tables,
pre-blocks, and blockquotes.

The module is import-safe even when ``xhtml2pdf`` is **not** installed:
the renderer is imported lazily inside :func:`markdown_to_pdf` and the
function raises a :class:`ServiceError` with an install hint when the
``[pdf]`` extra is missing. The rest of the package never hard-depends
on it.
"""

from __future__ import annotations

import io
from pathlib import Path

from emc_assistant.reports.html import markdown_to_html
from emc_assistant.service.results import ServiceError


def markdown_to_pdf(
    md: str, out_path, *, title: str = "EMC report"
) -> Path:
    """Render ``md`` (the report's Markdown source) to ``out_path``.

    Returns the absolute output path on success. Raises
    :class:`ServiceError` when ``xhtml2pdf`` is missing or the renderer
    reports errors — surface that to the caller so the run fails
    cleanly instead of producing a corrupt PDF."""
    try:
        from xhtml2pdf import pisa
    except ImportError as exc:
        raise ServiceError(
            "PDF report export requires the `[pdf]` extra:\n"
            "  pip install 'emc-assistant[pdf]'"
        ) from exc

    html = markdown_to_html(md, title=title)
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    buf = io.BytesIO()
    status = pisa.CreatePDF(
        src=html, dest=buf, link_callback=_resolve_relative_assets(out.parent),
    )
    if status.err:
        raise ServiceError(
            f"PDF rendering reported {status.err} error(s); the report's "
            "HTML contains CSS xhtml2pdf cannot handle."
        )
    out.write_bytes(buf.getvalue())
    return out


def _resolve_relative_assets(reports_dir: Path):
    """xhtml2pdf needs absolute paths for ``<img>`` / linked assets. The
    report's images (detector plots) live as siblings of ``report.md`` in
    ``reports/`` and the HTML references them by bare filename — map
    those back to absolute paths so the PDF embeds them."""

    def _link_callback(uri: str, _rel: str) -> str:
        if uri.startswith(("http://", "https://", "data:", "file://")):
            return uri
        candidate = (reports_dir / uri).resolve()
        if candidate.is_file():
            return str(candidate)
        return uri

    return _link_callback
