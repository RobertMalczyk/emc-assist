"""CLI-level tests for the M2.12 `recommendations` command group.

The DecisionLog itself is unit-tested in test_decisions.py; this file
exercises the `recommendations list / accept / reject` CLI commands
end-to-end — the surface the M3 UI will drive.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emc_assistant.cli import main

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _project_with_findings(tmp_path: Path) -> Path:
    """Copy the buck example and plant a minimal results/findings file."""
    project = tmp_path / "case"
    shutil.copytree(EXAMPLE, project)
    for sub in ("generated", "results", "reports", "decisions"):
        shutil.rmtree(project / sub, ignore_errors=True)
    findings = project / "results" / "findings"
    findings.mkdir(parents=True)
    (findings / "dcdc.json").write_text(json.dumps({
        "agent": "dcdc",
        "area": "DC/DC converter",
        "recommendations": [
            {"id": "REC-001", "area": "dcdc", "severity": "high",
             "confidence": 0.6, "problem": "hot loop radiates",
             "proposed_change": {"type": "layout", "description": "tighten loop"}},
            {"id": "REC-002", "area": "dcdc", "severity": "low",
             "confidence": 0.3, "problem": "minor ripple",
             "proposed_change": {"type": "filter", "description": "add cap"}},
        ],
    }), encoding="utf-8")
    return project


def test_recommendations_list(tmp_path: Path, capsys):
    project = _project_with_findings(tmp_path)
    rc = main(["recommendations", "list", str(project)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "dcdc/REC-001" in out and "dcdc/REC-002" in out
    # No decisions yet — every recommendation is "proposed".
    assert out.count("proposed") == 2


def test_recommendations_accept_persists_decision(tmp_path: Path):
    project = _project_with_findings(tmp_path)
    rc = main(["recommendations", "accept", str(project), "dcdc/REC-001",
               "--reason", "agreed"])
    assert rc == 0
    accepted = project / "decisions" / "accepted_changes.json"
    rows = json.loads(accepted.read_text(encoding="utf-8"))
    assert len(rows) == 1
    assert rows[0]["key"] == "dcdc/REC-001"
    assert rows[0]["status"] == "accepted"
    # The recommendation's problem text is snapshotted into the record.
    assert rows[0]["problem"] == "hot loop radiates"


def test_recommendations_reject_requires_reason(tmp_path: Path):
    project = _project_with_findings(tmp_path)
    rc = main(["recommendations", "reject", str(project), "dcdc/REC-002"])
    assert rc == 1  # a reject must carry --reason
    assert not (project / "decisions" / "rejected_changes.json").is_file()


def test_recommendations_reject_persists(tmp_path: Path):
    project = _project_with_findings(tmp_path)
    rc = main(["recommendations", "reject", str(project), "dcdc/REC-002",
               "--reason", "out of BOM budget"])
    assert rc == 0
    rows = json.loads(
        (project / "decisions" / "rejected_changes.json").read_text(encoding="utf-8")
    )
    assert rows[0]["key"] == "dcdc/REC-002"
    assert rows[0]["reason"] == "out of BOM budget"


def test_recommendations_decision_shows_in_list(tmp_path: Path, capsys):
    project = _project_with_findings(tmp_path)
    main(["recommendations", "accept", str(project), "dcdc/REC-001", "--reason", "ok"])
    capsys.readouterr()  # drain
    rc = main(["recommendations", "list", str(project)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "accepted" in out  # REC-001 now shows its status
    assert "proposed" in out  # REC-002 still undecided


def test_recommendations_reject_then_accept_moves_bucket(tmp_path: Path):
    project = _project_with_findings(tmp_path)
    main(["recommendations", "reject", str(project), "dcdc/REC-001", "--reason", "no"])
    main(["recommendations", "accept", str(project), "dcdc/REC-001", "--reason", "yes"])
    decisions = project / "decisions"
    accepted = json.loads((decisions / "accepted_changes.json").read_text(encoding="utf-8"))
    rejected = json.loads((decisions / "rejected_changes.json").read_text(encoding="utf-8"))
    assert [r["key"] for r in accepted] == ["dcdc/REC-001"]
    assert rejected == []  # moved out of the rejected bucket


def test_recommendations_bad_key_rejected(tmp_path: Path):
    project = _project_with_findings(tmp_path)
    rc = main(["recommendations", "accept", str(project), "REC-001", "--reason", "x"])
    assert rc == 1  # key must be <area>/<rec_id>
