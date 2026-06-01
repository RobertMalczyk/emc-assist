"""Knowledge-base operations — service layer.

Covers the four ``knowledge`` commands: list curated rules, build the
local vector index, search it, and build a project knowledge pack.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from emc_assistant.knowledge import load_default_knowledge
from emc_assistant.knowledge.chunker import Chunk, chunk_file, walk_knowledge_dir
from emc_assistant.knowledge.embedder import (
    DEFAULT_SENTENCE_TRANSFORMERS_MODEL,
    Embedder,
    EmbedderStub,
    make_embedder,
)
from emc_assistant.knowledge.pack import build_knowledge_pack, write_knowledge_pack
from emc_assistant.knowledge.vector_index import NumpyVectorIndex
from emc_assistant.logging_setup import get_logger
from emc_assistant.schemas import SchemaValidationError, require_all_valid
from emc_assistant.service.context import (
    build_default_parasitics,
    build_problem_context,
    load_user_context,
)
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError

_log = get_logger("knowledge")

_KNOWLEDGE_TIERS: tuple[tuple[str, str], ...] = (
    ("seed", "knowledge/seed"),
    ("raw_sources", "knowledge/raw_sources"),
    ("user_private_sources", "knowledge/user_private_sources"),
    ("licensed_sources", "knowledge/licensed_sources"),
)


def resolve_knowledge_root() -> Path:
    """Top-level ``knowledge/`` directory inside the repo.

    ``__file__`` here is ``src/emc_assistant/service/knowledge.py``, so
    the repo root is ``parents[3]``.
    """
    return Path(__file__).resolve().parents[3] / "knowledge"


def _collect_chunks(knowledge_root: Path) -> list[Chunk]:
    """Walk every tier directory and return concatenated chunks."""
    chunks: list[Chunk] = []
    for tier, rel in _KNOWLEDGE_TIERS:
        tier_root = knowledge_root / Path(rel).name
        if not tier_root.is_dir():
            continue
        for src in walk_knowledge_dir(tier_root, tier=tier):
            try:
                produced = chunk_file(src, tier=tier)
            except RuntimeError as exc:
                # PDF without [pdf] extra, or other tooling gap.
                _log.warning(f"  [skip] {src.name}: {exc}")
                continue
            if not produced and src.suffix.lower() == ".pdf":
                # A scanned / image-only PDF extracts no text. Warn,
                # do not crash — the run continues.
                _log.warning(
                    f"  [warn] {src.name}: no extractable text "
                    "(scanned/image-only PDF?) — skipped"
                )
            chunks.extend(produced)
    return chunks


def _make_embedder(use_stub: bool, model_name: str | None) -> Embedder:
    if use_stub:
        return EmbedderStub()
    try:
        return make_embedder(
            model_name=model_name or DEFAULT_SENTENCE_TRANSFORMERS_MODEL,
            use_stub=False,
        )
    except RuntimeError as exc:
        raise ServiceError(f"Embedder unavailable: {exc}", exit_code=2) from exc


# ---- list ------------------------------------------------------------------


@dataclass
class KnowledgeListResult:
    parasitic_rule_count: int
    emc_rule_count: int
    domain: str | None
    area: str | None
    limit: int
    domain_matches: list
    area_matches: list


def list_rules(
    *, domain: str | None = None, area: str | None = None, limit: int = 10
) -> KnowledgeListResult:
    """Load the curated knowledge base and (optionally) filter rules."""
    kb = load_default_knowledge()
    return KnowledgeListResult(
        parasitic_rule_count=len(kb.parasitic_rules),
        emc_rule_count=len(kb.emc_rules),
        domain=domain,
        area=area,
        limit=limit,
        domain_matches=kb.find_parasitic(domain=domain) if domain else [],
        area_matches=kb.find_emc(area_contains=area) if area else [],
    )


# ---- index -----------------------------------------------------------------


def build_index(
    *,
    use_stub: bool = False,
    embedder_model: str | None = None,
    knowledge_root: str | Path | None = None,
):
    """Scan the knowledge tiers, embed every chunk, write the vector
    index. Returns the index meta."""
    root = Path(knowledge_root) if knowledge_root else resolve_knowledge_root()
    if not root.is_dir():
        raise ServiceError(f"Missing {root}; create the knowledge/ tree first.")
    processed_root = root / "processed"
    _log.info(f"[knowledge index] scanning {root}…")
    chunks = _collect_chunks(root)
    _log.info(
        f"[knowledge index] collected {len(chunks)} chunks across "
        f"{len(set(c.tier for c in chunks))} tier(s)"
    )
    if not chunks:
        raise ServiceError(
            "No chunks to index — drop files under knowledge/raw_sources/ first."
        )
    embedder = _make_embedder(use_stub, embedder_model)
    _log.info(f"[knowledge index] embedder: {embedder.name} (dim={embedder.dim})")
    index = NumpyVectorIndex(root=processed_root)
    meta = index.build(chunks, embedder)
    _log.info(
        f"[knowledge index] wrote {processed_root}/chunks.jsonl + "
        "embeddings.npy + index_meta.json"
    )
    _log.info(
        f"  chunks: {meta.chunk_count}, dim: {meta.embedding_dim}, "
        f"built_at: {meta.built_at}"
    )
    for tier, count in sorted(meta.source_counts.items()):
        _log.info(f"  tier '{tier}': {count} chunks")
    return meta


# ---- search ----------------------------------------------------------------


@dataclass
class KnowledgeHit:
    rank: int
    score: float
    tier: str
    source_id: str
    rule_id: str
    title: str


def _open_index(knowledge_root: str | Path | None) -> tuple[NumpyVectorIndex, Path]:
    root = Path(knowledge_root) if knowledge_root else resolve_knowledge_root()
    processed_root = root / "processed"
    if not NumpyVectorIndex.exists(processed_root):
        raise ServiceError(
            f"No index at {processed_root}. "
            "Run `emc-assistant knowledge index` first."
        )
    index = NumpyVectorIndex(root=processed_root)
    index.load()
    return index, processed_root


def search_index(
    query: str,
    *,
    k: int = 5,
    use_stub: bool = False,
    embedder_model: str | None = None,
    knowledge_root: str | Path | None = None,
) -> list[KnowledgeHit]:
    """Query the local vector index; returns ranked hits."""
    index, _ = _open_index(knowledge_root)
    embedder = _make_embedder(use_stub, embedder_model)
    index_dim = index.meta.embedding_dim if index.meta else 0
    if embedder.dim != index_dim:
        raise ServiceError(
            f"Embedder dim {embedder.dim} != index dim "
            f"{index.meta.embedding_dim if index.meta else '??'}. "
            f"Rebuild the index with the same model "
            f"(was: {index.meta.embedder_model if index.meta else 'unknown'}).",
            exit_code=2,
        )
    hits = index.search(query, embedder, k=int(k))
    out: list[KnowledgeHit] = []
    for i, hit in enumerate(hits, start=1):
        chunk = hit.chunk
        title = chunk.get("title") or chunk.get("summary") or "(untitled)"
        out.append(
            KnowledgeHit(
                rank=i,
                score=hit.score,
                tier=chunk.get("tier", "?"),
                source_id=chunk.get("source_id", "?"),
                rule_id=chunk.get("rule_id", "-"),
                title=title,
            )
        )
    return out


# ---- build-pack ------------------------------------------------------------


@dataclass
class BuildPackResult:
    pack_path: Path
    snippet_count: int
    sweep_count: int
    value_count: int


def build_pack(
    project_root,
    *,
    k: int = 8,
    use_stub: bool = False,
    embedder_model: str | None = None,
    knowledge_root: str | Path | None = None,
) -> BuildPackResult:
    """Build ``generated/knowledge_pack.json`` for a project."""
    index, _ = _open_index(knowledge_root)
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    parasitics = build_default_parasitics(user_context)
    problem_context = build_problem_context(config, user_context, parasitics)
    embedder = _make_embedder(use_stub, embedder_model)
    index_dim = index.meta.embedding_dim if index.meta else 0
    if embedder.dim != index_dim:
        raise ServiceError(
            "Embedder dim mismatch with index. "
            "Rebuild via `knowledge index` first.",
            exit_code=2,
        )
    pack = build_knowledge_pack(problem_context, index=index, embedder=embedder, k=int(k))
    try:
        require_all_valid("knowledge_pack.schema.json", [pack])
    except SchemaValidationError as exc:
        raise ServiceError(f"Knowledge pack violates the schema:\n{exc}") from exc
    out_path = layout.generated_dir / "knowledge_pack.json"
    write_knowledge_pack(pack, output_path=out_path)
    _log.info(f"Wrote knowledge pack: {out_path}")
    _log.info(
        f"  snippets: {len(pack['snippets'])}, "
        f"recommended_sweeps: {len(pack['recommended_sweeps'])}, "
        f"typical_values: {len(pack['typical_values'])}"
    )
    return BuildPackResult(
        pack_path=out_path,
        snippet_count=len(pack["snippets"]),
        sweep_count=len(pack["recommended_sweeps"]),
        value_count=len(pack["typical_values"]),
    )
