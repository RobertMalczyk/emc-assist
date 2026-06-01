"""Recommendation accept/reject decision log (M2.12).

Persists the user's accept/reject choices on agent recommendations to
``decisions/accepted_changes.json`` and ``decisions/rejected_changes.json``
inside the project. A decision survives across pipeline runs, so the
report can show each recommendation's status and a rejected mitigation
is flagged rather than silently re-proposed.

A recommendation is keyed ``<area>/<rec_id>`` (e.g. ``filtering/REC-003``).
The key is stable for deterministic recommendations; for LLM-written
recommendations whose ids/order can drift between runs the match is
best-effort, and the stored ``problem`` snapshot keeps the record
auditable either way.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

ACCEPTED_FILE = "accepted_changes.json"
REJECTED_FILE = "rejected_changes.json"
_VALID_STATUS = ("accepted", "rejected")
PROPOSED = "proposed"


def decision_key(area: str, rec_id: str) -> str:
    """Stable key for a recommendation — ``<area>/<rec_id>``."""
    return f"{area}/{rec_id}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Decision:
    """One accept/reject decision on a recommendation."""

    area: str
    rec_id: str
    status: str  # "accepted" | "rejected"
    reason: str = ""
    timestamp: str = ""
    problem: str = ""  # snapshot of the recommendation, for audit
    proposed_change: str = ""  # snapshot summary
    bom_cost_estimate: str = ""  # optional, user-supplied
    side_risks: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in _VALID_STATUS:
            raise ValueError(f"status must be accepted|rejected; got {self.status!r}")
        if not self.area or not self.rec_id:
            raise ValueError("Decision needs a non-empty area and rec_id")
        if not self.timestamp:
            self.timestamp = _utc_now()

    @property
    def key(self) -> str:
        return decision_key(self.area, self.rec_id)

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "area": self.area,
            "rec_id": self.rec_id,
            "status": self.status,
            "reason": self.reason,
            "timestamp": self.timestamp,
            "problem": self.problem,
            "proposed_change": self.proposed_change,
            "bom_cost_estimate": self.bom_cost_estimate,
            "side_risks": list(self.side_risks),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Decision":
        return cls(
            area=str(d.get("area", "")),
            rec_id=str(d.get("rec_id", "")),
            status=str(d.get("status", "")),
            reason=str(d.get("reason", "")),
            timestamp=str(d.get("timestamp", "")),
            problem=str(d.get("problem", "")),
            proposed_change=str(d.get("proposed_change", "")),
            bom_cost_estimate=str(d.get("bom_cost_estimate", "")),
            side_risks=[str(x) for x in d.get("side_risks", []) if str(x)],
        )


@dataclass
class DecisionLog:
    """In-memory accept/reject log, persisted to two JSON files."""

    accepted: dict[str, Decision] = field(default_factory=dict)
    rejected: dict[str, Decision] = field(default_factory=dict)

    @classmethod
    def load(cls, decisions_dir: Path) -> "DecisionLog":
        """Read the two JSON files; missing or malformed files → empty."""
        log = cls()
        for fname, bucket in (
            (ACCEPTED_FILE, log.accepted),
            (REJECTED_FILE, log.rejected),
        ):
            path = Path(decisions_dir) / fname
            if not path.is_file():
                continue
            try:
                rows = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                continue
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                try:
                    d = Decision.from_dict(row)
                except ValueError:
                    continue
                bucket[d.key] = d
        return log

    def status_of(self, area: str, rec_id: str) -> str:
        """``"accepted"`` | ``"rejected"`` | ``"proposed"`` (no decision)."""
        key = decision_key(area, rec_id)
        if key in self.accepted:
            return "accepted"
        if key in self.rejected:
            return "rejected"
        return PROPOSED

    def get(self, area: str, rec_id: str) -> Decision | None:
        key = decision_key(area, rec_id)
        return self.accepted.get(key) or self.rejected.get(key)

    def record(self, decision: Decision) -> None:
        """Record a decision, moving the key out of the opposite bucket."""
        self.accepted.pop(decision.key, None)
        self.rejected.pop(decision.key, None)
        bucket = self.accepted if decision.status == "accepted" else self.rejected
        bucket[decision.key] = decision

    def all(self) -> list[Decision]:
        return [
            *sorted(self.accepted.values(), key=lambda d: d.key),
            *sorted(self.rejected.values(), key=lambda d: d.key),
        ]

    def save(self, decisions_dir: Path) -> None:
        """Write both JSON files (sorted by key for stable diffs)."""
        decisions_dir = Path(decisions_dir)
        decisions_dir.mkdir(parents=True, exist_ok=True)
        for fname, bucket in (
            (ACCEPTED_FILE, self.accepted),
            (REJECTED_FILE, self.rejected),
        ):
            rows = [d.to_dict() for d in sorted(bucket.values(), key=lambda d: d.key)]
            (decisions_dir / fname).write_text(
                json.dumps(rows, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
