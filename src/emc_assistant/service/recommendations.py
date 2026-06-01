"""Recommendation accept/reject feedback loop — service layer (M2.12)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

from emc_assistant.logging_setup import get_logger
from emc_assistant.recommendations.decisions import Decision, DecisionLog
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError

_log = get_logger("recommendations")


def load_recommendations_from_findings(layout) -> list[dict]:
    """Collect recommendation dicts from ``results/findings/*.json``.

    Each finding file is an ``AgentFinding`` schema dict; its
    ``recommendations`` carry ``id`` and ``area``. Returns a flat list.
    """
    findings_dir = layout.results_dir / "findings"
    out: list[dict] = []
    if not findings_dir.is_dir():
        return out
    for path in sorted(findings_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for rec in data.get("recommendations", []) if isinstance(data, dict) else []:
            if isinstance(rec, dict) and rec.get("id"):
                rec.setdefault("area", data.get("agent") or data.get("area") or "")
                out.append(rec)
    return out


def summarise_proposed_change(pc: dict) -> str:
    """One-line summary of a recommendation's ``proposed_change`` dict."""
    if not isinstance(pc, dict):
        return ""
    kind = str(pc.get("type", "")).strip()
    desc = str(pc.get("description", "")).strip()
    if kind and desc:
        return f"{kind}: {desc}"[:200]
    return (kind or desc)[:200]


# ---- list ------------------------------------------------------------------


@dataclass
class RecommendationRow:
    area: str
    rec_id: str
    status: str          # accepted | rejected | proposed
    severity: str
    problem: str
    # Full content the Findings screen renders (the summary row alone is
    # not enough). All optional so the lighter callers (Projects counts)
    # keep working unchanged.
    confidence: float = 0.0
    proposal: str = ""
    evidence: list = field(default_factory=list)
    limitations: list = field(default_factory=list)
    sources: list = field(default_factory=list)
    citations: list = field(default_factory=list)
    user_action: str = ""
    reason: str = ""     # rejection reason from the decision log


@dataclass
class RecommendationsListResult:
    project_id: str
    rows: list[RecommendationRow]


def list_recommendations(project_root) -> RecommendationsListResult:
    """List every recommendation from the findings + its decision status,
    with the full content the Findings screen renders."""
    config, layout = require_project(project_root)
    recs = load_recommendations_from_findings(layout)
    log = DecisionLog.load(layout.decisions_dir)

    def _strs(v) -> list:
        return [str(x) for x in v] if isinstance(v, list) else []

    rows = []
    for rec in recs:
        area = str(rec.get("area", ""))
        rec_id = str(rec.get("id", ""))
        key = f"{area}/{rec_id}"
        reason = log.rejected[key].reason if key in log.rejected else ""
        try:
            confidence = float(rec.get("confidence", 0) or 0)
        except (TypeError, ValueError):
            confidence = 0.0
        rows.append(RecommendationRow(
            area=area,
            rec_id=rec_id,
            status=log.status_of(area, rec_id),
            severity=str(rec.get("severity", "?")),
            problem=str(rec.get("problem", "")).replace("\n", " "),
            confidence=confidence,
            proposal=summarise_proposed_change(rec.get("proposed_change", {})),
            evidence=_strs(rec.get("evidence")),
            limitations=_strs(rec.get("limitations")),
            sources=_strs(rec.get("sources")),
            citations=_strs(rec.get("citations")),
            user_action=str(rec.get("user_action", "")),
            reason=reason,
        ))
    return RecommendationsListResult(project_id=config.project_id, rows=rows)


# ---- accept / reject -------------------------------------------------------


@dataclass
class DecideResult:
    key: str
    status: str
    reason: str
    decisions_dir: Path
    found_in_findings: bool


def decide_recommendation(
    project_root, key: str, status: str, reason: str = ""
) -> DecideResult:
    """Record an accept/reject decision for ``<area>/<rec_id>``."""
    _config, layout = require_project(project_root)
    key = str(key).strip()
    if "/" not in key:
        raise ServiceError(
            f"Key must be <area>/<rec_id> (e.g. filtering/REC-003); got {key!r}"
        )
    area, rec_id = key.split("/", 1)
    reason = str(reason or "").strip()
    if status == "rejected" and not reason:
        raise ServiceError("A reject needs --reason explaining why.")
    by_key = {
        f"{r.get('area','')}/{r.get('id','')}": r
        for r in load_recommendations_from_findings(layout)
    }
    snap = by_key.get(key)
    if snap is None:
        _log.warning(
            f"[warn] {key} not found in results/findings/ — recording the "
            "decision anyway (run the pipeline to populate findings)."
        )
    log = DecisionLog.load(layout.decisions_dir)
    log.record(
        Decision(
            area=area,
            rec_id=rec_id,
            status=status,
            reason=reason,
            problem=str((snap or {}).get("problem", "")),
            proposed_change=summarise_proposed_change(
                (snap or {}).get("proposed_change", {})
            ),
        )
    )
    log.save(layout.decisions_dir)
    return DecideResult(
        key=key,
        status=status,
        reason=reason,
        decisions_dir=layout.decisions_dir,
        found_in_findings=snap is not None,
    )
