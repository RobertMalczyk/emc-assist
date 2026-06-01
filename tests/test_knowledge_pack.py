"""Tests for the knowledge pack builder + schema validation."""

from __future__ import annotations

import json
from pathlib import Path

from emc_assistant.knowledge.chunker import Chunk
from emc_assistant.knowledge.embedder import EmbedderStub
from emc_assistant.knowledge.pack import (
    build_knowledge_pack,
    write_knowledge_pack,
)
from emc_assistant.knowledge.vector_index import NumpyVectorIndex
from emc_assistant.llm.assistant import ProblemContext
from emc_assistant.schemas import require_all_valid


def _ctx() -> ProblemContext:
    return ProblemContext(
        project_id="case_001_buck_conducted_emi",
        analysis_scope="conducted_emi_dc_dc",
        topology="buck_converter",
        problem_hypothesis="conducted EMI near switching harmonics",
        has_layout=False,
        has_stackup=True,
        missing_data=["layout", "known_issue"],
    )


def _seed_index(root: Path) -> NumpyVectorIndex:
    chunks = [
        Chunk(
            chunk_id="seed:S009:R026:1", tier="seed", source_id="S009",
            source_path="x.jsonl", source_type="jsonl", rule_id="R026",
            text="Structure: Buck converter hot input loop — Default value: 1-3 nH target — Range: Higher L causes ringing — Use when: Conducted EMI",
            summary="Buck converter hot input loop / Loop inductance",
            allowed_use="link_and_summary",
        ),
        Chunk(
            chunk_id="seed:S022:R033:1", tier="seed", source_id="S022",
            source_path="x.jsonl", source_type="jsonl", rule_id="R033",
            text="Structure: Mains input traces — Default value: wide/short — Range: Safety spacing forces loops — Use when: AC/DC EMI",
            summary="Mains input traces / Differential loop inductance",
            allowed_use="link_and_summary",
        ),
        Chunk(
            chunk_id="seed:SXX:RNX:1", tier="seed", source_id="SXX",
            source_path="x.jsonl", source_type="jsonl", rule_id="RNX",
            text="Unrelated chunk",
            summary="Unrelated",
            allowed_use="",
        ),
    ]
    idx = NumpyVectorIndex(root=root)
    idx.build(chunks, EmbedderStub(dim=32))
    return idx


def test_build_knowledge_pack_schema_valid(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    pack = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=3)
    # Schema validates.
    require_all_valid("knowledge_pack.schema.json", [pack])
    # Required fields present.
    assert pack["knowledge_pack_id"].startswith("case_001_buck_conducted_emi__")
    assert pack["problem_context_ref"]["project_id"] == "case_001_buck_conducted_emi"
    assert pack["retrieval_mode"] in ("keyword", "embeddings", "hybrid")
    assert "limitations" in pack and len(pack["limitations"]) >= 1


def test_pack_carries_only_redacted_fields(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    pack = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=3)
    for snippet in pack["snippets"]:
        assert "rule_id" in snippet
        assert "source_id" in snippet
        assert "summary" in snippet
        # Restrictive `allowed_use` → no excerpt should appear.
        assert "excerpt" not in snippet


def test_pack_extracts_typical_values_and_sweeps(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    pack = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=3)
    # Our seed-style chunks have `Default value:` and `Range:` → builder picks them up.
    rule_ids_in_typical = {entry["source_rule_ids"][0] for entry in pack["typical_values"]}
    rule_ids_in_sweeps = {entry["source_rule_ids"][0] for entry in pack["recommended_sweeps"]}
    assert rule_ids_in_typical or rule_ids_in_sweeps  # at least one path produced output


def test_pack_includes_layout_limitation_when_missing(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    pack = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=3)
    joined = " | ".join(pack["limitations"])
    assert "layout" in joined.lower()


def test_write_knowledge_pack_creates_parent_and_pretty_prints(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    pack = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=2)
    out = tmp_path / "out" / "knowledge_pack.json"
    written = write_knowledge_pack(pack, output_path=out)
    assert written == out
    assert out.is_file()
    text = out.read_text(encoding="utf-8")
    # Pretty-printed (multi-line).
    assert text.count("\n") > 5
    # Round-trip equal.
    assert json.loads(text) == pack


def test_pack_context_hash_stable_for_same_context(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    pack_a = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=2)
    pack_b = build_knowledge_pack(_ctx(), index=idx, embedder=EmbedderStub(dim=32), k=2)
    assert pack_a["problem_context_ref"]["context_hash"] == pack_b["problem_context_ref"]["context_hash"]
    assert pack_a["knowledge_pack_id"] == pack_b["knowledge_pack_id"]


def test_pack_context_hash_differs_for_different_topology(tmp_path: Path):
    idx = _seed_index(tmp_path / "processed")
    ctx_a = _ctx()
    ctx_b = ProblemContext(
        project_id=ctx_a.project_id,
        analysis_scope=ctx_a.analysis_scope,
        topology="flyback_converter",
    )
    pack_a = build_knowledge_pack(ctx_a, index=idx, embedder=EmbedderStub(dim=32), k=2)
    pack_b = build_knowledge_pack(ctx_b, index=idx, embedder=EmbedderStub(dim=32), k=2)
    assert pack_a["problem_context_ref"]["context_hash"] != pack_b["problem_context_ref"]["context_hash"]
