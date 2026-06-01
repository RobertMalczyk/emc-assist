"""LTspice simulation runs — service layer (single testbench + variants)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from emc_assistant.logging_setup import get_logger
from emc_assistant.ltspice import LtspiceAdapter, discover_ltspice, run_simulation
from emc_assistant.results import parse_log
from emc_assistant.service.options import CommandOptions
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError

_log = get_logger("simulation")


@dataclass
class SimRunResult:
    ok: bool
    run: Any


def run_testbench(project_root, options: CommandOptions) -> SimRunResult:
    """Run LTspice on ``generated/testbench.cir`` (or dry-run)."""
    config, layout = require_project(project_root)
    netlist_path = layout.generated_dir / "testbench.cir"
    if not netlist_path.is_file():
        raise ServiceError(
            f"Missing {netlist_path} — run `testbench compose` first."
        )

    configured = str(config.ltspice.get("executable_path") or "")
    executable = discover_ltspice(configured or None)
    timeout = int(config.ltspice.get("timeout_seconds", 120))
    adapter = LtspiceAdapter(executable=executable, timeout_seconds=timeout)

    mode = options.mode or str(config.ltspice.get("mode", "dry-run"))
    if mode not in ("dry-run", "local-run"):
        raise ServiceError(f"Invalid mode: {mode} (allowed: dry-run, local-run)")

    result = run_simulation(
        adapter=adapter,
        netlist=netlist_path,
        project_id=config.project_id,
        mode=mode,  # type: ignore[arg-type]
        output_dir=layout.results_dir,
    )
    _log.info(f"Run {result.run_id}: status={result.status}")
    _log.info(f"  command: {' '.join(result.command)}")
    if result.warnings:
        _log.info("  warnings:")
        for w in result.warnings:
            _log.info(f"    - {w}")
    if result.errors:
        _log.info("  errors:")
        for e in result.errors:
            _log.info(f"    - {e}")

    log_path = Path(result.artifacts.get("log", ""))
    if log_path.is_file():
        summary = parse_log(log_path)
        _log.info(f"  log: {log_path} (status={summary.status})")
        if summary.measurements:
            _log.info(f"  .meas: {len(summary.measurements)} values")
    return SimRunResult(ok=result.status in {"completed", "dry_run"}, run=result)


@dataclass
class VariantsRunResult:
    ok: bool
    fail_count: int
    total: int


def run_variants(project_root, options: CommandOptions) -> VariantsRunResult:
    """Run LTspice for every variant in ``generated/variants/variants.json``."""
    config, layout = require_project(project_root)
    manifest_path = layout.generated_dir / "variants" / "variants.json"
    if not manifest_path.is_file():
        raise ServiceError(
            f"Missing {manifest_path} — run `variants compose` first."
        )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    configured = str(config.ltspice.get("executable_path") or "")
    executable = discover_ltspice(configured or None)
    timeout = int(config.ltspice.get("timeout_seconds", 120))
    adapter = LtspiceAdapter(executable=executable, timeout_seconds=timeout)

    mode = options.mode or str(config.ltspice.get("mode", "dry-run"))
    if mode not in ("dry-run", "local-run"):
        raise ServiceError(f"Invalid mode: {mode}")

    out_dir = layout.results_dir / "variants"
    out_dir.mkdir(parents=True, exist_ok=True)
    fail_count = 0
    for entry in manifest:
        cir_path = Path(entry["cir"])
        if not cir_path.is_file():
            _log.info(f"Skipping {entry['label']}: missing {cir_path}")
            fail_count += 1
            continue
        result = run_simulation(
            adapter=adapter,
            netlist=cir_path,
            project_id=config.project_id,
            mode=mode,  # type: ignore[arg-type]
            output_dir=None,
        )
        payload = result.to_schema_dict()
        payload["variant_label"] = entry["label"]
        payload["overrides"] = entry["overrides"]
        (out_dir / f"{entry['label']}.json").write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        status_icon = "OK" if result.status in {"completed", "dry_run"} else "FAIL"
        _log.info(f"  [{status_icon}] {entry['label']}: {result.status}")
        if result.status not in {"completed", "dry_run"}:
            fail_count += 1
    _log.info(f"Wrote {len(manifest)} variant results to {out_dir}")
    return VariantsRunResult(
        ok=fail_count == 0, fail_count=fail_count, total=len(manifest)
    )
