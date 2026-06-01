"""Numpy-backed vector index.

Persists three files under `knowledge/processed/`:

- ``chunks.jsonl`` — one chunk record per line (matches `schemas/chunk_index.schema.json`)
- ``embeddings.npy`` — float32 ``(n_chunks, dim)`` matrix in the same row order
- ``index_meta.json`` — embedder name + model, chunk count, build timestamp, source checksums

Search is cosine similarity over L2-normalised rows → a single
matrix-vector dot product. Sufficient up to ~tens of thousands of
chunks; for our seed (~110 rules + a few user docs) it is more than
fast enough.

Writes are atomic (tmpfile → ``os.replace``) so a crashed `knowledge
index` never corrupts the previous index.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from emc_assistant.knowledge.chunker import Chunk
from emc_assistant.knowledge.embedder import Embedder


CHUNKS_FILENAME = "chunks.jsonl"
EMBEDDINGS_FILENAME = "embeddings.npy"
META_FILENAME = "index_meta.json"


@dataclass
class IndexMeta:
    embedder_name: str
    embedder_model: str
    embedding_dim: int
    chunk_count: int
    built_at: str
    source_counts: dict[str, int]  # tier → count

    def to_dict(self) -> dict:
        return {
            "embedder_name": self.embedder_name,
            "embedder_model": self.embedder_model,
            "embedding_dim": self.embedding_dim,
            "chunk_count": self.chunk_count,
            "built_at": self.built_at,
            "source_counts": dict(self.source_counts),
        }


@dataclass
class SearchHit:
    chunk: dict
    score: float


class VectorIndexMissingError(FileNotFoundError):
    """Raised when callers request a non-existent index. Retrieval layer
    catches this to fall back to keyword scoring (M2.7 behaviour)."""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, path)
    except Exception:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise


def _atomic_write_text(path: Path, text: str) -> None:
    _atomic_write_bytes(path, text.encode("utf-8"))


class NumpyVectorIndex:
    """In-memory + on-disk index.

    Typical lifecycle:

    1. ``index = NumpyVectorIndex(root='knowledge/processed')``
    2. ``index.build(chunks, embedder)`` — embeds and writes the three files
    3. Later: ``index.load()`` — reads the three files back into memory
    4. ``hits = index.search(query, embedder, k=5)`` — cosine top-K
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self._chunks: list[dict] = []
        self._embeddings: np.ndarray = np.zeros((0, 0), dtype=np.float32)
        self._meta: IndexMeta | None = None

    # ---------- Build ----------

    def build(self, chunks: list[Chunk], embedder: Embedder) -> IndexMeta:
        """Embed `chunks` and persist the index atomically. Returns metadata."""
        chunk_records = [c.to_jsonl_dict() for c in chunks]
        texts = [c.text for c in chunks]
        embeddings = embedder.embed(texts) if texts else np.zeros((0, embedder.dim), dtype=np.float32)
        if embeddings.dtype != np.float32:
            embeddings = embeddings.astype(np.float32)

        source_counts: dict[str, int] = {}
        for c in chunks:
            source_counts[c.tier] = source_counts.get(c.tier, 0) + 1

        meta = IndexMeta(
            embedder_name=embedder.name,
            embedder_model=getattr(embedder, "model_name", embedder.name),
            embedding_dim=int(embedder.dim),
            chunk_count=len(chunks),
            built_at=_now_iso(),
            source_counts=source_counts,
        )

        chunks_text = "\n".join(json.dumps(rec, ensure_ascii=False) for rec in chunk_records)
        if chunks_text:
            chunks_text += "\n"
        _atomic_write_text(self.root / CHUNKS_FILENAME, chunks_text)

        npy_path = self.root / EMBEDDINGS_FILENAME
        npy_path.parent.mkdir(parents=True, exist_ok=True)
        # np.save auto-appends `.npy` if missing, so we hand it a path that
        # already ends with `.npy` to avoid surprises during the rename.
        fd, tmp_name = tempfile.mkstemp(
            dir=str(npy_path.parent), prefix=npy_path.stem + ".", suffix=".npy"
        )
        os.close(fd)
        tmp_npy = Path(tmp_name)
        try:
            np.save(tmp_npy, embeddings, allow_pickle=False)
            os.replace(tmp_npy, npy_path)
        except Exception:
            try:
                tmp_npy.unlink()
            except OSError:
                pass
            raise

        _atomic_write_text(self.root / META_FILENAME, json.dumps(meta.to_dict(), indent=2))

        self._chunks = chunk_records
        self._embeddings = embeddings
        self._meta = meta
        return meta

    # ---------- Load / inspect ----------

    @classmethod
    def exists(cls, root: Path) -> bool:
        root = Path(root)
        return (
            (root / CHUNKS_FILENAME).is_file()
            and (root / EMBEDDINGS_FILENAME).is_file()
            and (root / META_FILENAME).is_file()
        )

    def load(self) -> IndexMeta:
        if not self.exists(self.root):
            raise VectorIndexMissingError(
                f"No vector index at {self.root}. Run `emc-assistant knowledge index`."
            )
        with (self.root / CHUNKS_FILENAME).open("r", encoding="utf-8") as fh:
            self._chunks = [json.loads(line) for line in fh if line.strip()]
        self._embeddings = np.load(self.root / EMBEDDINGS_FILENAME, allow_pickle=False).astype(np.float32)
        meta_raw = json.loads((self.root / META_FILENAME).read_text(encoding="utf-8"))
        self._meta = IndexMeta(
            embedder_name=meta_raw["embedder_name"],
            embedder_model=meta_raw["embedder_model"],
            embedding_dim=int(meta_raw["embedding_dim"]),
            chunk_count=int(meta_raw["chunk_count"]),
            built_at=meta_raw["built_at"],
            source_counts=dict(meta_raw.get("source_counts", {})),
        )
        return self._meta

    @property
    def chunks(self) -> list[dict]:
        return list(self._chunks)

    @property
    def meta(self) -> IndexMeta | None:
        return self._meta

    # ---------- Search ----------

    def search(
        self,
        query: str,
        embedder: Embedder,
        *,
        k: int = 5,
    ) -> list[SearchHit]:
        if not self._chunks or self._embeddings.shape[0] == 0:
            return []
        if embedder.dim != self._embeddings.shape[1]:
            raise ValueError(
                f"Embedder dim {embedder.dim} does not match index dim "
                f"{self._embeddings.shape[1]}. Rebuild the index with the same model "
                f"(was: {self._meta.embedder_model if self._meta else 'unknown'})."
            )
        q_matrix = embedder.embed([query])
        if q_matrix.shape[0] == 0:
            return []
        # Both query and corpus are L2-normalised → dot product is cosine.
        scores = (self._embeddings @ q_matrix[0]).astype(np.float32)
        k = min(int(k), len(scores))
        if k <= 0:
            return []
        # `argpartition` is O(n) for top-K; sort the K afterwards for stable order.
        top_idx = np.argpartition(-scores, k - 1)[:k]
        top_idx = top_idx[np.argsort(-scores[top_idx])]
        return [SearchHit(chunk=dict(self._chunks[int(i)]), score=float(scores[int(i)])) for i in top_idx]
