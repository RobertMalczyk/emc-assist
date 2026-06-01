# `user_private_sources/`

Confidential user-supplied content — NDAs, design reviews, internal lab notes, customer-specific datasheets, hand-written application notes. Treated more conservatively than `raw_sources/`.

## Drop files here

Same naming convention as `raw_sources/` recommended, with the SOURCE_ID prefixed for clarity:

```text
PRIV-001__customer_x_design_review_2026.md
PRIV-002__bench_emi_scan_notes_2026Q1.txt
```

## License / redaction rules

These files are **strictly local**. Even with `--llm openai`, the redaction layer treats every source in this directory as `allowed_use: user_provided_only`, which means:

- **Never sent to the LLM**, not even a 200-character excerpt.
- Indexed locally for retrieval scoring so the deterministic engine can use them.
- A retrieved chunk contributes only its `source_id` + our summary to the prompt — and the summary is derived from the chunk text by the local chunker, never the raw content.

If you want some content to be sendable to the LLM, move it to `raw_sources/` and set the source's `allowed_use` to `internal_reference` in a corresponding source manifest entry.

## Gitignore

This directory is gitignored at the contents level. Only the README is tracked. **Files dropped here will never be committed.**
