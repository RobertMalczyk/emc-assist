"""Loader for EMC and PCB-parasitic rules stored as JSONL.

Rules are reference metadata, not directives. Source documents stay
under ``knowledge/raw_sources/`` and are addressed by ``Source_ID`` —
the code never copies their contents.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Sequence

REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SEED_DIR = REPO_ROOT / "knowledge" / "seed"
DEFAULT_PARASITIC_FILE = "baza_pasozyty_pcb_rules.jsonl"
DEFAULT_EMC_FILE = "baza_wiedzy_emc_ltspice_rules.jsonl"


@dataclass
class ParasiticRule:
    rule_id: str
    domain: str
    structure: str
    parasitic: str
    default_value: str
    range_or_sensitivity: str
    formula: str
    inputs_needed: str
    use_when: str
    ltspice_representation: str
    confidence: str
    source_ids: list[str] = field(default_factory=list)
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, obj: dict) -> "ParasiticRule":
        return cls(
            rule_id=str(obj.get("Rule_ID", "")),
            domain=str(obj.get("Domain", "")),
            structure=str(obj.get("Structure", "")),
            parasitic=str(obj.get("Parasitic", "")),
            default_value=str(obj.get("Default_value_for_agent", "")),
            range_or_sensitivity=str(obj.get("Range_or_sensitivity", "")),
            formula=str(obj.get("Formula_or_method", "")),
            inputs_needed=str(obj.get("Inputs_needed", "")),
            use_when=str(obj.get("Use_when", "")),
            ltspice_representation=str(obj.get("LTspice_representation", "")),
            confidence=str(obj.get("Confidence", "")),
            source_ids=[s.strip() for s in str(obj.get("Source_IDs", "")).split(",") if s.strip()],
            raw=obj,
        )


@dataclass
class EmcRule:
    rule_id: str
    area: str
    rule: str
    rationale: str
    source_ids: list[str] = field(default_factory=list)
    agent_action: str = ""
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_json(cls, obj: dict) -> "EmcRule":
        sources = obj.get("source_ids", [])
        if isinstance(sources, str):
            sources = [s.strip() for s in sources.split(",") if s.strip()]
        return cls(
            rule_id=str(obj.get("rule_id", "")),
            area=str(obj.get("area", "")),
            rule=str(obj.get("rule", "")),
            rationale=str(obj.get("rationale", "")),
            source_ids=list(sources),
            agent_action=str(obj.get("agent_action", "")),
            raw=obj,
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
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSONL at {path}:{line_no}: {exc}") from exc
    return rows


@dataclass
class KnowledgeBase:
    parasitic_rules: list[ParasiticRule] = field(default_factory=list)
    emc_rules: list[EmcRule] = field(default_factory=list)
    seed_dir: Path | None = None

    @classmethod
    def from_files(
        cls,
        parasitic_path: Path,
        emc_path: Path,
    ) -> "KnowledgeBase":
        parasitic = [ParasiticRule.from_json(r) for r in _read_jsonl(parasitic_path)]
        emc = [EmcRule.from_json(r) for r in _read_jsonl(emc_path)]
        return cls(parasitic_rules=parasitic, emc_rules=emc, seed_dir=parasitic_path.parent)

    def find_parasitic(
        self,
        *,
        domain: str | None = None,
        structure_contains: str | None = None,
        parasitic_contains: str | None = None,
    ) -> list[ParasiticRule]:
        out: list[ParasiticRule] = []
        for rule in self.parasitic_rules:
            if domain and domain.lower() not in rule.domain.lower():
                continue
            if structure_contains and structure_contains.lower() not in rule.structure.lower():
                continue
            if parasitic_contains and parasitic_contains.lower() not in rule.parasitic.lower():
                continue
            out.append(rule)
        return out

    def find_emc(
        self,
        *,
        area_contains: str | None = None,
        text_contains: str | None = None,
    ) -> list[EmcRule]:
        out: list[EmcRule] = []
        for rule in self.emc_rules:
            if area_contains and area_contains.lower() not in rule.area.lower():
                continue
            if text_contains and text_contains.lower() not in rule.rule.lower():
                continue
            out.append(rule)
        return out

    def all_source_ids(self, rules: Iterable[object] | None = None) -> list[str]:
        ids: set[str] = set()
        candidates: Sequence[object]
        if rules is None:
            candidates = [*self.parasitic_rules, *self.emc_rules]
        else:
            candidates = list(rules)
        for r in candidates:
            for sid in getattr(r, "source_ids", []):
                if sid:
                    ids.add(sid)
        return sorted(ids)


def load_default_knowledge(seed_dir: Path | None = None) -> KnowledgeBase:
    seed_dir = Path(seed_dir) if seed_dir else DEFAULT_SEED_DIR
    return KnowledgeBase.from_files(
        parasitic_path=seed_dir / DEFAULT_PARASITIC_FILE,
        emc_path=seed_dir / DEFAULT_EMC_FILE,
    )
