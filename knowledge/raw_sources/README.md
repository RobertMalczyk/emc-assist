# `raw_sources/`

User-supplied public source materials downloaded from vendors and standards bodies:

- application notes (Texas Instruments, Analog Devices, Würth Elektronik, Infineon, …)
- public PDFs / HTML / TXT / MD reference documents
- tool documentation

## Drop files here

Recommended naming:

```text
<SOURCE_ID>__<short_slug>.<ext>
```

Examples:

```text
S001__ti_pcb_design_guidelines_reduced_emi.pdf
SRC-022__wuerth_ac_line_filter_calc.pdf
S013__adi_mt_101_decoupling_techniques.pdf
```

The `Source_ID` should match an entry in `knowledge/seed/baza_*_sources.jsonl` so retrieval can stitch a chunk back to its license metadata (`allowed_use`).

## License rules (load-bearing)

Public availability does not equal redistribution rights. Files dropped here are read locally only. M2.8's indexer chunks the body for retrieval scoring, but **the redaction layer (`feedback_copyright_redaction_for_llm` rule) ensures only `rule_id` + `source_id` + our own concise summary leave the machine when an LLM is involved.** A ≤ 200-character verbatim excerpt is sent **only** when the source's `allowed_use` is set to `internal_reference` in the source manifest.

## Gitignore

This directory is tracked (so the README exists), but contents are gitignored — the per-user source corpus does not belong in the public repo.

## Supported file types as of M2.8

- `.md` (heading-aware chunking)
- `.txt` (paragraph-aware)
- `.html` (paragraph-aware, tags stripped)
- `.jsonl` (one chunk per record)
- `.pdf` (requires `pip install emc-assistant[pdf]`)

`.xlsx` is not indexed; convert to JSONL or MD if needed.
