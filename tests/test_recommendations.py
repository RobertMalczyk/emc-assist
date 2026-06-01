"""Tests for the recommendation engine."""

from __future__ import annotations

import json
import re
from pathlib import Path

try:
    import jsonschema
except ImportError:
    jsonschema = None  # type: ignore[assignment]

from emc_assistant.parasitics.calculators import (
    trace_capacitance_from_z0_delay,
    trace_inductance_no_plane,
    trace_resistance,
)
from emc_assistant.recommendations.engine import build_baseline_recommendations


REPO_ROOT = Path(__file__).resolve().parents[1]
REC_SCHEMA = REPO_ROOT / "schemas" / "recommendation.schema.json"


def test_recommendations_have_required_fields():
    parasitics = [
        trace_resistance(length_mm=10.0, width_mm=0.5),
        trace_inductance_no_plane(length_mm=10.0, width_mm=0.5),
        trace_capacitance_from_z0_delay(length_mm=10.0, z0_ohm=50.0, delay_ps_per_mm=6.7),
    ]
    recs = build_baseline_recommendations(parasitics)
    assert recs
    pattern = re.compile(r"^REC-[0-9]{3,}$")
    for r in recs:
        assert pattern.match(r.id), r.id
        assert r.severity in {"info", "low", "medium", "high", "critical"}
        assert 0.0 <= r.confidence <= 1.0
        assert r.problem
        assert r.proposed_change.get("description")


def test_recommendations_match_schema():
    if jsonschema is None:
        return  # pragma: no cover — skip when jsonschema is unavailable
    schema = json.loads(REC_SCHEMA.read_text(encoding="utf-8"))
    parasitics = [trace_resistance(length_mm=5.0, width_mm=0.3)]
    recs = build_baseline_recommendations(parasitics)
    validator = jsonschema.Draft202012Validator(schema)
    for r in recs:
        errors = list(validator.iter_errors(r.to_schema_dict()))
        assert not errors, errors
