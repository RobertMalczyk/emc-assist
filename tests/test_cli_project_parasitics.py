"""CLI tests for the M3-prerequisite commands (UI-backend-contract gaps 1-3):
`project create` and `parasitics per-net`.
"""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import yaml

from emc_assistant.cli import build_project_status, main
from emc_assistant.project.model import load_project

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


# ---- project create --------------------------------------------------------


def test_project_create_writes_valid_skeleton(tmp_path: Path):
    project = tmp_path / "my_emc_project"
    rc = main(["project", "create", str(project)])
    assert rc == 0
    cfg = project / "project.yaml"
    assert cfg.is_file()
    assert (project / "input" / "models").is_dir()
    # The skeleton must itself pass project validation.
    config, _layout, errors = load_project(project)
    assert errors == []
    assert config.project_id == "my_emc_project"
    assert config.analysis_scope == "conducted_emi_dc_dc"
    data = yaml.safe_load(cfg.read_text(encoding="utf-8"))
    assert data["privacy"]["allow_cloud_llm"] is False
    assert data["ltspice"]["mode"] == "dry-run"


def test_project_create_then_validate(tmp_path: Path):
    project = tmp_path / "p2"
    assert main(["project", "create", str(project)]) == 0
    assert main(["project", "validate", str(project)]) == 0


def test_project_create_refuses_overwrite(tmp_path: Path, capsys):
    project = tmp_path / "p3"
    assert main(["project", "create", str(project)]) == 0
    capsys.readouterr()
    rc = main(["project", "create", str(project)])
    assert rc == 1
    assert "Refusing to overwrite" in capsys.readouterr().out


# ---- parasitics per-net ----------------------------------------------------


def _copy_example(tmp_path: Path) -> Path:
    project = tmp_path / "case"
    shutil.copytree(EXAMPLE, project)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(project / sub, ignore_errors=True)
    return project


def test_parasitics_per_net_writes_topology_and_estimates(tmp_path: Path):
    project = _copy_example(tmp_path)
    rc = main(["parasitics", "per-net", str(project)])
    assert rc == 0

    topo_path = project / "generated" / "topology.json"
    per_net_path = project / "generated" / "parasitics_per_net.json"
    assert topo_path.is_file() and per_net_path.is_file()

    topo = json.loads(topo_path.read_text(encoding="utf-8"))
    assert topo["nets"] and "power_supply_candidates" in topo

    per_net = json.loads(per_net_path.read_text(encoding="utf-8"))
    # One estimate per net; each carries role + R/L/C + injectability.
    assert len(per_net) == len(topo["nets"])
    for e in per_net:
        assert e["role"] in ("return", "switching_node", "power_rail", "signal")
        assert e["r_typ_ohm"] > 0 and e["l_typ_h"] > 0 and e["c_typ_f"] > 0
        assert isinstance(e["injectable"], bool)
    # The buck's ground net is present and never injectable. Under the
    # default dual-LISN wiring the user's local `0` is shown as `DUT_GND`
    # (the DUT-side virtual ground) — the same name the composed testbench
    # uses; `0` then lives only on the LISN side.
    gnd = next(e for e in per_net if e["role"] == "return")
    assert gnd["net"] == "DUT_GND" and gnd["injectable"] is False


def test_parasitics_per_net_no_compose_side_effects(tmp_path: Path):
    """per-net analyses topology only — it must not compose a testbench."""
    project = _copy_example(tmp_path)
    assert main(["parasitics", "per-net", str(project)]) == 0
    assert not (project / "generated" / "testbench.cir").exists()


def test_parasitics_per_net_rejects_missing_netlist(tmp_path: Path, capsys):
    project = tmp_path / "empty"
    main(["project", "create", str(project)])  # skeleton has empty netlist_path
    capsys.readouterr()
    rc = main(["parasitics", "per-net", str(project)])
    assert rc == 1
    assert "netlist" in capsys.readouterr().out.lower()


# ---- project status (contract gaps 4-5) ------------------------------------


def test_project_status_cli_emits_json(tmp_path: Path, capsys):
    project = tmp_path / "p"
    main(["project", "create", str(project)])
    capsys.readouterr()
    rc = main(["project", "status", str(project)])
    assert rc == 0
    status = json.loads(capsys.readouterr().out)
    assert status["project_id"] == "p"
    assert {s["stage"] for s in status["stages"]} >= {
        "context", "testbench", "simulation", "report",
    }
    assert "llm" in status


def test_project_status_fresh_project_has_no_artifacts(tmp_path: Path):
    project = tmp_path / "p"
    main(["project", "create", str(project)])
    config, layout, _ = load_project(project)
    status = build_project_status(config, layout)
    assert all(not s["present"] for s in status["stages"])
    assert status["llm"]["calls"] == 0


def test_project_status_detects_staleness(tmp_path: Path):
    project = tmp_path / "p"
    main(["project", "create", str(project)])
    config, layout, _ = load_project(project)
    ctx = project / "input" / "user_context.json"
    testbench = layout.generated_dir / "testbench.cir"
    testbench.parent.mkdir(parents=True, exist_ok=True)
    ctx.write_text("{}", encoding="utf-8")
    testbench.write_text("* tb\n", encoding="utf-8")
    # Make the upstream (user_context) newer than the testbench.
    os.utime(testbench, (1_000_000, 1_000_000))
    os.utime(ctx, (1_000_100, 1_000_100))
    stages = {s["stage"]: s for s in build_project_status(config, layout)["stages"]}
    assert stages["testbench"]["present"] is True
    assert stages["testbench"]["stale"] is True
    assert stages["context"]["stale"] is False  # a root input is never stale


def test_project_status_staleness_propagates_downstream(tmp_path: Path):
    """Regression: staleness must propagate through the workflow. Touching an
    upstream input (user_context) stales not only the immediate `testbench`
    stage but every stage built from it (variants / simulation / findings /
    report) — otherwise the rail keeps showing downstream work as 'done' after
    an upstream change, so the status never updates properly."""
    project = tmp_path / "p"
    main(["project", "create", str(project)])  # empty netlist → testbench deps on ctx only
    config, layout, _ = load_project(project)
    ctx = project / "input" / "user_context.json"

    # Fabricate a full, initially-fresh pipeline (each artifact newer than the
    # one before it, so nothing is stale to begin with).
    testbench = layout.generated_dir / "testbench.cir"
    variants = layout.generated_dir / "variants" / "variants.json"
    run = layout.results_dir / "run-0001.json"
    finding = layout.results_dir / "findings" / "dcdc.json"
    report = layout.reports_dir / "report.md"
    ordered = [ctx, testbench, variants, run, finding, report]
    for p in ordered:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("{}", encoding="utf-8")
    t = 1_000_000
    for p in ordered:
        os.utime(p, (t, t))
        t += 100

    downstream = ("testbench", "variants", "simulation", "findings", "report")
    fresh = {s["stage"]: s for s in build_project_status(config, layout)["stages"]}
    for s in downstream:
        assert fresh[s]["present"] is True
        assert fresh[s]["stale"] is False, f"{s} should start fresh"

    # Make user_context the newest input: `testbench` goes stale directly, and
    # every downstream stage inherits the staleness.
    os.utime(ctx, (t + 1000, t + 1000))
    after = {s["stage"]: s for s in build_project_status(config, layout)["stages"]}
    for s in downstream:
        assert after[s]["stale"] is True, f"{s} should inherit staleness"
    assert after["context"]["stale"] is False  # a root input is never stale


def test_project_status_parasitics_stage_tracks_per_net_not_user_context(tmp_path: Path):
    """Regression: the parasitics stage watches generated/parasitics_per_net.json
    (what the UI's parasitic-selection screen writes) and depends on the netlist,
    not user_context.json. Editing user_context — sim settings, parasitic
    overrides, signals — must NOT stale it; editing the netlist must."""
    project = _copy_example(tmp_path)
    assert main(["parasitics", "per-net", str(project)]) == 0
    config, layout, _ = load_project(project)

    per_net = layout.generated_dir / "parasitics_per_net.json"
    ctx = project / "input" / "user_context.json"
    netlist = (project / config.inputs["netlist_path"]).resolve()
    assert per_net.is_file() and netlist.is_file()

    def _para():
        stages = {s["stage"]: s for s in build_project_status(config, layout)["stages"]}
        return stages["parasitics"]

    # Baseline: netlist older than the per-net estimate, user_context newest.
    os.utime(netlist, (1_000_000, 1_000_000))
    os.utime(per_net, (1_000_050, 1_000_050))
    os.utime(ctx, (1_000_100, 1_000_100))
    p = _para()
    assert p["present"] is True
    assert p["artifact"].endswith("parasitics_per_net.json")
    # user_context newer than the estimate must NOT stale parasitics.
    assert p["stale"] is False

    # The netlist now newer than the estimate MUST stale parasitics.
    os.utime(netlist, (1_000_200, 1_000_200))
    assert _para()["stale"] is True


def test_project_status_aggregates_llm_cost(tmp_path: Path):
    project = tmp_path / "p"
    main(["project", "create", str(project)])
    config, layout, _ = load_project(project)
    llm_dir = layout.results_dir / "llm"
    llm_dir.mkdir(parents=True, exist_ok=True)
    (llm_dir / "run-a.jsonl").write_text(
        json.dumps({"prompt_tokens": 100, "completion_tokens": 40,
                    "estimated_cost_usd": 0.002}) + "\n"
        + json.dumps({"prompt_tokens": 200, "completion_tokens": 60,
                      "estimated_cost_usd": 0.003}) + "\n",
        encoding="utf-8",
    )
    llm = build_project_status(config, layout)["llm"]
    assert llm["calls"] == 2
    assert llm["prompt_tokens"] == 300
    assert llm["completion_tokens"] == 100
    assert llm["estimated_cost_usd"] == 0.005
