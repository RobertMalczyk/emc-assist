"""End-to-end test of the UI ↔ backend contract.

The M3 desktop UI is a thin pywebview shell over the service layer: every
screen action is an :class:`emc_assistant.ui.bridge.Api` call (see
``docs/design/ui_backend_contract.md`` §4). This test drives the whole
screen-by-screen workflow through that bridge — the exact ``Api`` methods
the UI's JavaScript will call — in **dry-run** mode (no LTspice, no LLM).

When the M3 UI lands this is the reference for *what the backend the UI
sits on must make work*. It deliberately does **not** test the rendered
HTML / JS — that needs the live pywebview window — only the ``Api``
contract behind every screen.

Simulation-result numbers and the quasi-peak detectors have their own
focused suites (``test_pipeline*``, ``test_detectors``,
``test_quasi_peak_detector``); here we verify the *workflow* completes
and every screen's data is reachable through the bridge.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from emc_assistant.ui.bridge import Api

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _data(res: dict):
    """Assert an ``Api`` call succeeded and return its ``data`` payload."""
    assert isinstance(res, dict), res
    assert res.get("ok") is True, f"Api call failed: {res}"
    return res["data"]


@pytest.fixture
def project(tmp_path: Path) -> Path:
    """A fresh copy of the buck example — a project with a real netlist,
    rebuilt artifacts removed."""
    dst = tmp_path / "e2e_case"
    shutil.copytree(EXAMPLE, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


def test_ui_backend_contract_e2e(project: Path, tmp_path: Path):
    """Walk the eight UI screens through the Api bridge, in dry-run."""
    api = Api()
    proj = str(project)

    # --- startup: the page's connectivity check ----------------------------
    pong = _data(api.ping())
    assert pong["pong"] is True

    # --- Screen 1 — Projects -----------------------------------------------
    listed = _data(api.list_projects(str(tmp_path)))
    assert any(Path(p["path"]) == project for p in listed)
    created = _data(api.create_project(str(tmp_path / "blank_project")))
    assert created["project_id"] == "blank_project"

    # --- Screen 2 — Import & context ---------------------------------------
    context = _data(api.load_context(proj))  # {} if the example ships none
    assert api.save_context(proj, dict(context))["ok"] is True

    # --- Screen 3 — Parasitic selection ------------------------------------
    per_net = _data(api.estimate_per_net(proj))
    assert per_net["estimate_count"] > 0
    topology = _data(api.read_artifact(proj, "generated/topology.json"))
    assert topology["nets"]
    _data(api.read_artifact(proj, "generated/parasitics_per_net.json"))

    # --- Screen 4 — Testbench review ---------------------------------------
    options = {
        "accept_wiring": True,
        "accept_signals": True,
        "accept_parasitics": True,
    }
    _data(api.compose_testbench(proj, options))
    testbench_cir = _data(api.read_artifact(proj, "generated/testbench.cir"))
    assert len(testbench_cir) > 0
    # Testbench-review audit artifacts must be reachable (the screen's
    # Parasitics audit reads these — every non-ground net gets a shunt C).
    shunt = _data(api.read_artifact(proj, "generated/parasitics_shunt.json"))
    assert isinstance(shunt, list) and len(shunt) > 0

    # --- Screen 5 — Run (one-shot pipeline, dry-run) -----------------------
    _data(api.run_pipeline(proj, {**options, "mode": "dry-run"}))

    # --- Screen 6 — Results -------------------------------------------------
    status = _data(api.project_status(proj))
    stages = {s["stage"]: s for s in status["stages"]}
    assert stages["report"]["present"] is True
    assert stages["findings"]["present"] is True
    _data(api.read_artifact(proj, "results/diagnostic.json"))
    # The Results screen reads load_results — diagnostic present in dry-run;
    # metrics only after a local-run, so has_metrics may be False here.
    results_view = _data(api.load_results(proj))
    assert results_view["diagnostic"] is not None
    assert "ranking" in results_view and "baseline" in results_view

    # --- Screen 7 — Findings & recommendations -----------------------------
    recs = _data(api.list_recommendations(proj))
    assert recs["project_id"]
    if recs["rows"]:
        first = recs["rows"][0]
        key = f"{first['area']}/{first['rec_id']}"
        decided = _data(api.accept_recommendation(proj, key))
        assert decided["status"] == "accepted"
        # The decision survives a re-read.
        again = _data(api.list_recommendations(proj))
        assert any(
            r["area"] == first["area"] and r["rec_id"] == first["rec_id"]
            and r["status"] == "accepted"
            for r in again["rows"]
        )

    # --- Screen 8 — Report & export ----------------------------------------
    report_md = _data(api.read_artifact(proj, "reports/report.md"))
    assert len(report_md) > 100  # the report has real content


def test_api_bridge_reports_errors_as_structured_envelopes(tmp_path: Path):
    """Every Api call must fail as {ok: false, error: …} — never throw a
    raw exception at the UI."""
    api = Api()
    missing = api.validate_project(str(tmp_path / "no_such_project"))
    assert missing["ok"] is False
    assert "message" in missing["error"]

    bad_artifact = api.read_artifact(str(tmp_path), "../escape.txt")
    assert bad_artifact["ok"] is False  # path-traversal is refused
