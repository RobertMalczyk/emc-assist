"""Tests for the `user_context.simulation.tran_directive` override.

Topologies like hot-swap controllers (case_002) need a much longer
transient window than the DC/DC default. Setting
`simulation.tran_directive` in `user_context.json` overrides
`TestbenchPlan.tran_directive` for both `cmd_testbench_compose` and
`cmd_variants_compose` paths.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from emc_assistant.cli import main


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


# Unit-level coverage of the structured settings lives in test_sim_settings.py;
# the tests here exercise the raw `tran_directive` override end-to-end through
# the compose / variants CLI paths (M2.13 keeps the raw override working).


def _copy_example_with_override(tmp_path: Path, override: str | None) -> Path:
    """Copy the buck example into a tmp dir, optionally patching user_context.json."""
    dst = tmp_path / "case"
    shutil.copytree(EXAMPLE, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    if override is not None:
        ctx_path = dst / "input" / "user_context.json"
        ctx = json.loads(ctx_path.read_text(encoding="utf-8"))
        ctx.setdefault("simulation", {})["tran_directive"] = override
        ctx_path.write_text(json.dumps(ctx, indent=2), encoding="utf-8")
    return dst


def test_testbench_compose_uses_default_tran(tmp_path: Path):
    project = _copy_example_with_override(tmp_path, override=None)
    rc = main(["testbench", "compose", str(project), "--accept-wiring"])
    assert rc == 0
    cir = (project / "generated" / "testbench.cir").read_text(encoding="utf-8")
    # Default DC/DC tran from composer.py
    assert ".tran 0 5m 0 100n" in cir


def test_testbench_compose_honours_user_context_override(tmp_path: Path):
    project = _copy_example_with_override(tmp_path, override=".tran 0 250m 0 100u")
    rc = main(["testbench", "compose", str(project), "--accept-wiring"])
    assert rc == 0
    cir = (project / "generated" / "testbench.cir").read_text(encoding="utf-8")
    assert ".tran 0 250m 0 100u" in cir
    # The DC/DC default must NOT also be present.
    assert ".tran 0 5m 0 100n" not in cir


def test_variants_compose_honours_user_context_override(tmp_path: Path):
    project = _copy_example_with_override(tmp_path, override=".tran 0 100m 0 1u")
    rc = main(["variants", "compose", str(project), "--accept-wiring"])
    assert rc == 0
    baseline = (project / "generated" / "variants" / "baseline.cir").read_text(encoding="utf-8")
    assert ".tran 0 100m 0 1u" in baseline
    assert ".tran 0 5m 0 100n" not in baseline
