"""Tests for the HTML report renderer (Markdown → HTML)."""

from __future__ import annotations

import shutil
from pathlib import Path

from emc_assistant.cli import main
from emc_assistant.reports.html import markdown_to_html

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


# ---- markdown_to_html — block types ---------------------------------------


def test_headings():
    html = markdown_to_html("# Title\n\n## Section\n\n### Sub\n")
    assert "<h1>Title</h1>" in html
    assert "<h2>Section</h2>" in html
    assert "<h3>Sub</h3>" in html


def test_inline_bold_italic_code():
    html = markdown_to_html("a **bold** and _ital_ and `code` here\n")
    assert "<strong>bold</strong>" in html
    assert "<em>ital</em>" in html
    assert "<code>code</code>" in html


def test_bullet_list():
    html = markdown_to_html("- one\n- two\n- three\n")
    assert "<ul>" in html and "</ul>" in html
    assert html.count("<li>") == 3


def test_gfm_table():
    md = "| Net | R |\n|-----|---|\n| in | 1m |\n| out | 2m |\n"
    html = markdown_to_html(md)
    assert "<table>" in html
    assert "<th>Net</th>" in html and "<th>R</th>" in html
    assert "<td>in</td>" in html and "<td>2m</td>" in html
    assert html.count("<tr>") == 3  # header + 2 body rows


def test_fenced_code_block():
    html = markdown_to_html("```\nR1 a b 1k\n.tran 0 5m\n```\n")
    assert "<pre><code>" in html
    assert "R1 a b 1k" in html


def test_horizontal_rule_and_blockquote():
    html = markdown_to_html("text\n\n---\n\n> a note\n")
    assert "<hr>" in html
    assert "<blockquote>a note</blockquote>" in html


def test_paragraph():
    html = markdown_to_html("first line\nsecond line\n\nnew para\n")
    assert "<p>first line second line</p>" in html
    assert "<p>new para</p>" in html


def test_html_is_escaped():
    """Raw < > & in the Markdown must not become live HTML."""
    html = markdown_to_html("a < b & c > d\n")
    assert "&lt;" in html and "&amp;" in html and "&gt;" in html
    assert "<p>a < b" not in html


def test_document_wrapper():
    html = markdown_to_html("# x\n", title="EMC report — case_001")
    assert html.startswith("<!DOCTYPE html>")
    assert "<title>EMC report — case_001</title>" in html
    assert "requires verification" in html  # pre-compliance footer
    assert html.rstrip().endswith("</html>")


# ---- CLI integration -------------------------------------------------------


def test_report_generate_html_flag(tmp_path: Path):
    project = tmp_path / "case"
    shutil.copytree(EXAMPLE, project)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(project / sub, ignore_errors=True)
    rc = main(["report", "generate", str(project), "--html"])
    assert rc == 0
    html_path = project / "reports" / "report.html"
    assert html_path.is_file()
    body = html_path.read_text(encoding="utf-8")
    assert body.startswith("<!DOCTYPE html>")
    assert "<h1>" in body
    # The Markdown report is still written alongside.
    assert (project / "reports" / "report.md").is_file()
