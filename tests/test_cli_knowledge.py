"""Tests for the new `knowledge index|search|build-pack` CLI subcommands."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emc_assistant.cli import main
from emc_assistant.knowledge.vector_index import NumpyVectorIndex


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _isolate_knowledge_root(tmp_path: Path, monkeypatch):
    """Redirect the CLI's `_resolve_knowledge_root` to a tmp dir with copied seed."""
    fake_root = tmp_path / "kroot"
    fake_root.mkdir()
    # Copy seed jsonl rules so retrieval finds something.
    seed_src = REPO_ROOT / "knowledge" / "seed"
    seed_dst = fake_root / "seed"
    shutil.copytree(seed_src, seed_dst)
    (fake_root / "raw_sources").mkdir()
    (fake_root / "processed").mkdir()

    from emc_assistant.service import knowledge as knowledge_service

    monkeypatch.setattr(knowledge_service, "resolve_knowledge_root", lambda: fake_root)
    return fake_root


def test_knowledge_index_with_stub_embedder(tmp_path: Path, monkeypatch, capsys):
    fake_root = _isolate_knowledge_root(tmp_path, monkeypatch)
    rc = main(["knowledge", "index", "--embedder-stub"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "[knowledge index]" in captured.out
    # Index files now exist.
    assert NumpyVectorIndex.exists(fake_root / "processed")
    idx = NumpyVectorIndex(root=fake_root / "processed")
    idx.load()
    assert idx.meta is not None
    assert idx.meta.chunk_count > 0


def test_knowledge_index_fails_when_no_files(tmp_path: Path, monkeypatch, capsys):
    # Empty knowledge root → nothing to index → rc=1
    fake_root = tmp_path / "kroot"
    fake_root.mkdir()
    (fake_root / "raw_sources").mkdir()
    (fake_root / "processed").mkdir()
    from emc_assistant.service import knowledge as knowledge_service

    monkeypatch.setattr(knowledge_service, "resolve_knowledge_root", lambda: fake_root)
    rc = main(["knowledge", "index", "--embedder-stub"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "No chunks to index" in out


def test_knowledge_search_round_trip(tmp_path: Path, monkeypatch, capsys):
    _isolate_knowledge_root(tmp_path, monkeypatch)
    main(["knowledge", "index", "--embedder-stub"])
    capsys.readouterr()  # drain
    rc = main(["knowledge", "search", "conducted EMI buck", "--k", "3", "--embedder-stub"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "[knowledge search]" in out
    # Format: " [1] score=… | [tier / source / rule] title"
    assert "score=" in out


def test_knowledge_search_fails_without_index(tmp_path: Path, monkeypatch, capsys):
    fake_root = tmp_path / "kroot"
    fake_root.mkdir()
    (fake_root / "processed").mkdir()
    from emc_assistant.service import knowledge as knowledge_service

    monkeypatch.setattr(knowledge_service, "resolve_knowledge_root", lambda: fake_root)
    rc = main(["knowledge", "search", "x", "--embedder-stub"])
    assert rc == 1
    out = capsys.readouterr().out
    assert "No index" in out


def test_knowledge_search_rejects_dim_mismatch(tmp_path: Path, monkeypatch, capsys):
    """When the index was built with one embedder dim and search uses another, rc=2."""
    fake_root = _isolate_knowledge_root(tmp_path, monkeypatch)
    # Build with stub dim=64 (default)
    main(["knowledge", "index", "--embedder-stub"])
    capsys.readouterr()
    # Manually corrupt the meta to claim a different embedding_dim
    meta_path = fake_root / "processed" / "index_meta.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    meta["embedding_dim"] = 1024  # lie
    meta_path.write_text(json.dumps(meta), encoding="utf-8")
    rc = main(["knowledge", "search", "x", "--embedder-stub"])
    assert rc == 2
    out = capsys.readouterr().out
    assert "dim" in out.lower()


def test_knowledge_build_pack_end_to_end(tmp_path: Path, monkeypatch, capsys):
    _isolate_knowledge_root(tmp_path, monkeypatch)
    # Index first
    main(["knowledge", "index", "--embedder-stub"])
    capsys.readouterr()
    # Copy example project so the build-pack call has something to read.
    project = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, project)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(project / sub, ignore_errors=True)

    rc = main([
        "knowledge", "build-pack", str(project),
        "--k", "5",
        "--embedder-stub",
    ])
    assert rc == 0
    pack_path = project / "generated" / "knowledge_pack.json"
    assert pack_path.is_file()
    pack = json.loads(pack_path.read_text(encoding="utf-8"))
    assert "snippets" in pack
    assert len(pack["snippets"]) <= 5
    assert pack["problem_context_ref"]["project_id"] == "case_001_buck_conducted_emi"
