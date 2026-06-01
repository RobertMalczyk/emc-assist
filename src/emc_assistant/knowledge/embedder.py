"""`Embedder` interface and two implementations.

- `EmbedderStub` — deterministic hash-based fake. Always available (no
  optional deps). Used in tests and as a `--llm none` fallback when the
  user hasn't installed the `[embeddings]` extra.
- `SentenceTransformersEmbedder` — real, default model
  `sentence-transformers/all-MiniLM-L6-v2`. Requires `[embeddings]`
  extra; raises a clear error if not installed.

Both produce ``numpy.ndarray`` of shape ``(n, dim)``, dtype float32,
L2-normalised so retrieval can use plain dot product for cosine
similarity.
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod

import numpy as np


DEFAULT_SENTENCE_TRANSFORMERS_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
"""Default embedding model: MiniLM-L6-v2. 384-dim, ~80 MB, CPU-fast.

To override at runtime use the `--embedder-model` flag or set
`EMC_ASSISTANT_EMBEDDER_MODEL` in the environment. Larger models like
`sentence-transformers/all-mpnet-base-v2` (768-dim, ~420 MB) trade
download size / latency for better technical-document quality.
"""


STUB_EMBED_DIM = 64
"""Tiny embedding dimension used by `EmbedderStub`. Just big enough that
top-K results don't collide in CI but small enough to keep test
artefacts trivial."""


def _normalise(matrix: np.ndarray) -> np.ndarray:
    """L2-normalise rows; safe on zero rows (stays zero)."""
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    norms = np.where(norms == 0.0, 1.0, norms)
    return (matrix / norms).astype(np.float32)


class Embedder(ABC):
    """Abstract base — embed a batch of strings to a `(n, dim)` matrix."""

    name: str = "abstract"
    """Short identifier for logs and the index metadata file."""

    dim: int = 0
    """Embedding dimension. Concrete subclasses set this in `__init__`."""

    @abstractmethod
    def embed(self, texts: list[str]) -> np.ndarray:
        """Return an ``(n, dim)`` float32 L2-normalised matrix."""


class EmbedderStub(Embedder):
    """Deterministic hash-based embedder for CI.

    Uses SHA-256 of each input string seeded into ``numpy.random`` to
    produce a stable ``STUB_EMBED_DIM``-vector. Two equal strings always
    embed to the same vector; two different strings embed to different
    vectors (with overwhelming probability for any non-trivial corpus).

    The resulting embedding has no semantic meaning whatsoever — it is
    NOT a substitute for the real model. Tests should assert structure
    (round-trip, top-K shape, fallback behaviour) rather than ranking
    quality.
    """

    name = "stub"

    def __init__(self, dim: int = STUB_EMBED_DIM) -> None:
        self.dim = int(dim)

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        rows = []
        for text in texts:
            digest = hashlib.sha256(text.encode("utf-8")).digest()
            seed = int.from_bytes(digest[:8], "big", signed=False) % (2**32 - 1)
            rng = np.random.default_rng(seed)
            rows.append(rng.standard_normal(self.dim).astype(np.float32))
        return _normalise(np.stack(rows))


class SentenceTransformersEmbedder(Embedder):
    """Real `sentence-transformers` embedder.

    Lazy-imports the package so installing the base distribution does
    not pull in torch. On first instantiation downloads the model to
    the user's Hugging Face cache (~80 MB for MiniLM-L6-v2).

    `embed()` batches internally; the wrapper just collects results and
    normalises.
    """

    name = "sentence-transformers"

    def __init__(self, model_name: str = DEFAULT_SENTENCE_TRANSFORMERS_MODEL) -> None:
        try:
            from sentence_transformers import SentenceTransformer  # type: ignore
        except ImportError as exc:  # pragma: no cover - tested by friendly-error path
            raise RuntimeError(
                "Embedding requires the `[embeddings]` extra. Install with: "
                "pip install 'emc-assistant[embeddings]'"
            ) from exc
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        # SentenceTransformer exposes the dim via .get_sentence_embedding_dimension().
        self.dim = int(self._model.get_sentence_embedding_dimension())

    def embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        arr = self._model.encode(
            texts,
            convert_to_numpy=True,
            normalize_embeddings=False,  # we normalise ourselves
            show_progress_bar=False,
        )
        arr = arr.astype(np.float32)
        return _normalise(arr)


def make_embedder(
    *,
    model_name: str | None = None,
    use_stub: bool = False,
) -> Embedder:
    """Convenience factory.

    `use_stub=True` always returns `EmbedderStub` — for tests.
    Otherwise constructs `SentenceTransformersEmbedder` (which surfaces
    a friendly error if the `[embeddings]` extra isn't installed).
    """
    if use_stub:
        return EmbedderStub()
    return SentenceTransformersEmbedder(
        model_name=model_name or DEFAULT_SENTENCE_TRANSFORMERS_MODEL
    )
