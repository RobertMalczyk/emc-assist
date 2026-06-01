# Knowledge-source ingestion

## Assumption

The user has downloaded public vendor materials, application notes, and articles. Claude Code should neither fetch them on its own nor assume internet access.

## Directories

```text
knowledge/
  seed/          # prepared JSONL/XLSX/MD with rules and metadata
  raw_sources/   # user-supplied HTML/PDF/TXT/MD downloads
  processed/     # summaries, chunked text, local index
```

## Naming convention for `raw_sources`

Recommended format:

```text
<SOURCE_ID>__<short_slug>.<ext>
```

Examples:

```text
SRC-001__analog_ltspice_emc_part1.html
SRC-003__analog_cm_dm_conducted_emissions.html
S001__ti_pcb_design_guidelines_reduced_emi.pdf
S003__wuerth_emc_design_tips_2025.pdf
```

## Allowed actions on sources

- read locally,
- produce short summaries,
- produce notes in our own words,
- link to the original,
- quote short excerpts under fair-use rules.

## Not allowed

- copying full PDFs into the product as our own content,
- training a model on paid standards without a license,
- distributing vendor libraries without checking the license,
- generating standard limit tables from memory,
- pretending sources are open-source when they are only publicly accessible.

## Minimum MVP ingestion

- read `knowledge/seed/*sources.jsonl`,
- read `knowledge/seed/*rules.jsonl`,
- search by tags and domains,
- map `Rule_ID -> Source_ID`,
- report the list of rules and sources used.

## Later ingestion

- text extraction from PDF,
- chunking,
- local or cloud embeddings,
- reranking,
- citations to sources,
- company-private knowledge sources.
