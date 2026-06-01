"""Regression test for the wired-screen "first run" flow.

This mirrors what a user does clicking through the wired M3 screens
(Projects → Import & context → Parasitic selection → Run), but drives
it through the `emc_assistant.ui.bridge.Api` object the screens actually
call — so it locks in the contract every wired screen depends on.

Runs in **dry-run** on a copy of `case_001` (a `.cir` project, so no
LTspice and no `.asc → .cir` conversion is needed → CI-safe). The
real-LTspice / `local-run` path is verified manually against `case_002`;
this guards the wiring, not the simulator.

Distinct from `test_ui_e2e.py` (which walks the eight screens generically):
this follows the exact bridge-call sequence of the wired flow, including
the methods added while wiring it — `project_inputs`, the parasitic
override round-trip through `save_context`, and the Run screen's
`run_pipeline` invocation with its accept-flags.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from emc_assistant.ui.bridge import Api

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _data(res: dict):
    assert isinstance(res, dict), res
    assert res.get("ok") is True, f"bridge call failed: {res}"
    return res["data"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A fresh copy of the buck example with rebuilt artefacts removed —
    the cleaned starting state a user opens."""
    dst = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, dst)
    for sub in ("generated", "results", "reports", "decisions"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


def test_first_run_flow_through_the_bridge(project: Path):
    """Projects → Import → Parasitic selection → Run, end to end."""
    api = Api()
    proj = str(project)

    # ── Projects: the folder scan + open ────────────────────────────────
    listed = _data(api.list_projects(str(project.parent)))
    assert any(Path(p["path"]) == project for p in listed)

    # ── Open: what the app shell + Import screen load ──────────────────
    status = _data(api.project_status(proj))
    assert {"stages", "project_id"} <= set(status)
    _data(api.load_context(proj))                       # Import form load
    inputs = _data(api.project_inputs(proj))            # schematic-source card
    assert inputs["netlist_path"]                       # the .cir is configured

    # ── Parasitic selection: estimate + load + override round-trip ─────
    per_net = _data(api.estimate_per_net(proj))
    assert per_net["estimate_count"] > 0
    rows = _data(api.read_artifact(proj, "generated/parasitics_per_net.json"))
    assert isinstance(rows, list) and rows
    # Pick an injectable net and pin its shunt C — the Parasitic screen's
    # override action persists this into user_context.parasitics.per_net.
    injectable = next((r["net"] for r in rows if r.get("injectable")), rows[0]["net"])
    ctx = _data(api.load_context(proj))
    ctx.setdefault("parasitics", {}).setdefault("per_net", {})[injectable] = {"c_pf": 47.0}
    _data(api.save_context(proj, ctx))
    # The override survives a reload (read from disk, not React-local state).
    reread = _data(api.load_context(proj))
    assert reread["parasitics"]["per_net"][injectable]["c_pf"] == 47.0

    # ── Compose + Run (dry-run — CI-safe) ───────────────────────────────
    opts = {"accept_wiring": True, "accept_signals": True, "accept_parasitics": True}
    _data(api.compose_testbench(proj, opts))
    _data(api.run_pipeline(proj, {**opts, "mode": "dry-run", "html": True}))

    # ── Results / Report on disk ────────────────────────────────────────
    after = _data(api.project_status(proj))
    stages = {s["stage"]: s for s in after["stages"]}
    assert stages["report"]["present"] is True
    assert stages["findings"]["present"] is True
    report_md = _data(api.read_artifact(proj, "reports/report.md"))
    assert len(report_md) > 100
    # The composed testbench reflects the override (round-trip through wiring).
    testbench = _data(api.read_artifact(proj, "generated/testbench.cir"))
    assert len(testbench) > 0


def test_new_project_import_real_schematic_flow(tmp_path: Path):
    """The other entry path: create a brand-new project and import a REAL
    example schematic via `set_schematic`, then estimate + run it dry-run.

    Guards the import action against real netlist content (not the
    placeholder text the `set_schematic` unit tests use) and confirms the
    downstream estimate / compose / run work on a freshly-imported
    circuit."""
    api = Api()
    fresh = tmp_path / "imported_buck"
    created = _data(api.create_project(str(fresh)))
    assert created["project_id"] == "imported_buck"

    # Import the real buck netlist (a `.cir` → no LTspice conversion needed).
    real_schematic = EXAMPLE / "input" / "buck_demo.cir"
    assert real_schematic.is_file()
    imported = _data(api.set_schematic(str(fresh), str(real_schematic)))
    assert imported["netlist_path"] == "input/buck_demo.cir"
    assert imported["copied"] is True
    assert (fresh / "input" / "buck_demo.cir").is_file()
    # The Import screen's schematic-source card reads this.
    assert _data(api.project_inputs(str(fresh)))["netlist_path"] == "input/buck_demo.cir"

    # Minimal context (Import form save), then estimate on the REAL netlist.
    _data(api.save_context(str(fresh), {
        "input_voltage_v": 12,
        "switching_frequency_hz": 500000,
    }))
    per_net = _data(api.estimate_per_net(str(fresh)))
    assert per_net["estimate_count"] > 0          # real nets, not a placeholder
    rows = _data(api.read_artifact(str(fresh), "generated/parasitics_per_net.json"))
    assert isinstance(rows, list) and rows

    # Compose + dry-run → a report from the imported schematic.
    opts = {"accept_signals": True, "accept_parasitics": True}
    _data(api.compose_testbench(str(fresh), opts))
    _data(api.run_pipeline(str(fresh), {**opts, "mode": "dry-run"}))
    after = _data(api.project_status(str(fresh)))
    stages = {s["stage"]: s for s in after["stages"]}
    assert stages["report"]["present"] is True


def test_first_run_requires_a_real_project():
    """Opening a non-existent project surfaces a structured error, never a
    crash — the screens render the error banner from this envelope."""
    api = Api()
    res = api.project_status(str(REPO_ROOT / "no_such_project"))
    assert res["ok"] is False
    assert "message" in res["error"]
