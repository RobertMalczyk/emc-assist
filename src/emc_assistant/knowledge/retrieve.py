"""Keyword + tag retrieval over seed `.jsonl` rules, with redaction for LLM exposure.

M2.7 keeps retrieval intentionally simple (substring + tag scoring). M2.8
replaces the scoring with embeddings + a vector index, but the
``RedactedSnippet`` contract returned by ``redact_for_llm`` stays the
same — every downstream LLM caller can rely on it.

Copyright contract (see [[feedback_copyright_redaction_for_llm]]):
- always safe: ``rule_id``, ``source_id``, ``summary`` (our own words);
- ``excerpt`` (≤ 200 chars verbatim): included only when the source's
  ``allowed_use`` is permissive (``internal_reference``);
- restrictive sources (``link_and_summary`` / ``check_license`` /
  ``user_provided_only`` / ``do_not_ingest``) contribute no body excerpt.
- Free-form ``Use_caution`` text on a source is treated as
  ``link_and_summary`` (most restrictive) by default.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from emc_assistant.knowledge.embedder import Embedder, EmbedderStub
from emc_assistant.knowledge.loader import (
    DEFAULT_SEED_DIR,
    EmcRule,
    KnowledgeBase,
    ParasiticRule,
)
from emc_assistant.knowledge.vector_index import (
    NumpyVectorIndex,
    VectorIndexMissingError,
)
from emc_assistant.llm.assistant import ProblemContext, RedactedSnippet


MAX_EXCERPT_CHARS = 200
"""Hard cap on verbatim excerpts. The M2.7 retrieval keeps this small;
M2.8's vector layer may surface longer matches but the redaction cap
still applies."""


PERMISSIVE_ALLOWED_USE = {"internal_reference"}
"""Source `allowed_use` values that allow a ≤200-char verbatim excerpt.
Everything else (`link_and_summary`, `check_license`,
`user_provided_only`, `do_not_ingest`, missing, or free-form
`Use_caution`) is treated as restrictive."""


@dataclass
class Snippet:
    """Pre-redaction representation of a retrieved item.

    Carries the full rule and source metadata so the redactor can decide
    what to expose. Never pass a ``Snippet`` directly to an LLM — always
    pass ``redact_for_llm(snippet)``.
    """

    rule_id: str
    source_id: str
    score: float
    summary: str
    """Our own summary, built from curated rule fields. Always safe."""
    raw_body: str = ""
    """Vendor-document body text if available. May be redacted out."""
    allowed_use: str = ""
    """Either an enum value from `source_manifest.schema.json` or empty."""


def _load_sources(seed_dir: Path | None = None) -> dict[str, dict]:
    """Load both source jsonl files into a {Source_ID: raw_dict} map."""
    seed_dir = Path(seed_dir) if seed_dir else DEFAULT_SEED_DIR
    out: dict[str, dict] = {}
    for name in (
        "baza_pasozyty_pcb_sources.jsonl",
        "baza_wiedzy_emc_ltspice_sources.jsonl",
    ):
        path = seed_dir / name
        if not path.is_file():
            continue
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                sid = str(row.get("Source_ID") or row.get("source_id") or "").strip()
                if sid:
                    out[sid] = row
    return out


_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")


def _tokens(text: str) -> set[str]:
    return {t.lower() for t in _TOKEN_RE.findall(text or "")}


def _context_tokens(ctx: ProblemContext) -> set[str]:
    parts = [
        ctx.analysis_scope or "",
        ctx.topology or "",
        ctx.problem_hypothesis or "",
        " ".join(ctx.missing_data),
    ]
    return _tokens(" ".join(parts))


def _score_parasitic(rule: ParasiticRule, ctx_tokens: set[str]) -> float:
    rule_text = " ".join(
        [
            rule.domain,
            rule.structure,
            rule.parasitic,
            rule.use_when,
            rule.range_or_sensitivity,
        ]
    )
    overlap = ctx_tokens & _tokens(rule_text)
    base = float(len(overlap))
    if rule.confidence.lower() == "high":
        base += 0.5
    elif rule.confidence.lower() == "medium":
        base += 0.25
    return base


def _score_emc(rule: EmcRule, ctx_tokens: set[str]) -> float:
    rule_text = " ".join([rule.area, rule.rule, rule.rationale, rule.agent_action])
    overlap = ctx_tokens & _tokens(rule_text)
    return float(len(overlap))


def _parasitic_summary(rule: ParasiticRule) -> str:
    parts = [
        f"{rule.structure} / {rule.parasitic}",
        rule.default_value,
        f"range: {rule.range_or_sensitivity}" if rule.range_or_sensitivity else "",
        f"use when: {rule.use_when}" if rule.use_when else "",
    ]
    return " — ".join(p for p in parts if p)


def _emc_summary(rule: EmcRule) -> str:
    parts = [f"area: {rule.area}", rule.rule]
    if rule.rationale:
        parts.append(f"rationale: {rule.rationale}")
    return " — ".join(parts)


def _retrieve_by_tokens(
    query_tokens: set[str],
    *,
    kb: KnowledgeBase,
    sources: dict[str, dict],
    k: int,
) -> list[Snippet]:
    """Score every parasitic + EMC rule by token overlap with ``query_tokens``.

    Shared core for ``retrieve_top_k`` (problem-context tokens) and
    ``retrieve_for_keywords`` (per-agent keyword tokens).
    """
    scored: list[tuple[float, Snippet]] = []
    for rule in kb.parasitic_rules:
        score = _score_parasitic(rule, query_tokens)
        if score <= 0:
            continue
        primary_source = rule.source_ids[0] if rule.source_ids else ""
        src_meta = sources.get(primary_source, {})
        allowed = str(src_meta.get("allowed_use") or "").strip().lower()
        scored.append(
            (
                score,
                Snippet(
                    rule_id=rule.rule_id,
                    source_id=primary_source,
                    score=score,
                    summary=_parasitic_summary(rule),
                    raw_body=str(src_meta.get("body") or ""),
                    allowed_use=allowed,
                ),
            )
        )
    for rule in kb.emc_rules:
        score = _score_emc(rule, query_tokens)
        if score <= 0:
            continue
        primary_source = rule.source_ids[0] if rule.source_ids else ""
        src_meta = sources.get(primary_source, {})
        allowed = str(src_meta.get("allowed_use") or "").strip().lower()
        scored.append(
            (
                score,
                Snippet(
                    rule_id=rule.rule_id,
                    source_id=primary_source,
                    score=score,
                    summary=_emc_summary(rule),
                    raw_body=str(src_meta.get("body") or ""),
                    allowed_use=allowed,
                ),
            )
        )
    scored.sort(key=lambda s: s[0], reverse=True)
    return [s for _, s in scored[:k]]


def retrieve_top_k(
    problem_context: ProblemContext,
    *,
    kb: KnowledgeBase | None = None,
    k: int = 5,
    seed_dir: Path | None = None,
) -> list[Snippet]:
    """Return up to ``k`` highest-scoring snippets across both rule sets.

    Combines parasitic + EMC rules into a single ranked list. The result
    is suitable for passing through ``redact_for_llm`` before any LLM
    call.
    """
    from emc_assistant.knowledge import load_default_knowledge

    kb = kb or load_default_knowledge(seed_dir=seed_dir)
    sources = _load_sources(seed_dir=seed_dir)
    return _retrieve_by_tokens(
        _context_tokens(problem_context), kb=kb, sources=sources, k=k
    )


def redact_for_llm(snippet: Snippet) -> RedactedSnippet:
    """Convert an internal ``Snippet`` into a payload safe to send to an LLM.

    Always emits ``rule_id`` + ``source_id`` + our own ``summary``. Adds a
    ≤ 200-character verbatim excerpt **only** if the source's
    ``allowed_use`` is in ``PERMISSIVE_ALLOWED_USE``.

    The function is the only sanctioned bridge between the local
    knowledge index and any outbound LLM payload. Callers MUST route
    every snippet through it; bypassing this helper is a copyright
    contract violation (see [[feedback_copyright_redaction_for_llm]]).
    """
    excerpt: str | None = None
    if snippet.allowed_use in PERMISSIVE_ALLOWED_USE and snippet.raw_body:
        excerpt = snippet.raw_body[:MAX_EXCERPT_CHARS]
    return RedactedSnippet(
        rule_id=snippet.rule_id,
        source_id=snippet.source_id,
        summary=snippet.summary,
        excerpt=excerpt,
    )


def retrieve_redacted(
    problem_context: ProblemContext,
    *,
    kb: KnowledgeBase | None = None,
    k: int = 5,
    seed_dir: Path | None = None,
    index_root: Path | None = None,
    embedder: Embedder | None = None,
) -> list[RedactedSnippet]:
    """Convenience: best-effort retrieval + ``redact_for_llm`` in one call.

    Behaviour:
    - If ``index_root`` points at an existing built index (M2.8), use the
      vector index with the supplied (or stub) embedder.
    - Otherwise fall back to M2.7 keyword scoring over the seed `.jsonl`.

    Either path produces redacted snippets honouring the copyright
    contract.
    """
    repo_root = Path(__file__).resolve().parents[3]
    candidate_root = Path(index_root) if index_root else repo_root / "knowledge" / "processed"
    if NumpyVectorIndex.exists(candidate_root):
        try:
            return _retrieve_via_vector_index(
                _build_index_query(problem_context),
                index_root=candidate_root,
                embedder=embedder,
                k=k,
            )
        except (VectorIndexMissingError, ValueError):
            # Fall through to keyword on any structural problem.
            pass
    return [
        redact_for_llm(s) for s in retrieve_top_k(problem_context, kb=kb, k=k, seed_dir=seed_dir)
    ]


def retrieve_for_keywords(
    keywords: list[str],
    problem_context: ProblemContext,
    *,
    kb: KnowledgeBase | None = None,
    k: int = 5,
    seed_dir: Path | None = None,
    index_root: Path | None = None,
    embedder: Embedder | None = None,
) -> list[RedactedSnippet]:
    """M2.9.1 per-agent retrieval.

    Builds a query from a specialist agent's ``keywords`` list plus the
    project's topology, then runs the vector index (when one exists) or
    a keyword-token fallback over the seed rules. This is what gives the
    ``decoupling`` agent decoupling-specific chunks instead of all 11
    agents sharing one topology-level retrieval.

    The redaction contract is identical to :func:`retrieve_redacted`.
    """
    repo_root = Path(__file__).resolve().parents[3]
    candidate_root = Path(index_root) if index_root else repo_root / "knowledge" / "processed"
    if NumpyVectorIndex.exists(candidate_root):
        try:
            return _retrieve_via_vector_index(
                _build_keyword_query(keywords, problem_context),
                index_root=candidate_root,
                embedder=embedder,
                k=k,
            )
        except (VectorIndexMissingError, ValueError):
            pass
    # Keyword fallback: score seed rules against the agent keyword tokens.
    from emc_assistant.knowledge import load_default_knowledge

    kb = kb or load_default_knowledge(seed_dir=seed_dir)
    sources = _load_sources(seed_dir=seed_dir)
    query_tokens = _tokens(" ".join(keywords))
    return [
        redact_for_llm(s)
        for s in _retrieve_by_tokens(query_tokens, kb=kb, sources=sources, k=k)
    ]


def _retrieve_via_vector_index(
    query: str,
    *,
    index_root: Path,
    embedder: Embedder | None,
    k: int,
) -> list[RedactedSnippet]:
    """Vector-path retrieval for an arbitrary query string.

    Caller is responsible for falling back on errors. ``query`` is built
    by :func:`_build_index_query` (problem-context retrieval) or
    :func:`_build_keyword_query` (per-agent retrieval).
    """
    index = NumpyVectorIndex(root=index_root)
    index.load()
    if embedder is None:
        # Use a stub when no real embedder was passed — works only if the
        # index was built with the stub too (dims must match). The CLI
        # always passes a real embedder; this branch is mostly for tests.
        embedder = EmbedderStub(dim=index.meta.embedding_dim if index.meta else 64)
    hits = index.search(query, embedder, k=k)
    out: list[RedactedSnippet] = []
    for hit in hits:
        chunk = hit.chunk
        allowed = str(chunk.get("allowed_use", "")).strip().lower()
        excerpt: str | None = None
        if allowed in PERMISSIVE_ALLOWED_USE:
            raw = chunk.get("text") or ""
            excerpt = raw[:MAX_EXCERPT_CHARS] if raw else None
        out.append(
            RedactedSnippet(
                rule_id=str(chunk.get("rule_id") or ""),
                source_id=str(chunk.get("source_id") or ""),
                summary=str(chunk.get("summary") or chunk.get("title") or chunk.get("text", "")[:200]),
                excerpt=excerpt,
            )
        )
    return out


def _build_index_query(problem_context: ProblemContext) -> str:
    parts: list[str] = []
    if problem_context.topology:
        parts.append(problem_context.topology)
    if problem_context.analysis_scope:
        parts.append(problem_context.analysis_scope.replace("_", " "))
    if problem_context.problem_hypothesis:
        parts.append(problem_context.problem_hypothesis)
    return ". ".join(parts) or "conducted EMI"


def _build_keyword_query(keywords: list[str], problem_context: ProblemContext) -> str:
    """Per-agent query: the agent's keyword list, grounded by topology + scope.

    Keeps the topology so a 'decoupling' query still resolves to DC/DC
    decoupling chunks rather than generic capacitor theory.
    """
    parts: list[str] = []
    if keywords:
        parts.append(" ".join(keywords))
    if problem_context.topology:
        parts.append(problem_context.topology)
    if problem_context.analysis_scope:
        parts.append(problem_context.analysis_scope.replace("_", " "))
    return ". ".join(parts) or "conducted EMI"
