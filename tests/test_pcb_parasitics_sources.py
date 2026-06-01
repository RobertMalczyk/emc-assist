"""Metadata + JSONL validity tests for the PCB-parasitics source set.

Covers the S032-S036 manifest additions and the proposed staging rules
in ``knowledge/seed/staging_pcb_parasitic_trace_rules.jsonl``. No
ingestion code is exercised here — only the manifest / staging files
and the ``staging_`` skip in the chunker walk.
"""

from __future__ import annotations

import json
from pathlib import Path

from emc_assistant.knowledge.chunker import walk_knowledge_dir

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "knowledge" / "seed"
SOURCES_MANIFEST = SEED_DIR / "baza_pasozyty_pcb_sources.jsonl"
STAGING_RULES = SEED_DIR / "staging_pcb_parasitic_trace_rules.jsonl"

NEW_SOURCE_IDS = {"S032", "S033", "S034", "S035", "S036"}

# A rule must never assert EMC compliance (CLAUDE.md guardrail).
_BANNED_COMPLIANCE_PHRASES = (
    "will pass emc",
    "guarantees emc",
    "ensures emc",
    "passes emc",
    "emc compliant",
)


def _read_jsonl(path: Path) -> list[dict]:
    rows: list[dict] = []
    with path.open("r", encoding="utf-8") as fh:
        for line_no, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as exc:  # pragma: no cover - failure path
                raise AssertionError(f"Invalid JSON at {path.name}:{line_no}: {exc}")
    return rows


# ---- source manifest ------------------------------------------------------


def test_sources_manifest_parses():
    rows = _read_jsonl(SOURCES_MANIFEST)
    assert rows, "manifest is empty"


def test_no_duplicate_source_ids():
    rows = _read_jsonl(SOURCES_MANIFEST)
    ids = [r["Source_ID"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate Source_ID in the manifest"


def test_new_sources_present():
    rows = _read_jsonl(SOURCES_MANIFEST)
    ids = {r["Source_ID"] for r in rows}
    assert NEW_SOURCE_IDS <= ids, f"missing: {NEW_SOURCE_IDS - ids}"


def test_new_sources_have_required_fields():
    required = {"Source_ID", "Title", "Organization", "Type", "Topics",
                "URL", "Notes", "Use_caution"}
    rows = {r["Source_ID"]: r for r in _read_jsonl(SOURCES_MANIFEST)}
    for sid in NEW_SOURCE_IDS:
        entry = rows[sid]
        missing = required - set(entry)
        assert not missing, f"{sid} missing fields: {missing}"
        assert entry["Title"].strip(), f"{sid} has empty Title"


def test_new_sources_carry_access_and_allowed_use():
    """access_class + allowed_use are folded into Notes; the license
    warning into Use_caution. All three must be present per source."""
    rows = {r["Source_ID"]: r for r in _read_jsonl(SOURCES_MANIFEST)}
    for sid in NEW_SOURCE_IDS:
        notes = rows[sid]["Notes"].lower()
        caution = rows[sid]["Use_caution"].lower()
        assert "access_class" in notes, f"{sid}: no access_class"
        assert "allowed_use" in notes, f"{sid}: no allowed_use"
        assert "source_type" in notes, f"{sid}: no source_type"
        assert "do_not_redistribute_full_text" in caution, f"{sid}: no license_warning"


# ---- staging rules --------------------------------------------------------


def test_staging_rules_parse():
    rows = _read_jsonl(STAGING_RULES)
    assert 8 <= len(rows) <= 12, f"expected 8-12 staged rules, got {len(rows)}"


def test_no_duplicate_rule_ids():
    rows = _read_jsonl(STAGING_RULES)
    ids = [r["Rule_ID"] for r in rows]
    assert len(ids) == len(set(ids)), "duplicate Rule_ID in the staging file"


def test_staging_rules_required_fields():
    required = {"Rule_ID", "topic", "rule_text", "source_ids", "confidence",
                "use_case", "limitations", "recommended_action",
                "simulation_usage", "tags"}
    for rule in _read_jsonl(STAGING_RULES):
        missing = required - set(rule)
        assert not missing, f"{rule.get('Rule_ID')} missing fields: {missing}"
        assert rule["rule_text"].strip(), f"{rule['Rule_ID']} empty rule_text"
        assert rule["limitations"], f"{rule['Rule_ID']} has no limitations"
        assert rule["confidence"] in {"low", "medium", "high"}, rule["Rule_ID"]


def test_staging_rules_cite_known_sources():
    """Every cited source resolves to a manifest entry or the explicit
    engineering_estimate marker — no dangling / paid-standard ids."""
    known = {r["Source_ID"] for r in _read_jsonl(SOURCES_MANIFEST)}
    known.add("engineering_estimate")
    for rule in _read_jsonl(STAGING_RULES):
        assert rule["source_ids"], f"{rule['Rule_ID']} cites no source"
        for sid in rule["source_ids"]:
            assert sid in known, f"{rule['Rule_ID']} cites unknown source {sid}"


def test_staging_rules_make_no_compliance_claim():
    for rule in _read_jsonl(STAGING_RULES):
        text = rule["rule_text"].lower()
        for phrase in _BANNED_COMPLIANCE_PHRASES:
            assert phrase not in text, f"{rule['Rule_ID']} claims EMC compliance"


def test_staging_rules_prefer_ranges_over_single_values():
    """A rule with a numeric band must give min<=typ<=max, not one value."""
    for rule in _read_jsonl(STAGING_RULES):
        mtm = rule.get("suggested_min_typ_max")
        if mtm is None:
            continue
        assert mtm["min"] <= mtm["typ"] <= mtm["max"], rule["Rule_ID"]
        assert mtm.get("unit"), f"{rule['Rule_ID']} band has no unit"


# ---- staging file is not auto-indexed -------------------------------------


def test_staging_file_excluded_from_index_walk():
    """walk_knowledge_dir must skip staging_* files so proposed rules
    never enter the retrieval index before review."""
    walked = {p.name for p in walk_knowledge_dir(SEED_DIR, tier="seed")}
    assert STAGING_RULES.name not in walked
    # ...but the canonical manifest/rule files are still walked.
    assert "baza_pasozyty_pcb_rules.jsonl" in walked
