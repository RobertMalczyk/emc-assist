"""Tests for the knowledge-base loader."""

from __future__ import annotations

from emc_assistant.knowledge import load_default_knowledge


def test_knowledge_loads_parasitic_and_emc_rules():
    kb = load_default_knowledge()
    assert kb.parasitic_rules, "expected parasitic rules to be loaded"
    assert kb.emc_rules, "expected EMC rules to be loaded"


def test_knowledge_filter_by_domain():
    kb = load_default_knowledge()
    matches = kb.find_parasitic(domain="trace")
    assert matches, "expected rules for domain~='trace'"
    for rule in matches:
        assert "trace" in rule.domain.lower()


def test_knowledge_filter_emc_by_area():
    kb = load_default_knowledge()
    matches = kb.find_emc(area_contains="emc")
    assert matches, "expected rules containing 'emc' in their area"


def test_source_ids_aggregation_nonempty():
    kb = load_default_knowledge()
    ids = kb.all_source_ids()
    assert ids
    for sid in ids:
        assert isinstance(sid, str)
        assert sid.strip() == sid
