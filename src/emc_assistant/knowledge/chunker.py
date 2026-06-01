"""Chunkers for `.md`, `.txt`, `.html`, `.jsonl`, and (optional) `.pdf`.

Each chunker turns one source file into a list of `Chunk` dataclasses
that conform to `schemas/chunk_index.schema.json`. The chunks become
the rows of `knowledge/processed/chunks.jsonl`; their embeddings (same
order) live in `embeddings.npy`.

Design notes:
- Heading-aware splits for `.md` so retrieval can ground citations on a
  named section.
- Paragraph-aware splits for `.txt` / `.html` with a soft 800-character
  cap so embeddings stay coherent.
- For `.jsonl` (the seed rule files) every record becomes one chunk —
  the curated rules already have the right granularity.
- PDF extraction is gated behind the `[pdf]` extra (pdfminer.six).
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable


SOFT_CHUNK_CHAR_LIMIT = 800
"""Target maximum chunk size for prose. Hard limit is 1.5×."""


@dataclass
class Chunk:
    chunk_id: str
    tier: str  # seed | raw_sources | user_private_sources | licensed_sources
    source_id: str
    source_path: str
    source_type: str  # md | txt | html | jsonl | pdf
    text: str
    rule_id: str = ""
    title: str = ""
    tags: list[str] = field(default_factory=list)
    allowed_use: str = ""
    summary: str = ""
    checksum: str = ""

    def to_jsonl_dict(self) -> dict:
        out = {
            "chunk_id": self.chunk_id,
            "tier": self.tier,
            "source_id": self.source_id,
            "source_path": self.source_path,
            "source_type": self.source_type,
            "text": self.text,
        }
        if self.rule_id:
            out["rule_id"] = self.rule_id
        if self.title:
            out["title"] = self.title
        if self.tags:
            out["tags"] = list(self.tags)
        if self.allowed_use:
            out["allowed_use"] = self.allowed_use
        if self.summary:
            out["summary"] = self.summary
        if self.checksum:
            out["checksum"] = self.checksum
        return out


def file_checksum(path: Path) -> str:
    """SHA-256 of the file contents."""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for buf in iter(lambda: fh.read(65536), b""):
            h.update(buf)
    return h.hexdigest()


def _truncate(text: str, limit: int = SOFT_CHUNK_CHAR_LIMIT) -> list[str]:
    """Split overlong text on paragraph boundaries; hard-cut as fallback."""
    if len(text) <= int(limit * 1.5):
        return [text]
    parts: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        if not paragraph.strip():
            continue
        if len(current) + len(paragraph) + 2 > limit and current:
            parts.append(current.strip())
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip() if current else paragraph
    if current:
        parts.append(current.strip())
    # Hard-cut anything still over the limit.
    out: list[str] = []
    for part in parts:
        if len(part) <= int(limit * 1.5):
            out.append(part)
        else:
            for i in range(0, len(part), limit):
                out.append(part[i : i + limit])
    return out


def _strip_html(html: str) -> str:
    """Minimal HTML tag stripping — no external deps."""
    no_scripts = re.sub(r"<(script|style).*?</\1>", " ", html, flags=re.DOTALL | re.IGNORECASE)
    no_tags = re.sub(r"<[^>]+>", " ", no_scripts)
    return re.sub(r"\s+", " ", no_tags).strip()


# ---------- Per-source-type chunkers ----------

def chunk_jsonl_rules(
    path: Path,
    *,
    tier: str,
    source_id_default: str = "",
) -> list[Chunk]:
    """One chunk per record in a curated rules `.jsonl`.

    Recognises both shapes used by the seed: parasitic rules
    (uppercase keys: `Rule_ID`, `Source_IDs`, `Default_value_for_agent`)
    and EMC rules (lowercase keys: `rule_id`, `source_ids`).
    """
    chunks: list[Chunk] = []
    checksum = file_checksum(path)
    seen_ids: set[str] = set()
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            rule_id = str(rec.get("Rule_ID") or rec.get("rule_id") or "").strip()
            if not rule_id:
                continue
            # Sources field varies: "S004, S022" vs list.
            sources_field = rec.get("Source_IDs") or rec.get("source_ids") or ""
            if isinstance(sources_field, list):
                source_ids = [str(s).strip() for s in sources_field if str(s).strip()]
            else:
                source_ids = [s.strip() for s in str(sources_field).split(",") if s.strip()]
            primary_source = source_ids[0] if source_ids else source_id_default

            # Build text body: include the rule's curated fields so the
            # embedding captures the semantics. NEVER include source URLs
            # or vendor body content — those don't belong in the index.
            parts: list[str] = []
            if rec.get("Domain"):
                parts.append(f"Domain: {rec['Domain']}")
            if rec.get("Structure"):
                parts.append(f"Structure: {rec['Structure']}")
            if rec.get("Parasitic"):
                parts.append(f"Parasitic: {rec['Parasitic']}")
            if rec.get("Default_value_for_agent"):
                parts.append(f"Default value: {rec['Default_value_for_agent']}")
            if rec.get("Range_or_sensitivity"):
                parts.append(f"Range: {rec['Range_or_sensitivity']}")
            if rec.get("Formula_or_method"):
                parts.append(f"Formula: {rec['Formula_or_method']}")
            if rec.get("Use_when"):
                parts.append(f"Use when: {rec['Use_when']}")
            if rec.get("Inputs_needed"):
                parts.append(f"Inputs: {rec['Inputs_needed']}")
            if rec.get("LTspice_representation"):
                parts.append(f"SPICE: {rec['LTspice_representation']}")
            if rec.get("Confidence"):
                parts.append(f"Confidence: {rec['Confidence']}")
            # EMC rule shape:
            if rec.get("area"):
                parts.append(f"Area: {rec['area']}")
            if rec.get("rule"):
                parts.append(f"Rule: {rec['rule']}")
            if rec.get("rationale"):
                parts.append(f"Rationale: {rec['rationale']}")
            if rec.get("agent_action"):
                parts.append(f"Agent action: {rec['agent_action']}")

            text = " — ".join(parts)
            summary = (
                f"{rec.get('Structure') or rec.get('area') or ''} / "
                f"{rec.get('Parasitic') or ''}".strip(" /")
            ) or (rec.get("rule") or text[:120])

            tags: list[str] = []
            if rec.get("Domain"):
                tags.extend(re.findall(r"[A-Za-z][A-Za-z\-]+", str(rec["Domain"])))
            if rec.get("area"):
                tags.extend(re.findall(r"[A-Za-z][A-Za-z\-]+", str(rec["area"])))

            cid = f"{tier}:{primary_source}:{rule_id}:{line_no}"
            if cid in seen_ids:
                cid = f"{cid}-{len(seen_ids)}"
            seen_ids.add(cid)

            chunks.append(
                Chunk(
                    chunk_id=cid,
                    tier=tier,
                    source_id=primary_source,
                    source_path=str(path),
                    source_type="jsonl",
                    text=text,
                    rule_id=rule_id,
                    title=summary,
                    tags=tags,
                    summary=summary,
                    checksum=checksum,
                )
            )
    return chunks


def chunk_markdown(
    path: Path,
    *,
    tier: str,
    source_id: str = "",
) -> list[Chunk]:
    """Heading-aware markdown chunker — one chunk per `## ` section."""
    text = path.read_text(encoding="utf-8")
    checksum = file_checksum(path)
    # Strip code fences for cleaner chunk text (the original is on disk).
    # Split on `## ` headings.
    lines = text.splitlines()
    current_title = ""
    current_body: list[str] = []
    sections: list[tuple[str, str]] = []  # (title, body)

    for line in lines:
        if re.match(r"^##\s+", line):
            if current_title or current_body:
                sections.append((current_title, "\n".join(current_body).strip()))
            current_title = re.sub(r"^##\s+", "", line).strip()
            current_body = []
        else:
            current_body.append(line)
    if current_title or current_body:
        sections.append((current_title, "\n".join(current_body).strip()))

    # If there's no `## ` heading, treat the whole file as one section.
    if not sections or (len(sections) == 1 and not sections[0][1]):
        sections = [(path.stem, text.strip())]

    chunks: list[Chunk] = []
    seq = 0
    for title, body in sections:
        if not body.strip():
            continue
        for piece in _truncate(body):
            seq += 1
            cid = f"{tier}:{source_id or path.stem}:{seq}"
            chunks.append(
                Chunk(
                    chunk_id=cid,
                    tier=tier,
                    source_id=source_id or path.stem,
                    source_path=str(path),
                    source_type="md",
                    text=piece,
                    title=title,
                    summary=title or piece[:120],
                    checksum=checksum,
                )
            )
    return chunks


def chunk_text(
    path: Path,
    *,
    tier: str,
    source_id: str = "",
    source_type: str = "txt",
) -> list[Chunk]:
    """Paragraph-aware chunker for `.txt` and stripped `.html`."""
    raw = path.read_text(encoding="utf-8")
    checksum = file_checksum(path)
    body = _strip_html(raw) if source_type == "html" else raw
    chunks: list[Chunk] = []
    for seq, piece in enumerate(_truncate(body), start=1):
        if not piece.strip():
            continue
        cid = f"{tier}:{source_id or path.stem}:{seq}"
        chunks.append(
            Chunk(
                chunk_id=cid,
                tier=tier,
                source_id=source_id or path.stem,
                source_path=str(path),
                source_type=source_type,
                text=piece,
                title=path.stem,
                summary=piece[:120],
                checksum=checksum,
            )
        )
    return chunks


def chunk_pdf(
    path: Path,
    *,
    tier: str,
    source_id: str = "",
) -> list[Chunk]:
    """PDF chunker — requires the `[pdf]` optional extra (pdfminer.six)."""
    try:
        from pdfminer.high_level import extract_text  # type: ignore
    except ImportError as exc:  # pragma: no cover - tested via the friendly error
        raise RuntimeError(
            "PDF ingest requires the `[pdf]` extra. Install with: "
            "pip install 'emc-assistant[pdf]'"
        ) from exc
    body = extract_text(str(path))
    checksum = file_checksum(path)
    chunks: list[Chunk] = []
    for seq, piece in enumerate(_truncate(body), start=1):
        if not piece.strip():
            continue
        cid = f"{tier}:{source_id or path.stem}:{seq}"
        chunks.append(
            Chunk(
                chunk_id=cid,
                tier=tier,
                source_id=source_id or path.stem,
                source_path=str(path),
                source_type="pdf",
                text=piece,
                title=path.stem,
                summary=piece[:120],
                checksum=checksum,
            )
        )
    return chunks


# ---------- File-walk dispatcher ----------

_EXTENSION_DISPATCH = {
    ".md": "md",
    ".txt": "txt",
    ".html": "html",
    ".htm": "html",
    ".jsonl": "jsonl",
    ".pdf": "pdf",
}


def chunk_file(
    path: Path,
    *,
    tier: str,
    source_id_hint: str = "",
) -> list[Chunk]:
    """Dispatch by extension. Unsupported extensions return an empty list."""
    ext = path.suffix.lower()
    source_type = _EXTENSION_DISPATCH.get(ext)
    if source_type is None:
        return []
    # Source-id naming convention: `<SOURCE_ID>__<slug>.<ext>` (see
    # `knowledge/raw_sources/README.md`).
    if not source_id_hint:
        stem = path.stem
        if "__" in stem:
            source_id_hint = stem.split("__", 1)[0]
        else:
            source_id_hint = stem
    if source_type == "jsonl":
        return chunk_jsonl_rules(path, tier=tier, source_id_default=source_id_hint)
    if source_type == "md":
        return chunk_markdown(path, tier=tier, source_id=source_id_hint)
    if source_type == "html":
        return chunk_text(path, tier=tier, source_id=source_id_hint, source_type="html")
    if source_type == "txt":
        return chunk_text(path, tier=tier, source_id=source_id_hint, source_type="txt")
    if source_type == "pdf":
        return chunk_pdf(path, tier=tier, source_id=source_id_hint)
    return []


def walk_knowledge_dir(root: Path, *, tier: str) -> Iterable[Path]:
    """Yield indexable files in a tier directory.

    Skips READMEs (we don't want to index docs about the index itself),
    `.gitkeep`, `.gitignore`, obvious non-source files (`.xlsx`), and any
    `staging_*` file. A `staging_` prefix marks proposed-but-not-merged
    knowledge (e.g. `staging_pcb_parasitic_trace_rules.jsonl`): it is a
    review artifact and must not enter the retrieval index until it is
    promoted into a canonical `baza_*` file.
    """
    if not root.is_dir():
        return
    skip = {"README.md", ".gitkeep", ".gitignore"}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.name in skip:
            continue
        if path.name.startswith("staging_"):
            continue
        if path.suffix.lower() in {".xlsx", ".zip"}:
            continue
        yield path
