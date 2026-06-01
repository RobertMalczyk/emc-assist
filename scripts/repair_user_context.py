"""Detect & repair user_context.json files corrupted by the pre-fix
import-screen save bug.

Two bugs (fixed in commit 2bf286f) degraded ``input/user_context.json``
on every save through the Import & context screen:

1. A blank numeric field was written as 0 (JS ``Number("") === 0``), so an
   unknown switching frequency became a misleading
   ``"switching_frequency_hz": 0`` ("DC") instead of ``null`` ("unknown").
2. The signals list was rebuilt from names alone, dropping each signal's
   ``from_label`` / ``rationale`` / ``unit`` and resetting ``confidence``
   from 1.0 to 0.8.

What is recoverable, and what is not:

- **Signals** — recoverable. The metadata is re-derived from the
  schematic's ``FLAG`` labels (the authoritative source). A degraded
  signal whose name matches a FLAG label is restored; one that matches no
  label is treated as a genuine user-added name and left untouched.
- **Numeric zeros** — the original blank value is gone, so a ``0`` is
  ambiguous (the user may have typed 0). These are reported for manual
  review. Only ``switching_frequency_hz: 0`` is auto-repaired (-> null),
  because 0 Hz is never a meaningful switching frequency.

Every ``--fix`` write is preceded by a ``<file>.bak`` backup, so repairs
are reversible. Without ``--fix`` the tool only reports (read-only).

Usage:
    # Report only (no writes) — a project dir, a json file, or many:
    python scripts/repair_user_context.py examples/case_002_DCDC
    python scripts/repair_user_context.py path/to/input/user_context.json

    # Walk a tree for every <...>/input/user_context.json:
    python scripts/repair_user_context.py --scan C:/path/to/projects

    # Apply the safe repairs (writes a .bak first):
    python scripts/repair_user_context.py --fix examples/case_002_DCDC

Exit code is non-zero when corruption is found (report mode) or when a
repair could not complete, so the tool is scriptable.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from emc_assistant.netlist.signals import detect_signals  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]


# Numeric fields the Import screen writes (dotted paths). A 0 in any of
# these is suspect under the old blank->0 bug; only switching_frequency_hz
# is auto-repaired (see module docstring).
_NUMERIC_FIELDS: tuple[str, ...] = (
    "input_voltage_v",
    "output_voltage_v",
    "load_current_a",
    "switching_frequency_hz",
    "cable_length_m",
    "ambient_t_c",
    "pcb.layers",
    "pcb.copper_oz",
    "pcb.dielectric_height_to_plane_mm",
    "pcb.prepreg_mm",
    "pcb.trace_width_mm",
    "pcb.trace_length_mm",
)


def _get(ctx: dict, dotted: str):
    cur = ctx
    for key in dotted.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def _is_zero(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value == 0


def detect_zero_numerics(ctx: dict) -> list[tuple[str, object]]:
    """Numeric fields that are exactly 0 — suspect blank->0 corruption."""
    found: list[tuple[str, object]] = []
    for path in _NUMERIC_FIELDS:
        value = _get(ctx, path)
        if _is_zero(value):
            found.append((path, value))
    return found


def detect_degraded_signals(ctx: dict) -> list[tuple[int, dict]]:
    """Signals that look stripped: confidence ~0.8 and no from_label.

    These are *candidates*; only ones whose name matches a schematic FLAG
    label are actually repairable (the rest are genuine user additions).
    """
    out: list[tuple[int, dict]] = []
    signals = ctx.get("signals")
    if not isinstance(signals, list):
        return out
    for i, sig in enumerate(signals):
        if not isinstance(sig, dict):
            continue
        conf = sig.get("confidence")
        looks_default_conf = isinstance(conf, (int, float)) and abs(float(conf) - 0.8) < 1e-9
        if looks_default_conf and not sig.get("from_label"):
            out.append((i, sig))
    return out


def find_schematic(input_dir: Path) -> tuple[Path | None, Path | None]:
    """Locate the source schematic next to user_context.json.

    Prefers a ``.asc`` (carries FLAG labels) and falls back to a ``.cir``.
    """
    asc = next(iter(sorted(input_dir.glob("*.asc"))), None)
    cir = next(iter(sorted(input_dir.glob("*.cir"))), None)
    return asc, cir


def rederive_signals(asc_path: Path | None, cir_path: Path | None) -> dict[str, object]:
    """name -> Signal re-derived from the schematic (authoritative)."""
    sigs = detect_signals(asc_path=asc_path, cir_path=cir_path)
    return {s.name: s for s in sigs}


def repair_signals(ctx: dict, rederived: dict) -> list[str]:
    """Restore stripped metadata for signals matching a re-derived name."""
    changes: list[str] = []
    signals = ctx.get("signals")
    if not isinstance(signals, list):
        return changes
    for sig in signals:
        if not isinstance(sig, dict):
            continue
        name = sig.get("name")
        rd = rederived.get(name)
        if rd is None:
            continue  # genuine user-added name — nothing to restore
        conf = sig.get("confidence")
        degraded = (not sig.get("from_label")) or (
            isinstance(conf, (int, float)) and abs(float(conf) - 0.8) < 1e-9
        )
        if not degraded:
            continue
        before = dict(sig)
        sig["expr"] = rd.expr
        sig["kind"] = rd.kind or sig.get("kind", "voltage")
        if rd.unit:
            sig["unit"] = rd.unit
        if rd.rationale:
            sig["rationale"] = rd.rationale
        if rd.from_label:
            # A FLAG-derived name was user-confirmed: restore to that state.
            sig["from_label"] = rd.from_label
            sig["confidence"] = 1.0
            sig["source"] = "user"
        else:
            sig["confidence"] = float(rd.confidence)
            sig.setdefault("source", rd.source)
        if sig != before:
            changes.append(
                f"signal '{name}': restored metadata "
                f"(from_label={rd.from_label or '-'}, expr={rd.expr})"
            )
    return changes


def repair_switching_freq(ctx: dict) -> list[str]:
    """``switching_frequency_hz: 0`` -> null (0 Hz is not a switching rate)."""
    if _is_zero(ctx.get("switching_frequency_hz")):
        ctx["switching_frequency_hz"] = None
        return ["switching_frequency_hz: 0 -> null (0 Hz is not a meaningful switching frequency)"]
    return []


def diagnose_and_repair(ctx: dict, input_dir: Path, *, fix: bool) -> tuple[dict, list[str], list[str]]:
    """Return (ctx, findings, changes). ``changes`` is empty unless ``fix``."""
    asc, cir = find_schematic(input_dir)
    rederived = rederive_signals(asc, cir)

    findings: list[str] = []
    zeros = detect_zero_numerics(ctx)
    for path, value in zeros:
        tag = " (auto-repairable -> null)" if path == "switching_frequency_hz" else " (review manually)"
        findings.append(f"numeric '{path}' = {value}{tag}")

    degraded = detect_degraded_signals(ctx)
    for _i, sig in degraded:
        name = sig.get("name")
        if name in rederived and rederived[name].from_label:
            findings.append(f"signal '{name}': stripped metadata, restorable from FLAG `{rederived[name].from_label}`")
        elif name in rederived:
            findings.append(f"signal '{name}': stripped metadata, restorable from .cir heuristic")
        else:
            findings.append(f"signal '{name}': low-confidence, no schematic match (likely a genuine user-added name — left as-is)")

    changes: list[str] = []
    if fix:
        changes += repair_switching_freq(ctx)
        changes += repair_signals(ctx, rederived)
    return ctx, findings, changes


def _resolve_context_path(arg: Path) -> Path | None:
    """Map a CLI arg to a user_context.json: a file, a project dir, or an input dir."""
    if arg.is_file() and arg.suffix == ".json":
        return arg
    if arg.is_dir():
        for candidate in (arg / "input" / "user_context.json", arg / "user_context.json"):
            if candidate.is_file():
                return candidate
    return None


def collect_context_files(paths: list[str], scan_root: str | None) -> list[Path]:
    out: list[Path] = []
    seen: set[Path] = set()

    def _add(p: Path) -> None:
        rp = p.resolve()
        if rp not in seen:
            seen.add(rp)
            out.append(p)

    if scan_root:
        root = Path(scan_root)
        for p in sorted(root.rglob("user_context.json")):
            _add(p)
    for raw in paths:
        resolved = _resolve_context_path(Path(raw))
        if resolved is not None:
            _add(resolved)
        else:
            print(f"  ! skipped: no user_context.json at {raw}", file=sys.stderr)
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", help="project dir(s) or user_context.json file(s)")
    parser.add_argument("--scan", metavar="ROOT", help="recursively scan ROOT for user_context.json files")
    parser.add_argument("--fix", action="store_true", help="apply safe repairs (writes a .bak backup first)")
    args = parser.parse_args(argv)

    files = collect_context_files(args.paths, args.scan)
    if not files:
        print("No user_context.json files found.", file=sys.stderr)
        return 2

    total_findings = 0
    total_changes = 0
    for path in files:
        try:
            ctx = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            print(f"\n{path}\n  ! could not read JSON: {exc}", file=sys.stderr)
            total_findings += 1
            continue
        if not isinstance(ctx, dict):
            print(f"\n{path}\n  ! not a JSON object — skipped", file=sys.stderr)
            continue

        ctx, findings, changes = diagnose_and_repair(ctx, path.parent, fix=args.fix)
        print(f"\n{path}")
        if not findings:
            print("  ok — no corruption signatures")
        for f in findings:
            print(f"  - {f}")
        total_findings += len(findings)

        if args.fix and changes:
            backup = Path(str(path) + ".bak")
            backup.write_text(path.read_text(encoding="utf-8"), encoding="utf-8")
            path.write_text(json.dumps(ctx, indent=2, ensure_ascii=False), encoding="utf-8")
            print(f"  -> repaired ({len(changes)} change(s)); backup at {backup.name}")
            for c in changes:
                print(f"     * {c}")
            total_changes += len(changes)
        elif args.fix:
            print("  -> nothing auto-repairable")

    print(f"\nScanned {len(files)} file(s): {total_findings} finding(s)"
          + (f", {total_changes} repair(s) applied" if args.fix else ""))
    # Non-zero when there is something to act on, so CI/scripts can gate.
    if args.fix:
        return 0
    return 1 if total_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
