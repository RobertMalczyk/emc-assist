"""Tests for the variant-ranking module."""

from __future__ import annotations

import pytest

from emc_assistant.results.ranking import rank_variants


def test_ranking_basic_lower_is_better():
    data = [
        ("baseline", {"vpeak": 1.0}),
        ("var-a", {"vpeak": 0.6}),
        ("var-b", {"vpeak": 1.4}),
    ]
    ranked = rank_variants(data, metric_key="vpeak", lower_is_better=True)
    assert [r.label for r in ranked] == ["var-a", "baseline", "var-b"]
    assert ranked[0].rank == 1 and ranked[1].rank == 2 and ranked[2].rank == 3
    rank_a = next(r for r in ranked if r.label == "var-a")
    assert rank_a.delta == pytest.approx(-0.4)
    assert rank_a.delta_pct == pytest.approx(-40.0)


def test_ranking_higher_is_better():
    data = [
        ("baseline", {"margin": 6.0}),
        ("var-a", {"margin": 4.0}),
        ("var-b", {"margin": 9.0}),
    ]
    ranked = rank_variants(data, metric_key="margin", lower_is_better=False)
    assert ranked[0].label == "var-b"


def test_ranking_skips_missing_metric():
    data = [("baseline", {"vpeak": 1.0}), ("var-a", {"other": 2.0})]
    ranked = rank_variants(data, metric_key="vpeak")
    assert [r.label for r in ranked] == ["baseline"]


def test_ranking_handles_no_baseline():
    data = [("var-a", {"x": 1.0}), ("var-b", {"x": 2.0})]
    ranked = rank_variants(data, metric_key="x", lower_is_better=True)
    # No baseline → delta is None.
    assert all(r.delta is None for r in ranked)
