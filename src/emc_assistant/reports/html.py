"""HTML report renderer.

The Markdown report (``reports/markdown.py``) is the single source of
truth for report content. This module converts that Markdown to a
styled, standalone HTML document — so there is one report renderer, not
two that can drift apart.

The converter handles the Markdown subset the report generator actually
emits: ``#``–``######`` headings, ``**bold**``, ``_italic_``,
`` `code` ``, ``- `` bullet lists, GFM pipe tables, fenced code blocks,
``---`` rules, ``>`` blockquotes, and blank-line-separated paragraphs.
It is deliberately not a general-purpose Markdown engine — the input is
generated and well-formed.
"""

from __future__ import annotations

import re

_HR = {"---", "***", "___"}
_TABLE_SEP = re.compile(r"^\|?[\s:|-]+\|?$")
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_CODE_SPAN = re.compile(r"`([^`]+)`")
_BOLD = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC = re.compile(r"(?<![A-Za-z0-9`])_([^_]+)_(?![A-Za-z0-9])")
_IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline(text: str) -> str:
    """Escape, then apply inline image / code / bold / italic."""
    out = _escape(text)
    out = _IMAGE.sub(r'<img alt="\1" src="\2">', out)
    out = _CODE_SPAN.sub(r"<code>\1</code>", out)
    out = _BOLD.sub(r"<strong>\1</strong>", out)
    out = _ITALIC.sub(r"<em>\1</em>", out)
    return out


def _is_block_start(line: str) -> bool:
    s = line.strip()
    if not s:
        return True
    return (
        s[0] in "#>|"
        or s in _HR
        or s.startswith("- ")
        or s.startswith("* ")
        or s.startswith("```")
    )


def _render_table(rows: list[str]) -> str:
    """Render a GFM pipe table. ``rows`` is header, separator, then body."""
    def cells(row: str) -> list[str]:
        row = row.strip()
        if row.startswith("|"):
            row = row[1:]
        if row.endswith("|"):
            row = row[:-1]
        return [c.strip() for c in row.split("|")]

    head = cells(rows[0])
    body = [cells(r) for r in rows[2:]]
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in head]
    out.append("</tr></thead>")
    out.append("<tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def markdown_to_html(md: str, *, title: str = "EMC report") -> str:
    """Convert the generated Markdown report to a standalone HTML document."""
    lines = md.splitlines()
    html: list[str] = []
    in_list = False
    i = 0

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html.append("</ul>")
            in_list = False

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # Fenced code block.
        if stripped.startswith("```"):
            close_list()
            i += 1
            buf: list[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                buf.append(_escape(lines[i]))
                i += 1
            i += 1  # closing fence
            html.append("<pre><code>" + "\n".join(buf) + "</code></pre>")
            continue

        # GFM table — current line and a separator row both pipe-shaped.
        if (
            stripped.startswith("|")
            and i + 1 < len(lines)
            and _TABLE_SEP.match(lines[i + 1].strip())
        ):
            close_list()
            tbl: list[str] = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                tbl.append(lines[i])
                i += 1
            html.append(_render_table(tbl))
            continue

        m = _HEADING.match(stripped)
        if m:
            close_list()
            lvl = len(m.group(1))
            html.append(f"<h{lvl}>{_inline(m.group(2))}</h{lvl}>")
            i += 1
            continue

        if stripped in _HR:
            close_list()
            html.append("<hr>")
            i += 1
            continue

        if stripped.startswith("- ") or stripped.startswith("* "):
            if not in_list:
                html.append("<ul>")
                in_list = True
            html.append(f"<li>{_inline(stripped[2:])}</li>")
            i += 1
            continue

        if stripped.startswith(">"):
            close_list()
            html.append(f"<blockquote>{_inline(stripped[1:].strip())}</blockquote>")
            i += 1
            continue

        if not stripped:
            close_list()
            i += 1
            continue

        # Paragraph — gather consecutive plain lines.
        close_list()
        para: list[str] = []
        while i < len(lines) and lines[i].strip() and not _is_block_start(lines[i]):
            para.append(lines[i].strip())
            i += 1
        html.append(f"<p>{_inline(' '.join(para))}</p>")

    close_list()
    return _document(title, "\n".join(html))


_CSS = """
:root { color-scheme: light dark; }
body { font: 15px/1.6 -apple-system, Segoe UI, Roboto, sans-serif;
       max-width: 920px; margin: 2rem auto; padding: 0 1.2rem; color: #1a1a1a; }
h1, h2, h3, h4 { line-height: 1.25; margin-top: 1.8rem; }
h1 { border-bottom: 2px solid #c92a7a; padding-bottom: .3rem; }
h2 { border-bottom: 1px solid #ddd; padding-bottom: .2rem; }
code { background: #f0f0f3; padding: .1rem .3rem; border-radius: 3px;
       font-size: .9em; }
pre { background: #f6f6f8; padding: .8rem 1rem; overflow-x: auto;
      border-radius: 5px; border: 1px solid #e3e3e8; }
pre code { background: none; padding: 0; }
table { border-collapse: collapse; width: 100%; margin: 1rem 0; font-size: .92em; }
th, td { border: 1px solid #d4d4d8; padding: .35rem .6rem; text-align: left; }
th { background: #f3f3f6; }
blockquote { border-left: 3px solid #c92a7a; margin: 1rem 0; padding: .2rem 1rem;
             background: #faf2f6; color: #444; }
img { max-width: 100%; height: auto; display: block; margin: 1rem 0;
      border: 1px solid #e3e3e8; border-radius: 5px; }
hr { border: none; border-top: 1px solid #ddd; margin: 1.6rem 0; }
.report-footer { margin-top: 2.5rem; padding-top: .8rem; border-top: 1px solid #ddd;
                 color: #888; font-size: .85em; }
"""


def _document(title: str, body: str) -> str:
    return (
        "<!DOCTYPE html>\n"
        '<html lang="en">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"<title>{_escape(title)}</title>\n"
        f"<style>{_CSS}</style>\n</head>\n<body>\n"
        f"{body}\n"
        '<p class="report-footer">Pre-compliance engineering aid — every '
        "result is a hypothesis that requires verification. Generated by "
        "emc-assistant.</p>\n"
        "</body>\n</html>\n"
    )
