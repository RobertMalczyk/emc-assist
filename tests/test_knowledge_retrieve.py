"""Tests for keyword retrieval + the copyright-safe redaction layer."""

from __future__ import annotations

import json
from pathlib import Path

from emc_assistant.knowledge.retrieve import (
    MAX_EXCERPT_CHARS,
    PERMISSIVE_ALLOWED_USE,
    Snippet,
    redact_for_llm,
    retrieve_for_keywords,
    retrieve_redacted,
    retrieve_top_k,
)
from emc_assistant.knowledge.loader import KnowledgeBase, ParasiticRule
from emc_assistant.llm.assistant import ProblemContext


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


def test_retrieve_top_k_from_seed_returns_scored_results():
    """With the bundled seed `.jsonl`, conducted-EMI context should match rules."""
    snippets = retrieve_top_k(_ctx(), k=5)
    assert len(snippets) > 0
    assert all(s.score > 0 for s in snippets)
    # results are sorted high-to-low
    scores = [s.score for s in snippets]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_top_k_respects_k():
    snippets = retrieve_top_k(_ctx(), k=3)
    assert len(snippets) <= 3


def test_redact_for_llm_strips_body_when_source_is_restrictive():
    """The headline copyright-redaction guarantee: long bodies don't leak.

    A 5000-char source body with allowed_use='link_and_summary' (which is
    NOT in PERMISSIVE_ALLOWED_USE) must produce a RedactedSnippet that
    carries the source_id but no part of the body.
    """
    long_body = "PROPRIETARY VENDOR TEXT " * 250  # ~5000 chars
    assert len(long_body) > 4000
    snippet = Snippet(
        rule_id="R-003",
        source_id="SRC-001",
        score=10.0,
        summary="Our own summary of LISN setup",
        raw_body=long_body,
        allowed_use="link_and_summary",
    )
    redacted = redact_for_llm(snippet)
    assert redacted.rule_id == "R-003"
    assert redacted.source_id == "SRC-001"
    assert redacted.summary == "Our own summary of LISN setup"
    assert redacted.excerpt is None, "Restrictive source must not contribute an excerpt"
    # Hard assertion: the body must not appear anywhere in the redacted payload.
    payload = json.dumps({
        "rule_id": redacted.rule_id,
        "source_id": redacted.source_id,
        "summary": redacted.summary,
        "excerpt": redacted.excerpt,
    })
    assert "PROPRIETARY VENDOR TEXT" not in payload


def test_redact_for_llm_allows_capped_excerpt_when_source_is_permissive():
    """A source with `allowed_use=internal_reference` can contribute a ≤200-char excerpt."""
    long_body = "x" * 5000
    snippet = Snippet(
        rule_id="R-007",
        source_id="SRC-INT",
        score=5.0,
        summary="Our summary",
        raw_body=long_body,
        allowed_use="internal_reference",
    )
    redacted = redact_for_llm(snippet)
    assert redacted.excerpt is not None
    assert len(redacted.excerpt) <= MAX_EXCERPT_CHARS
    assert redacted.excerpt == "x" * MAX_EXCERPT_CHARS


def test_redact_for_llm_handles_missing_allowed_use_as_restrictive():
    snippet = Snippet(
        rule_id="R-008",
        source_id="SRC-MISSING",
        score=2.0,
        summary="Summary",
        raw_body="proprietary body",
        allowed_use="",
    )
    redacted = redact_for_llm(snippet)
    assert redacted.excerpt is None


def test_redact_for_llm_handles_empty_body_safely():
    snippet = Snippet(
        rule_id="R-009",
        source_id="SRC-INT",
        score=1.0,
        summary="Summary",
        raw_body="",
        allowed_use="internal_reference",
    )
    redacted = redact_for_llm(snippet)
    assert redacted.excerpt is None


def test_permissive_allowed_use_enumerates_only_internal_reference():
    # If we ever widen this set the redaction test pair above needs to
    # be revisited. Locking it down with an explicit assertion.
    assert PERMISSIVE_ALLOWED_USE == {"internal_reference"}


def test_retrieve_redacted_combines_retrieve_and_redact(tmp_path: Path):
    # Pin index_root to a non-existent path to force the M2.7 keyword
    # fallback. Without this, the call would prefer the real vector
    # index at knowledge/processed/ when it exists, which is correct
    # production behaviour but makes the assertion below racy
    # (md-index chunks have no rule_id).
    redacted = retrieve_redacted(_ctx(), k=3, index_root=tmp_path / "nonexistent")
    assert len(redacted) <= 3
    # All seed sources currently have `Use_caution` free text, no
    # explicit `allowed_use=internal_reference` — so excerpts should
    # all be None for the bundled seed.
    assert all(r.excerpt is None for r in redacted)
    assert all(r.rule_id for r in redacted)


def test_retrieve_top_k_with_synthetic_kb(tmp_path: Path, monkeypatch):
    """Verify scoring uses the context tokens, not source metadata alone."""
    pr = [
        ParasiticRule(
            rule_id="R-AAA",
            domain="Conducted EMI / DC/DC",
            structure="buck input filter",
            parasitic="L_dm",
            default_value="1 µH",
            range_or_sensitivity="0.47–4.7 µH",
            formula="",
            inputs_needed="",
            use_when="conducted EMI mitigation in DC/DC buck",
            ltspice_representation="",
            confidence="High",
            source_ids=["S001"],
        ),
        ParasiticRule(
            rule_id="R-BBB",
            domain="Radiated EMI",  # unrelated
            structure="antenna feed",
            parasitic="R",
            default_value="50 ohm",
            range_or_sensitivity="",
            formula="",
            inputs_needed="",
            use_when="",
            ltspice_representation="",
            confidence="Medium",
            source_ids=["S002"],
        ),
    ]
    kb = KnowledgeBase(parasitic_rules=pr, emc_rules=[])
    results = retrieve_top_k(_ctx(), kb=kb, k=5, seed_dir=tmp_path)
    # R-AAA should beat R-BBB because the context mentions buck + EMI + DC/DC.
    assert results[0].rule_id == "R-AAA"


# ---- M2.9.1 per-agent retrieval -------------------------------------------


def test_retrieve_for_keywords_keyword_fallback_returns_redacted():
    """With no vector index, retrieve_for_keywords scores seed rules
    against the agent's keyword tokens and returns redacted snippets."""
    redacted = retrieve_for_keywords(
        ["decoupling", "esr", "esl", "capacitor"],
        _ctx(),
        k=4,
        index_root=Path("does/not/exist"),
    )
    assert len(redacted) <= 4
    # Redaction contract holds: seed sources are restrictive -> no excerpt.
    assert all(r.excerpt is None for r in redacted)
    # Every hit carries a rule_id (seed rules always have one).
    assert all(r.rule_id for r in redacted)


def test_retrieve_for_keywords_different_keywords_give_different_hits():
    """The whole point of M2.9.1: a decoupling-keyword query and a
    filtering-keyword query should not return the same snippet set."""
    decoupling = retrieve_for_keywords(
        ["decoupling", "esr", "esl", "srf", "antiresonance", "mlcc"],
        _ctx(), k=6, index_root=Path("does/not/exist"),
    )
    filtering = retrieve_for_keywords(
        ["filter", "damping", "ferrite", "common mode choke", "cmrr"],
        _ctx(), k=6, index_root=Path("does/not/exist"),
    )
    dec_ids = {r.rule_id for r in decoupling}
    filt_ids = {r.rule_id for r in filtering}
    # They may overlap a little, but must not be identical sets.
    assert dec_ids != filt_ids, "per-keyword retrieval collapsed to one result set"


def test_retrieve_for_keywords_empty_keywords_still_returns_something():
    """An agent with no keyword matches still gets topology-grounded hits
    (the query keeps topology + scope), or an empty list -- never raises."""
    out = retrieve_for_keywords([], _ctx(), k=3, index_root=Path("does/not/exist"))
    assert isinstance(out, list)
    assert len(out) <= 3

