"""Knowledge pack builder — consumes a `ProblemContext` + vector index → `knowledge_pack.json`.

The pack is the bounded payload that M2.9 specialist agents and M2.11
orchestrator consume. It carries:

- top-K redacted snippets (per the copyright contract),
- recommended sweeps inferred from the snippets' fields,
- typical values extracted from curated rule defaults,
- limitations carried forward from missing context.

The pack is schema-valid (`schemas/knowledge_pack.schema.json`) and
stable to ingest from downstream code.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path

from emc_assistant.knowledge.embedder import Embedder
from emc_assistant.knowledge.vector_index import (
    NumpyVectorIndex,
    SearchHit,
)
from emc_assistant.llm.assistant import ProblemContext, RedactedSnippet


PERMISSIVE_ALLOWED_USE = {"internal_reference"}
"""Mirror of `knowledge.retrieve.PERMISSIVE_ALLOWED_USE` — kept in sync."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _problem_context_hash(ctx: ProblemContext) -> str:
    payload = json.dumps(
        {
            "project_id": ctx.project_id,
            "analysis_scope": ctx.analysis_scope,
            "topology": ctx.topology,
            "problem_hypothesis": ctx.problem_hypothesis,
            "freq_range": [ctx.frequency_range_min_hz, ctx.frequency_range_max_hz],
            "missing_data": sorted(ctx.missing_data),
        },
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def _build_topics(ctx: ProblemContext) -> list[str]:
    parts: list[str] = []
    if ctx.analysis_scope:
        parts.append(ctx.analysis_scope)
    if ctx.topology:
        parts.append(re.sub(r"\W+", "_", ctx.topology.lower()).strip("_"))
    if ctx.problem_hypothesis:
        # Pick short noun-ish tokens
        for tok in re.findall(r"[A-Za-z][A-Za-z\-]{3,}", ctx.problem_hypothesis):
            if tok.lower() not in {"near", "from", "with", "and", "the"}:
                parts.append(tok.lower())
    seen: set[str] = set()
    out: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out[:10]


def _hit_to_redacted_snippet(hit: SearchHit) -> RedactedSnippet:
    """Apply the copyright contract to a search hit."""
    chunk = hit.chunk
    allowed = str(chunk.get("allowed_use", "")).strip().lower()
    excerpt: str | None = None
    if allowed in PERMISSIVE_ALLOWED_USE:
        raw = chunk.get("text") or ""
        excerpt = raw[:200] if raw else None
    return RedactedSnippet(
        rule_id=str(chunk.get("rule_id") or ""),
        source_id=str(chunk.get("source_id") or ""),
        summary=str(chunk.get("summary") or chunk.get("title") or chunk.get("text", "")[:200]),
        excerpt=excerpt,
    )


def _build_query_from_context(ctx: ProblemContext) -> str:
    """Render a single query string the embedder can score against the index."""
    parts: list[str] = []
    if ctx.topology:
        parts.append(ctx.topology)
    if ctx.analysis_scope:
        parts.append(ctx.analysis_scope.replace("_", " "))
    if ctx.problem_hypothesis:
        parts.append(ctx.problem_hypothesis)
    if ctx.missing_data:
        parts.append("missing: " + ", ".join(ctx.missing_data))
    return ". ".join(parts) or "conducted EMI"


def build_knowledge_pack(
    problem_context: ProblemContext,
    *,
    index: NumpyVectorIndex,
    embedder: Embedder,
    k: int = 8,
) -> dict:
    """Build a schema-valid knowledge pack from a loaded vector index.

    The caller must `index.load()` first; this function does not load
    or rebuild the index by itself (keeps responsibilities clean).
    """
    query = _build_query_from_context(problem_context)
    hits = index.search(query, embedder, k=k)
    snippets: list[dict] = []
    for hit in hits:
        red = _hit_to_redacted_snippet(hit)
        snippet_record = {
            "rule_id": red.rule_id,
            "source_id": red.source_id,
            "score": float(hit.score),
            "summary": red.summary,
            "tier": str(hit.chunk.get("tier", "")),
        }
        if red.excerpt:
            snippet_record["excerpt"] = red.excerpt
        snippets.append(snippet_record)

    recommended_sweeps: list[dict] = []
    typical_values: list[dict] = []
    for hit in hits:
        chunk = hit.chunk
        rid = chunk.get("rule_id") or ""
        text = chunk.get("text") or ""
        range_match = re.search(r"Range:\s*([^—]+?)(?:\s+—|$)", text)
        default_match = re.search(r"Default value:\s*([^—]+?)(?:\s+—|$)", text)
        if range_match and rid:
            recommended_sweeps.append(
                {
                    "parameter": chunk.get("summary") or rid,
                    "range": range_match.group(1).strip(),
                    "rationale": chunk.get("summary") or "",
                    "source_rule_ids": [rid],
                }
            )
        if default_match and rid:
            typical_values.append(
                {
                    "parameter": chunk.get("summary") or rid,
                    "value": default_match.group(1).strip(),
                    "confidence": "",
                    "source_rule_ids": [rid],
                }
            )

    limitations: list[str] = ["Results are pre-compliance only — verify with measurements."]
    if not problem_context.has_layout:
        limitations.append("No PCB layout available — parasitic estimates are geometric guesses.")
    if not problem_context.has_stackup:
        limitations.append("No stack-up available — defaulted to FR-4 ε_r=4.3, plane spacing unknown.")
    if "known_issue" in problem_context.missing_data:
        limitations.append("No known-issue hypothesis supplied — recommendations are generic for the topology.")

    pack: dict = {
        "knowledge_pack_id": f"{problem_context.project_id}__{_problem_context_hash(problem_context)}",
        "created_at": _now_iso(),
        "retrieval_mode": "embeddings" if index.meta and index.meta.embedder_name != "stub" else "embeddings",
        "embedder_model": (index.meta.embedder_model if index.meta else embedder.name),
        "problem_context_ref": {
            "project_id": problem_context.project_id,
            "analysis_scope": problem_context.analysis_scope,
            "topology": problem_context.topology,
            "context_hash": _problem_context_hash(problem_context),
        },
        "topics": _build_topics(problem_context),
        "snippets": snippets,
        "recommended_sweeps": recommended_sweeps,
        "typical_values": typical_values,
        "limitations": limitations,
    }
    return pack


def write_knowledge_pack(
    pack: dict,
    *,
    output_path: Path,
) -> Path:
    """Write the pack as pretty-printed JSON. Creates parent dirs."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(pack, indent=2, ensure_ascii=False), encoding="utf-8")
    return output_path
