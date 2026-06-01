"""Tests for the M2.8 chunker / embedder / numpy vector index trio."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from emc_assistant.knowledge.chunker import (
    Chunk,
    chunk_file,
    chunk_jsonl_rules,
    chunk_markdown,
    chunk_text,
    file_checksum,
    walk_knowledge_dir,
)
from emc_assistant.knowledge.embedder import EmbedderStub, _normalise
from emc_assistant.knowledge.vector_index import (
    NumpyVectorIndex,
    VectorIndexMissingError,
)
from emc_assistant.knowledge.retrieve import retrieve_redacted
from emc_assistant.llm.assistant import ProblemContext


# ---------- Chunker tests ----------


def test_chunk_jsonl_rules_seed(tmp_path: Path):
    src = tmp_path / "rules.jsonl"
    src.write_text(
        '\n'.join([
            json.dumps({
                "Rule_ID": "R001",
                "Domain": "Trace / interconnect",
                "Structure": "1 oz Cu trace",
                "Parasitic": "DC resistance",
                "Default_value_for_agent": "0.49 mOhm/sq",
                "Range_or_sensitivity": "0.25-0.98 mOhm/sq",
                "Source_IDs": "S004, S022",
            }),
            json.dumps({
                "Rule_ID": "R002",
                "Domain": "Buck input loop",
                "Structure": "Hot loop",
                "Parasitic": "Loop inductance",
                "Default_value_for_agent": "1-3 nH target",
                "Source_IDs": "S009",
            }),
        ]),
        encoding="utf-8",
    )
    chunks = chunk_jsonl_rules(src, tier="seed")
    assert len(chunks) == 2
    assert chunks[0].rule_id == "R001"
    assert chunks[0].source_id == "S004"
    assert chunks[0].tier == "seed"
    assert chunks[0].source_type == "jsonl"
    assert "Default value:" in chunks[0].text
    assert chunks[1].source_id == "S009"


def test_chunk_jsonl_rules_emc_shape(tmp_path: Path):
    src = tmp_path / "emc.jsonl"
    src.write_text(
        json.dumps({
            "rule_id": "R-003",
            "area": "conducted_emi_testbench",
            "rule": "Use LISN model for conducted EMI",
            "source_ids": ["SRC-001"],
        }),
        encoding="utf-8",
    )
    chunks = chunk_jsonl_rules(src, tier="seed")
    assert len(chunks) == 1
    assert chunks[0].rule_id == "R-003"
    assert chunks[0].source_id == "SRC-001"
    assert "Rule:" in chunks[0].text


def test_chunk_markdown_heading_aware(tmp_path: Path):
    src = tmp_path / "doc.md"
    src.write_text(
        "# Top\n\nIntro paragraph.\n\n"
        "## Section A\n\nA body line.\n\n"
        "## Section B\n\nB body line.\n",
        encoding="utf-8",
    )
    chunks = chunk_markdown(src, tier="raw_sources", source_id="S001")
    titles = [c.title for c in chunks]
    assert "Section A" in titles
    assert "Section B" in titles
    assert all(c.source_type == "md" for c in chunks)
    assert all(c.source_id == "S001" for c in chunks)


def test_chunk_text_html_strips_tags(tmp_path: Path):
    src = tmp_path / "page.html"
    src.write_text(
        "<html><body><script>alert(1)</script>"
        "<p>This is content about <b>conducted EMI</b> in buck converters.</p>"
        "</body></html>",
        encoding="utf-8",
    )
    chunks = chunk_text(src, tier="raw_sources", source_type="html")
    assert len(chunks) == 1
    assert "conducted EMI" in chunks[0].text
    assert "<script>" not in chunks[0].text
    assert "alert(1)" not in chunks[0].text


def test_chunk_file_dispatches_by_extension(tmp_path: Path):
    md = tmp_path / "S001__doc.md"
    md.write_text("# Heading\n\n## Section\n\nbody.\n", encoding="utf-8")
    txt = tmp_path / "S002__notes.txt"
    txt.write_text("Plain note paragraph.\n", encoding="utf-8")
    unsupported = tmp_path / "data.xlsx"
    unsupported.write_text("not really xlsx, but the dispatcher should skip", encoding="utf-8")

    md_chunks = chunk_file(md, tier="raw_sources")
    txt_chunks = chunk_file(txt, tier="raw_sources")
    skip = chunk_file(unsupported, tier="raw_sources")

    assert md_chunks and md_chunks[0].source_id == "S001"
    assert txt_chunks and txt_chunks[0].source_id == "S002"
    assert skip == []


def test_walk_knowledge_dir_skips_readme_and_xlsx(tmp_path: Path):
    (tmp_path / "README.md").write_text("not indexed", encoding="utf-8")
    (tmp_path / "a.md").write_text("# Indexed\n", encoding="utf-8")
    (tmp_path / "b.xlsx").write_text("skip", encoding="utf-8")
    files = list(walk_knowledge_dir(tmp_path, tier="raw_sources"))
    names = {p.name for p in files}
    assert "a.md" in names
    assert "README.md" not in names
    assert "b.xlsx" not in names


def test_file_checksum_stable(tmp_path: Path):
    src = tmp_path / "x.txt"
    src.write_text("hello", encoding="utf-8")
    h1 = file_checksum(src)
    h2 = file_checksum(src)
    assert h1 == h2
    src.write_text("hello!", encoding="utf-8")
    assert file_checksum(src) != h1


# ---------- Embedder tests ----------


def test_embedder_stub_deterministic_and_normalised():
    e = EmbedderStub(dim=16)
    a = e.embed(["foo"])
    b = e.embed(["foo"])
    assert np.allclose(a, b)
    norms = np.linalg.norm(a, axis=1)
    assert np.allclose(norms, [1.0])
    # Different inputs differ
    c = e.embed(["foo", "bar"])
    assert c.shape == (2, 16)
    assert not np.allclose(c[0], c[1])


def test_embedder_stub_empty_input():
    e = EmbedderStub(dim=16)
    out = e.embed([])
    assert out.shape == (0, 16)


def test_normalise_handles_zero_rows():
    arr = np.array([[0.0, 0.0], [3.0, 4.0]], dtype=np.float32)
    norm = _normalise(arr)
    assert np.allclose(norm[0], [0.0, 0.0])
    assert np.allclose(np.linalg.norm(norm[1]), 1.0)


# ---------- Vector index tests ----------


def test_vector_index_build_round_trip(tmp_path: Path):
    chunks = [
        Chunk(chunk_id="seed:S001:R001:1", tier="seed", source_id="S001",
              source_path="x.jsonl", source_type="jsonl", text="foo bar", rule_id="R001"),
        Chunk(chunk_id="seed:S001:R002:1", tier="seed", source_id="S001",
              source_path="x.jsonl", source_type="jsonl", text="baz qux", rule_id="R002"),
    ]
    idx = NumpyVectorIndex(root=tmp_path / "processed")
    embedder = EmbedderStub(dim=32)
    meta = idx.build(chunks, embedder)
    assert meta.chunk_count == 2
    assert meta.embedding_dim == 32
    # Files on disk
    assert (tmp_path / "processed" / "chunks.jsonl").is_file()
    assert (tmp_path / "processed" / "embeddings.npy").is_file()
    assert (tmp_path / "processed" / "index_meta.json").is_file()
    # Re-load
    idx2 = NumpyVectorIndex(root=tmp_path / "processed")
    meta2 = idx2.load()
    assert meta2.chunk_count == 2
    assert idx2._embeddings.shape == (2, 32)
    assert idx2._chunks[0]["rule_id"] == "R001"


def test_vector_index_search_returns_topk(tmp_path: Path):
    chunks = [
        Chunk(chunk_id="seed:S:R1:1", tier="seed", source_id="S",
              source_path="x", source_type="jsonl", text="alpha bravo charlie", rule_id="R1"),
        Chunk(chunk_id="seed:S:R2:1", tier="seed", source_id="S",
              source_path="x", source_type="jsonl", text="delta echo foxtrot", rule_id="R2"),
        Chunk(chunk_id="seed:S:R3:1", tier="seed", source_id="S",
              source_path="x", source_type="jsonl", text="golf hotel india", rule_id="R3"),
    ]
    embedder = EmbedderStub(dim=16)
    idx = NumpyVectorIndex(root=tmp_path / "p")
    idx.build(chunks, embedder)
    # Querying with the same text as a chunk should rank it first.
    hits = idx.search("alpha bravo charlie", embedder, k=3)
    assert len(hits) == 3
    assert hits[0].chunk["rule_id"] == "R1"
    # Scores monotonically non-increasing
    scores = [h.score for h in hits]
    assert scores == sorted(scores, reverse=True)


def test_vector_index_missing_raises(tmp_path: Path):
    idx = NumpyVectorIndex(root=tmp_path / "missing")
    with pytest.raises(VectorIndexMissingError):
        idx.load()


def test_vector_index_exists(tmp_path: Path):
    root = tmp_path / "p"
    assert NumpyVectorIndex.exists(root) is False
    NumpyVectorIndex(root=root).build([], EmbedderStub(dim=8))
    assert NumpyVectorIndex.exists(root) is True


def test_vector_index_dim_mismatch_raises(tmp_path: Path):
    chunks = [
        Chunk(chunk_id="seed:S:R1:1", tier="seed", source_id="S",
              source_path="x", source_type="jsonl", text="hello world", rule_id="R1"),
    ]
    idx = NumpyVectorIndex(root=tmp_path / "p")
    idx.build(chunks, EmbedderStub(dim=16))
    # Re-load with the same root but search with a different-dim embedder
    idx2 = NumpyVectorIndex(root=tmp_path / "p")
    idx2.load()
    with pytest.raises(ValueError):
        idx2.search("query", EmbedderStub(dim=32), k=1)


# ---------- retrieve_redacted falls back when no index ----------


def _ctx() -> ProblemContext:
    return ProblemContext(
        project_id="case_001",
        analysis_scope="conducted_emi_dc_dc",
        topology="buck_converter",
        problem_hypothesis="conducted EMI near switching harmonics",
        has_layout=False,
        has_stackup=True,
        missing_data=["layout"],
    )


def test_retrieve_redacted_falls_back_to_keyword_when_no_index(tmp_path: Path):
    """When the index root doesn't exist, retrieve still returns results via M2.7 path."""
    snippets = retrieve_redacted(
        _ctx(),
        k=3,
        index_root=tmp_path / "absent",
    )
    # Should use keyword fallback against bundled seed and produce something.
    assert len(snippets) >= 1
    assert all(s.rule_id for s in snippets)


def test_retrieve_redacted_uses_vector_index_when_present(tmp_path: Path):
    chunks = [
        Chunk(
            chunk_id="seed:S009:R026:1", tier="seed", source_id="S009",
            source_path="x.jsonl", source_type="jsonl", rule_id="R026",
            text="buck converter hot input loop loop inductance VIN ringing conducted EMI",
            summary="Buck converter hot input loop / Loop inductance",
            allowed_use="link_and_summary",
        ),
        Chunk(
            chunk_id="seed:S003:R027:1", tier="seed", source_id="S003",
            source_path="x.jsonl", source_type="jsonl", rule_id="R027",
            text="switch node polygon parasitic capacitance to GND chassis displacement current",
            summary="Buck switch node polygon / Parasitic capacitance",
            allowed_use="",
        ),
        Chunk(
            chunk_id="seed:SNX:RXX:1", tier="seed", source_id="SNX",
            source_path="x.jsonl", source_type="jsonl", rule_id="RXX",
            text="completely unrelated mixed signal ADC reference grounding",
            summary="Mixed-signal ADC",
            allowed_use="",
        ),
    ]
    NumpyVectorIndex(root=tmp_path / "processed").build(chunks, EmbedderStub(dim=32))
    snippets = retrieve_redacted(
        _ctx(),
        k=2,
        index_root=tmp_path / "processed",
    )
    assert len(snippets) == 2
    # All snippets are restrictive sources → no excerpt should be present.
    assert all(s.excerpt is None for s in snippets)
    # Every snippet carries a rule_id + source_id (the redaction contract).
    assert all(s.rule_id for s in snippets)
    assert all(s.source_id for s in snippets)
    # The stub embedder is semantically meaningless, so we only assert
    # structural properties — ranking quality is verified by the real
    # SentenceTransformersEmbedder in the live demo, not in CI.