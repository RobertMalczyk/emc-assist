"""Local LTspice runner — ``dry-run`` and ``local-run``.

``dry-run`` records only the planned command and does not spawn a process.
``local-run`` invokes ``LTspice -b -Run <netlist>`` with a timeout.
Either way we produce a ``simulation_run.json`` artefact that conforms
to ``schemas/simulation_run.schema.json``.

LTspice is never executed remotely and never bundled with the tool.
"""

from __future__ import annotations

import json
import subprocess
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import re

from emc_assistant.ltspice.adapter import LtspiceAdapter
from emc_assistant.results.log_parser import parse_log
from emc_assistant.results.metrics import summarize_default_metrics
from emc_assistant.results.raw_parser import UnsupportedRawFormat, parse_raw


_FAILURE_PATTERNS: tuple[tuple[str, re.Pattern[str], str], ...] = (
    (
        "convergence",
        re.compile(r"(singular matrix|fail(?:ed)? to converge|time step too small)", re.IGNORECASE),
        "Convergence failure — try tighter .options reltol or smaller initial timestep.",
    ),
    (
        "license",
        re.compile(r"(license|activation|trial expired)", re.IGNORECASE),
        "LTspice license / activation issue.",
    ),
    (
        "missing_model",
        re.compile(
            r"(unknown subcircuit|missing model|could not find model|cannot find include|file not found)",
            re.IGNORECASE,
        ),
        "Missing model or include — check `.model`/`.include` paths.",
    ),
    (
        "syntax",
        re.compile(r"(syntax error|unexpected token|illegal character)", re.IGNORECASE),
        "Netlist syntax error reported by LTspice.",
    ),
)


def _classify_failures(text: str) -> list[tuple[str, str, str]]:
    """Match known failure patterns; return ``(tag, snippet, hint)`` tuples."""
    out: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    for line in text.splitlines():
        for tag, pattern, hint in _FAILURE_PATTERNS:
            if tag in seen:
                continue
            if pattern.search(line):
                snippet = line.strip()[:200]
                out.append((tag, snippet, hint))
                seen.add(tag)
                break
    return out


RunMode = Literal["dry-run", "local-run"]
RunStatus = Literal["planned", "dry_run", "running", "completed", "failed", "timeout"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class SimulationResult:
    run_id: str
    project_id: str
    status: RunStatus
    started_at: str
    command: list[str]
    artifacts: dict[str, str] = field(default_factory=dict)
    completed_at: str | None = None
    return_code: int | None = None
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    metrics: dict[str, float] = field(default_factory=dict)

    def to_schema_dict(self) -> dict:
        out: dict = {
            "run_id": self.run_id,
            "project_id": self.project_id,
            "status": self.status,
            "started_at": self.started_at,
            "command": list(self.command),
            "artifacts": dict(self.artifacts),
            "warnings": list(self.warnings),
            "errors": list(self.errors),
            "metrics": dict(self.metrics),
        }
        if self.completed_at:
            out["completed_at"] = self.completed_at
        if self.return_code is not None:
            out["return_code"] = int(self.return_code)
        return out


def _expected_log_path(netlist: Path) -> Path:
    return netlist.with_suffix(".log")


def _expected_raw_path(netlist: Path) -> Path:
    return netlist.with_suffix(".raw")


def run_simulation(
    *,
    adapter: LtspiceAdapter,
    netlist: Path,
    project_id: str,
    mode: RunMode = "dry-run",
    output_dir: Path | None = None,
    timeout_seconds: int | None = None,
) -> SimulationResult:
    """Run (or plan) an LTspice simulation."""
    netlist = Path(netlist).resolve()
    if not netlist.is_file():
        raise FileNotFoundError(f"Netlist not found: {netlist}")

    run_id = f"run-{uuid.uuid4().hex[:8]}"
    started = _now_iso()
    command = adapter.build_command(netlist)
    log_path = _expected_log_path(netlist)
    raw_path = _expected_raw_path(netlist)
    artifacts = {
        "netlist": str(netlist),
        "log": str(log_path),
        "raw": str(raw_path),
    }

    result = SimulationResult(
        run_id=run_id,
        project_id=project_id,
        status="planned",
        started_at=started,
        command=command,
        artifacts=artifacts,
    )

    if mode == "dry-run":
        result.status = "dry_run"
        result.completed_at = _now_iso()
        if not adapter.available:
            result.warnings.append(
                "LTspice not detected locally — only the dry-run was performed."
            )
    elif mode == "local-run":
        if not adapter.available:
            result.status = "failed"
            result.errors.append("LTspice is not available locally — local-run impossible.")
            result.completed_at = _now_iso()
        else:
            timeout = timeout_seconds if timeout_seconds is not None else adapter.timeout_seconds
            result.status = "running"
            try:
                proc = subprocess.run(
                    command,
                    cwd=str(netlist.parent),
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                )
                result.return_code = proc.returncode
                if proc.returncode == 0:
                    result.status = "completed"
                else:
                    result.status = "failed"
                    if proc.stderr:
                        result.errors.append(proc.stderr.strip()[:2000])
            except subprocess.TimeoutExpired:
                result.status = "timeout"
                result.errors.append(f"LTspice exceeded timeout of {timeout}s")
            except FileNotFoundError as exc:
                result.status = "failed"
                result.errors.append(f"Could not start LTspice: {exc}")
            except OSError as exc:  # pragma: no cover — uncommon
                result.status = "failed"
                result.errors.append(f"OS error while starting LTspice: {exc}")
            result.completed_at = _now_iso()
    else:  # pragma: no cover — typed Literal
        raise ValueError(f"Unknown run mode: {mode}")

    # Fail-safe: if LTspice produced `.raw`, try to compute metrics.
    raw_path_resolved = Path(result.artifacts.get("raw", ""))
    if result.status == "completed" and raw_path_resolved.is_file():
        try:
            raw = parse_raw(raw_path_resolved)
            result.metrics.update(summarize_default_metrics(raw))
        except UnsupportedRawFormat as exc:
            result.warnings.append(f".raw parser did not handle the file: {exc}")
        except Exception as exc:  # pragma: no cover — defensive
            result.warnings.append(f"Unexpected error parsing .raw: {exc}")

    # If LTspice produced a `.log`, pull `.meas` results into metrics{}
    # (cheaper than .raw and works even when LTspice is told not to save raw).
    log_path_resolved = Path(result.artifacts.get("log", ""))
    if result.status == "completed" and log_path_resolved.is_file():
        try:
            log_summary = parse_log(log_path_resolved)
            for key, value in log_summary.measurements.items():
                result.metrics.setdefault(key, value)
            for w in log_summary.warnings:
                result.warnings.append(f".log: {w[:200]}")
        except Exception as exc:  # pragma: no cover — defensive
            result.warnings.append(f"Unexpected error parsing .log: {exc}")

    # Classify common LTspice failure modes (stderr + .log) into tagged hints.
    if result.status in {"failed", "timeout"}:
        haystack = "\n".join(result.errors)
        if log_path_resolved.is_file():
            try:
                haystack += "\n" + log_path_resolved.read_text(encoding="utf-8", errors="replace")
            except OSError:  # pragma: no cover - rare
                pass
        for tag, snippet, hint in _classify_failures(haystack):
            result.errors.append(f"[{tag}] {hint} (matched: {snippet})")

    if output_dir is not None:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        out_path = output_dir / f"{run_id}.json"
        out_path.write_text(
            json.dumps(result.to_schema_dict(), indent=2), encoding="utf-8"
        )

    return result
