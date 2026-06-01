"""Convert an LTspice `.asc` schematic to a `.cir` netlist via the LTspice CLI.

LTspice itself netlists `.asc` files in batch mode:

    LTspice.exe -netlist <file>.asc   →  produces <file>.net

We rename the output to `<file>.cir` so the rest of the pipeline
(which only knows about `.cir` inputs) can pick it up unchanged. The
result is cached — re-running the converter when the cached `.cir` is
newer than the source `.asc` short-circuits.

The pipeline's fragment preprocessor (`netlist/fragment.py`) then
strips `.tran` / `.end` etc. from the converted netlist before the
composer wraps it.

This is deliberately a thin wrapper:
- We do NOT parse `.asc` graphically.
- We rely on LTspice to do the netlisting.
- If LTspice is missing, we raise a friendly error instead of crashing.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Callable


class AscConversionError(RuntimeError):
    """Raised when `.asc` → `.cir` conversion fails or LTspice is unavailable."""


@dataclass
class AscConversionResult:
    asc_path: Path
    cir_path: Path
    used_cache: bool
    """True when the cached `.cir` was younger than the source `.asc` and
    we skipped the LTspice call."""


def _cache_is_fresh(asc_path: Path, cir_path: Path) -> bool:
    if not cir_path.is_file():
        return False
    try:
        return cir_path.stat().st_mtime >= asc_path.stat().st_mtime
    except OSError:
        return False


def convert_asc_to_cir(
    asc_path: Path,
    *,
    ltspice_exe: Path | str | None,
    force: bool = False,
    timeout_seconds: int = 60,
    subprocess_run: Callable | None = None,
) -> AscConversionResult:
    """Convert ``asc_path`` to a ``.cir`` sibling using LTspice's `-netlist` mode.

    Returns an :class:`AscConversionResult` with the cached or freshly
    written `.cir` path. The cached path lives next to the `.asc` with
    the same stem (``<file>.cir``).

    :raises AscConversionError: if ``ltspice_exe`` is missing, the
        subprocess call fails, or LTspice does not produce the expected
        output.
    """
    asc_path = Path(asc_path)
    if not asc_path.is_file():
        raise FileNotFoundError(f"`.asc` not found: {asc_path}")
    if asc_path.suffix.lower() != ".asc":
        raise ValueError(f"Expected .asc input, got {asc_path.suffix!r}: {asc_path}")

    cir_path = asc_path.with_suffix(".cir")
    if not force and _cache_is_fresh(asc_path, cir_path):
        return AscConversionResult(asc_path=asc_path, cir_path=cir_path, used_cache=True)

    if not ltspice_exe:
        raise AscConversionError(
            "LTspice executable not configured. Set `ltspice.executable_path` in "
            "`project.yaml`, set the LTSPICE_PATH environment variable, or "
            "convert `.asc` → `.cir` manually via LTspice GUI (View → SPICE Netlist)."
        )
    exe_path = Path(ltspice_exe)
    if not exe_path.is_file():
        raise AscConversionError(
            f"LTspice executable not found at {exe_path}. "
            f"Update `ltspice.executable_path` or LTSPICE_PATH."
        )

    runner = subprocess_run or subprocess.run
    try:
        proc = runner(
            [str(exe_path), "-netlist", str(asc_path)],
            cwd=str(asc_path.parent),
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except FileNotFoundError as exc:  # pragma: no cover - already validated above
        raise AscConversionError(f"Could not invoke LTspice: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise AscConversionError(
            f"LTspice `-netlist` timed out after {timeout_seconds}s on {asc_path.name}."
        ) from exc

    if proc.returncode != 0:
        stderr = (proc.stderr or "").strip()[:500]
        raise AscConversionError(
            f"LTspice `-netlist` exited with code {proc.returncode} on {asc_path.name}. "
            f"stderr: {stderr or '(empty)'}"
        )

    # LTspice writes <file>.net next to the source.
    net_path = asc_path.with_suffix(".net")
    if not net_path.is_file():
        # Some LTspice versions write directly to .cir; handle that too.
        if cir_path.is_file():
            return AscConversionResult(asc_path=asc_path, cir_path=cir_path, used_cache=False)
        raise AscConversionError(
            f"LTspice did not produce a netlist file for {asc_path.name}. "
            f"Expected {net_path.name} or {cir_path.name}."
        )

    # Atomic rename: .net → .cir.
    try:
        net_path.replace(cir_path)
    except OSError as exc:
        raise AscConversionError(
            f"Failed to rename {net_path.name} → {cir_path.name}: {exc}"
        ) from exc

    return AscConversionResult(asc_path=asc_path, cir_path=cir_path, used_cache=False)
