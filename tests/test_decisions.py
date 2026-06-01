"""Tests for M2.12 — the recommendation accept/reject decision log."""

from __future__ import annotations

import pytest

from emc_assistant.project.model import ProjectConfig
from emc_assistant.recommendations.decisions import (
    Decision,
    DecisionLog,
    decision_key,
)
from emc_assistant.recommendations.engine import Recommendation
from emc_assistant.reports.markdown import ReportContext, render_markdown_report


# ---- Decision dataclass ----------------------------------------------------


def test_decision_key_and_defaults():
    d = Decision(area="filtering", rec_id="REC-003", status="accepted")
    assert d.key == "filtering/REC-003"
    assert decision_key("filtering", "REC-003") == "filtering/REC-003"
    assert d.timestamp  # auto-stamped


def test_decision_rejects_bad_status():
    with pytest.raises(ValueError):
        Decision(area="a", rec_id="r", status="maybe")


def test_decision_rejects_empty_area_or_id():
    with pytest.raises(ValueError):
        Decision(area="", rec_id="r", status="accepted")
    with pytest.raises(ValueError):
        Decision(area="a", rec_id="", status="accepted")


def test_decision_round_trip():
    d = Decision(
        area="dcdc", rec_id="REC-002", status="rejected",
        reason="too costly", problem="hot loop", proposed_change="add damper",
        bom_cost_estimate="$0.40", side_risks=["loop stability"],
    )
    d2 = Decision.from_dict(d.to_dict())
    assert d2.key == d.key
    assert d2.status == "rejected" and d2.reason == "too costly"
    assert d2.side_risks == ["loop stability"]


# ---- DecisionLog -----------------------------------------------------------


def test_decision_log_empty_dir(tmp_path):
    log = DecisionLog.load(tmp_path)
    assert log.all() == []
    assert log.status_of("filtering", "REC-001") == "proposed"


def test_decision_log_record_and_status(tmp_path):
    log = DecisionLog.load(tmp_path)
    log.record(Decision(area="filtering", rec_id="REC-001", status="accepted"))
    log.record(Decision(area="dcdc", rec_id="REC-002", status="rejected",
                         reason="no"))
    assert log.status_of("filtering", "REC-001") == "accepted"
    assert log.status_of("dcdc", "REC-002") == "rejected"
    assert log.status_of("dcdc", "REC-099") == "proposed"


def test_decision_log_record_moves_buckets(tmp_path):
    """Re-deciding a key moves it out of the opposite bucket."""
    log = DecisionLog.load(tmp_path)
    log.record(Decision(area="a", rec_id="R1", status="accepted"))
    assert log.status_of("a", "R1") == "accepted"
    log.record(Decision(area="a", rec_id="R1", status="rejected", reason="changed"))
    assert log.status_of("a", "R1") == "rejected"
    assert "a/R1" not in log.accepted
    assert len(log.all()) == 1  # not duplicated across buckets


def test_decision_log_save_load_round_trip(tmp_path):
    log = DecisionLog.load(tmp_path)
    log.record(Decision(area="filtering", rec_id="REC-001", status="accepted",
                         reason="agreed"))
    log.record(Decision(area="dcdc", rec_id="REC-005", status="rejected",
                         reason="cost"))
    log.save(tmp_path)
    assert (tmp_path / "accepted_changes.json").is_file()
    assert (tmp_path / "rejected_changes.json").is_file()

    reloaded = DecisionLog.load(tmp_path)
    assert reloaded.status_of("filtering", "REC-001") == "accepted"
    assert reloaded.status_of("dcdc", "REC-005") == "rejected"
    assert reloaded.get("dcdc", "REC-005").reason == "cost"


def test_decision_log_tolerates_malformed_file(tmp_path):
    (tmp_path / "accepted_changes.json").write_text("not json", encoding="utf-8")
    log = DecisionLog.load(tmp_path)  # must not raise
    assert log.all() == []


# ---- report status badges --------------------------------------------------


def _report_ctx(decision_log):
    project = ProjectConfig(
        project_id="t", name="t", version="0.1", created_at="2026-01-01",
        analysis_scope="conducted_emi_dc_dc",
    )
    recs = [
        Recommendation(id="REC-001", area="filtering", severity="high",
                       confidence=0.6, problem="underdamped input filter"),
        Recommendation(id="REC-002", area="dcdc", severity="medium",
                       confidence=0.5, problem="hot loop"),
    ]
    return ReportContext(
        project=project, parasitics=[], recommendations=recs,
        decision_log=decision_log,
    )


def test_report_shows_decision_badges():
    log = DecisionLog()
    log.record(Decision(area="filtering", rec_id="REC-001", status="accepted"))
    log.record(Decision(area="dcdc", rec_id="REC-002", status="rejected",
                         reason="already fixed in rev B"))
    md = render_markdown_report(_report_ctx(log))
    assert "[ACCEPTED]" in md
    assert "[REJECTED]" in md
    assert "already fixed in rev B" in md


def test_report_no_badges_without_decision_log():
    md = render_markdown_report(_report_ctx(None))
    assert "[ACCEPTED]" not in md
    assert "[REJECTED]" not in md
