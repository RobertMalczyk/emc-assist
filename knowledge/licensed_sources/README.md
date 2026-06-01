# `licensed_sources/`

Paid or licensed reference content — purchased standards, paid datasheets, paid training materials. The user has explicit rights but redistribution is still restricted.

## Drop files here

```text
LIC-001__cispr25_2026_edition.pdf
LIC-002__murata_extended_spice_library.zip
```

## License / redaction rules

The indexer treats every source here as `allowed_use: check_license` — the strictest setting compatible with usage. That means:

- **Body text never sent to any LLM.** Same protection as `user_private_sources/`.
- Retrieval scoring is local-only.
- The privacy log (`results/llm/<run-id>.jsonl`) shows what was sent and confirms no licensed body text leaked.

When ingesting paid standards, **do not extract limit tables from CISPR / IEC / IPC documents into the indexed text.** The CLAUDE.md guardrail "Nie generuj fikcyjnych limitów norm EMC / Don't generate fake EMC limit tables" plus the no-redistribution rule make limit tables fundamentally off-limits as quoted content.

What is allowed:
- Indexing the document so it can be cited by `Source_ID`.
- Producing your own summaries (in the seed `.jsonl` rules) with rationales.
- Linking to the original document inside your organisation.

## Gitignore

Contents gitignored. Only the README is tracked.
