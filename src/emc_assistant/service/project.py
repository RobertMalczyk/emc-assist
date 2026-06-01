"""Project-level service operations: create, validate, status.

Also owns :func:`require_project`, the shared "load a project or fail
with a user-facing error" helper that nearly every command needs.
"""

from __future__ import annotations

import datetime as _dt
import json
from dataclasses import dataclass
from pathlib import Path

import yaml

from emc_assistant.project.model import load_project, validate_project_config
from emc_assistant.service.results import ServiceError


def _load_or_raise(project_root):
    """``load_project`` but a missing ``project.yaml`` becomes an
    expected :class:`ServiceError`, not an uncaught ``FileNotFoundError``."""
    try:
        return load_project(project_root)
    except FileNotFoundError as exc:
        raise ServiceError(str(exc)) from exc


def require_project(project_root):
    """Load a project, or raise :class:`ServiceError` if it is missing or
    its ``project.yaml`` does not validate. Returns ``(config, layout)``."""
    config, layout, errors = _load_or_raise(project_root)
    if errors:
        raise ServiceError(
            "Invalid project configuration — aborting:", details=list(errors)
        )
    return config, layout


# ---- create ----------------------------------------------------------------


@dataclass
class CreateProjectResult:
    project_id: str
    root: Path
    config_path: Path
    models_dir: Path


def create_project(project_root) -> CreateProjectResult:
    """Create a new ``.emcproj`` — a validated ``project.yaml`` skeleton
    plus the ``input/models/`` tree. Refuses to overwrite."""
    root = Path(project_root)
    cfg_path = root / "project.yaml"
    if cfg_path.exists():
        raise ServiceError(f"Refusing to overwrite an existing project: {cfg_path}")

    project_id = root.name or "emc_project"
    skeleton = {
        "project_id": project_id,
        "name": project_id,
        "version": "0.1.0",
        "created_at": _dt.date.today().isoformat(),
        "analysis_scope": "conducted_emi_dc_dc",
        "inputs": {
            "netlist_path": "",
            "schematic_path": "",
            "models_dir": "input/models",
        },
        "privacy": {
            "allow_cloud_llm": False,
            "allow_telemetry": False,
            "redact_net_names": True,
        },
        "ltspice": {"executable_path": "", "mode": "dry-run", "timeout_seconds": 120},
    }
    errors = validate_project_config(skeleton)
    if errors:
        raise ServiceError(
            "Internal error — the project skeleton failed schema validation:",
            details=list(errors),
        )

    models_dir = root / "input" / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    cfg_path.write_text(yaml.safe_dump(skeleton, sort_keys=False), encoding="utf-8")
    return CreateProjectResult(
        project_id=project_id,
        root=root,
        config_path=cfg_path,
        models_dir=models_dir,
    )


# ---- set schematic ---------------------------------------------------------


@dataclass
class SetSchematicResult:
    """Outcome of dropping a schematic into a project."""

    project_id: str
    netlist_path: str
    """The new ``inputs.netlist_path`` value (relative to the project root)."""
    schematic_path: str | None
    """The new ``inputs.schematic_path`` for ``.asc`` sources; ``None`` for ``.cir``."""
    destination: Path
    """Absolute path of the file inside ``<project>/input/`` after the copy."""
    copied: bool
    """True when the source was copied; False when it was already inside ``input/``."""


_SCHEMATIC_SUFFIXES = (".asc", ".cir")


def set_schematic(project_root, source_path) -> SetSchematicResult:
    """Drop a schematic into a project — copy ``source_path`` into
    ``<project>/input/`` (unless it is already there) and update
    ``project.yaml`` so ``inputs.netlist_path`` (and ``schematic_path``
    for ``.asc``) reference it.

    Subsequent pipeline runs pick up the new schematic automatically.
    An existing same-named file in ``input/`` is overwritten — the
    semantic is "replace the project's schematic with this one".
    """
    import shutil

    config, layout = require_project(project_root)
    src = Path(source_path)
    if not src.is_file():
        raise ServiceError(f"Source file not found: {source_path}")

    suffix = src.suffix.lower()
    if suffix not in _SCHEMATIC_SUFFIXES:
        raise ServiceError(
            f"Unsupported schematic format {suffix!r} — expected .asc or .cir"
        )

    input_dir = layout.input_dir
    input_dir.mkdir(parents=True, exist_ok=True)
    dest = input_dir / src.name
    # Skip the copy when the source is already inside input/ (idempotent).
    same_file = False
    try:
        same_file = src.resolve() == dest.resolve()
    except OSError:
        same_file = False
    if not same_file:
        shutil.copy2(src, dest)

    rel_netlist = f"input/{src.name}"
    rel_schematic = rel_netlist if suffix == ".asc" else None

    # Persist via the raw YAML so any unrelated keys in project.yaml
    # (user-added metadata, comments stripped on dump, etc.) round-trip.
    cfg_path = layout.root / "project.yaml"
    raw = (
        yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        if cfg_path.is_file() else {}
    )
    if not isinstance(raw, dict):
        raw = {}
    raw.setdefault("inputs", {})
    raw["inputs"]["netlist_path"] = rel_netlist
    if rel_schematic is not None:
        raw["inputs"]["schematic_path"] = rel_schematic
    cfg_path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")

    return SetSchematicResult(
        project_id=config.project_id,
        netlist_path=rel_netlist,
        schematic_path=rel_schematic,
        destination=dest,
        copied=not same_file,
    )


# ---- validate --------------------------------------------------------------


@dataclass
class ValidateProjectResult:
    project_id: str
    name: str
    version: str
    analysis_scope: str
    root: Path


def validate_project(project_root) -> ValidateProjectResult:
    """Validate a project's ``project.yaml``."""
    config, layout, errors = _load_or_raise(project_root)
    if errors:
        raise ServiceError(
            f"Invalid project configuration ({len(errors)} errors):",
            details=list(errors),
        )
    return ValidateProjectResult(
        project_id=config.project_id,
        name=config.name,
        version=config.version,
        analysis_scope=config.analysis_scope,
        root=layout.root,
    )


# ---- status ----------------------------------------------------------------


def _artifact_mtime(path: Path) -> float | None:
    """mtime of a file, or the newest ``*.json`` in a directory; else None."""
    if path.is_dir():
        mtimes = [p.stat().st_mtime for p in path.glob("*.json")]
        return max(mtimes) if mtimes else None
    if path.is_file():
        return path.stat().st_mtime
    return None


def _llm_cost_summary(layout) -> dict:
    """Aggregate the per-call privacy logs in ``results/llm/*.jsonl``."""
    calls = prompt_tok = completion_tok = 0
    cost = 0.0
    llm_dir = layout.results_dir / "llm"
    if llm_dir.is_dir():
        for log in llm_dir.glob("*.jsonl"):
            for line in log.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                calls += 1
                prompt_tok += int(entry.get("prompt_tokens", 0) or 0)
                completion_tok += int(entry.get("completion_tokens", 0) or 0)
                cost += float(entry.get("estimated_cost_usd", 0.0) or 0.0)
    return {
        "calls": calls,
        "prompt_tokens": prompt_tok,
        "completion_tokens": completion_tok,
        "estimated_cost_usd": round(cost, 6),
    }


def build_project_status(config, layout) -> dict:
    """Machine-readable per-stage project state (UI-backend-contract gap 4/5).

    For each pipeline stage: is its artifact present, when was it
    generated, and is it *stale* — older than an upstream artifact it
    depends on. Plus an aggregate LLM-cost block.
    """
    root = layout.root
    netlist_rel = config.inputs.get("netlist_path", "") if config else ""
    netlist = (root / netlist_rel) if netlist_rel else None

    ctx = root / "input" / "user_context.json"
    # The UI's parasitic-selection stage is the per-net estimate
    # (parasitics_per_net.json), derived from the netlist topology — NOT the
    # legacy flat parasitics.json, which is written only by the deprecated
    # `parasitics estimate` path and is never refreshed by the UI flow.
    para = layout.generated_dir / "parasitics_per_net.json"
    testbench = layout.generated_dir / "testbench.cir"
    variants = layout.generated_dir / "variants" / "variants.json"
    # A simulation run writes ``results/run-<id>.json`` (both the single
    # `simulate run` and the pipeline). The stage is present when at least one
    # exists; we point it at the newest. (Older builds wrote a fixed
    # ``simulation_run.json`` — kept as the no-run fallback path.)
    _runs = sorted(layout.results_dir.glob("run-*.json"))
    simulation = _runs[-1] if _runs else (layout.results_dir / "simulation_run.json")
    findings = layout.results_dir / "findings"
    report = layout.reports_dir / "report.md"

    # (stage, artifact path, [upstream artifact paths])
    stage_defs = [
        ("context", ctx, []),
        # The per-net estimate derives from the netlist topology (plus only the
        # LISN-mode field of user_context), so it is NOT staled by unrelated
        # user_context edits — sim settings, parasitic overrides, signals.
        # Overriding a parasitic stales the *downstream* testbench, not this
        # stage (see QA flow J4).
        ("parasitics", para, [netlist] if netlist else []),
        ("testbench", testbench, [ctx] + ([netlist] if netlist else [])),
        ("variants", variants, [testbench]),
        ("simulation", simulation, [testbench]),
        ("findings", findings, [simulation]),
        ("report", report, [simulation, findings]),
    ]

    def _iso(ts: float) -> str:
        return _dt.datetime.fromtimestamp(ts, _dt.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

    # Map each stage's artifact path so staleness can propagate transitively:
    # a stage is stale not only when a direct input file is newer than its own
    # output, but also when a stage it was built from is itself stale. Without
    # this, editing user_context flagged only `testbench` stale while the
    # simulation / findings / report built from it kept showing "done" — the
    # rail never reflected that the whole downstream workflow was out of date.
    stage_of_artifact = {artifact: name for name, artifact, _ in stage_defs}

    stages: list[dict] = []
    computed: dict[str, dict] = {}
    for name, artifact, upstream in stage_defs:
        self_mt = _artifact_mtime(artifact)
        present = self_mt is not None
        stale = False
        if present:
            up = [m for m in (_artifact_mtime(u) for u in upstream) if m is not None]
            direct_stale = any(m > self_mt for m in up)
            # Inherit staleness from any upstream *stage* that is itself stale.
            # stage_defs is in topological order, so upstream stages are already
            # in `computed`. Pure input files (e.g. the netlist) are not in
            # stage_of_artifact and contribute only via the direct mtime check.
            inherited_stale = any(
                computed[stage_of_artifact[u]]["stale"]
                for u in upstream
                if u in stage_of_artifact
            )
            stale = bool(direct_stale or inherited_stale)
        entry = {
            "stage": name,
            "artifact": str(artifact.relative_to(root)).replace("\\", "/"),
            "present": present,
            "generated_at": _iso(self_mt) if self_mt else None,
            "stale": stale,
        }
        computed[name] = entry
        stages.append(entry)

    return {
        "project_id": config.project_id,
        "stages": stages,
        "llm": _llm_cost_summary(layout),
    }


def get_project_status(project_root) -> dict:
    """Load a project and return its :func:`build_project_status` dict."""
    config, layout = require_project(project_root)
    return build_project_status(config, layout)
