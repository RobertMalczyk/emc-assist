# `processed/`

Local index built by `emc-assistant knowledge index`. Contains:

| File | Purpose |
|---|---|
| `chunks.jsonl` | One JSON object per chunk: `chunk_id`, `source_id`, `rule_id`, `text`, `source_type`, `file_path`, `tier` (`seed` / `raw_sources` / `user_private_sources` / `licensed_sources`). |
| `embeddings.npy` | NumPy array shape `(n_chunks, embed_dim)`. Row `i` corresponds to `chunks.jsonl` line `i+1`. Float32. |
| `index_meta.json` | Build metadata: embedder name + model, chunk count, source counts per tier, build timestamp, mtime checksums per source. |

The on-disk format is intentionally simple — no FAISS / Chroma database, no opaque binary blobs. You can inspect everything with `head chunks.jsonl` and `python -c "import numpy as np; print(np.load('embeddings.npy').shape)"`.

## How to rebuild

```bash
emc-assistant knowledge index
# … walks knowledge/{seed,raw_sources,user_private_sources,licensed_sources}/
# … chunks each supported file
# … embeds with the configured model
# … writes chunks.jsonl + embeddings.npy + index_meta.json atomically here
```

`knowledge index` is idempotent — re-running rewrites the three files atomically (tmpfile → rename). A crashed build never corrupts an existing index.

To upgrade the embedding model:

```bash
emc-assistant knowledge index --embedder-model sentence-transformers/all-mpnet-base-v2
```

Old `chunks.jsonl` text is reused; only embeddings are recomputed. The `index_meta.json` records which model was used so retrieval can refuse to run if the configured model and the index model disagree.

## Gitignore

This directory is entirely gitignored except for this README. The index is rebuilt by the user on first run.
