"""Tests for hard JSON-schema validation."""

from __future__ import annotations

import pytest

from emc_assistant.parasitics.calculators import trace_resistance
from emc_assistant.recommendations.engine import build_baseline_recommendations
from emc_assistant.schemas import (
    SchemaValidationError,
    require_all_valid,
    require_valid,
)


def test_require_valid_passes_correct_recommendation():
    parasitics = [trace_resistance(length_mm=5.0, width_mm=0.3)]
    recs = build_baseline_recommendations(parasitics)
    for r in recs:
        require_valid("recommendation.schema.json", r.to_schema_dict())


def test_require_valid_rejects_bad_id():
    bad = {
        "id": "NOT-MATCHING",
        "area": "x",
        "severity": "info",
        "confidence": 0.5,
        "problem": "x",
        "evidence": [],
        "proposed_change": {"type": "x", "description": "x"},
        "limitations": [],
    }
    with pytest.raises(SchemaValidationError) as exc:
        require_valid("recommendation.schema.json", bad)
    assert "id" in str(exc.value)


def test_require_all_valid_aggregates_errors():
    parasitic_ok = trace_resistance(length_mm=5.0, width_mm=0.3).to_schema_dict()
    parasitic_bad = dict(parasitic_ok)
    parasitic_bad["structure"] = "not_a_real_structure"
    with pytest.raises(SchemaValidationError) as exc:
        require_all_valid(
            "parasitic_model.schema.json", [parasitic_ok, parasitic_bad]
        )
    assert "[1]" in str(exc.value)
