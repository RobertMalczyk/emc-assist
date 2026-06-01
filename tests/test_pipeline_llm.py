"""End-to-end pipeline tests with the LLM assistant injected as a stub."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from emc_assistant.cli import main
from emc_assistant.service import resolve as resolve_module
from emc_assistant.llm import StubAssistant


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE = REPO_ROOT / "examples" / "case_001_buck_conducted_emi"


def _copy_example(tmp_path: Path) -> Path:
    dst = tmp_path / "case_001"
    shutil.copytree(EXAMPLE, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)
    return dst


def _make_ltspice_stub(tmp_path: Path):
    """Reuse the same fake-LTspice setup as the mocked-runner tests."""
    fake_exe = tmp_path / "ltspice_stub.exe"
    fake_exe.write_text("# stub", encoding="utf-8")
    return fake_exe


def _ascii_raw(netlist_dir: Path, netlist_stem: str):
    points = [(0.0, 0.0), (1e-6, 1.0), (2e-6, 0.5)]
    raw = (
        "Title: * synthetic\n"
        "Plotname: Transient Analysis\n"
        "Flags: real\n"
        "No. Variables: 2\n"
        f"No. Points: {len(points)}\n"
        "Variables:\n"
        "\t0\ttime\ttime\n"
        "\t1\tV(MEAS)\tvoltage\n"
        "Values:\n"
    )
    body = []
    for i, (t, v) in enumerate(points):
        body.append(f"{i}\t{t}")
        body.append(f"\t{v}")
    (netlist_dir / f"{netlist_stem}.raw").write_text(raw + "\n".join(body) + "\n", encoding="utf-8")


def _meas_log(netlist_dir: Path, netlist_stem: str):
    log = (
        "Circuit: * synthetic\n"
        ".step sweep_corner=1\n"
        "Measurement: vpeak\n"
        "  MAX(v(meas))=1.0 FROM 0 TO 2e-06\n"
        "Total elapsed time: 0.001 seconds.\n"
    )
    (netlist_dir / f"{netlist_stem}.log").write_text(log, encoding="utf-8")


def _fake_subprocess_run(command, *args, **kwargs):
    nl = Path(command[-1])
    if nl.is_file():
        _ascii_raw(nl.parent, nl.stem)
        _meas_log(nl.parent, nl.stem)

    class _Proc:
        returncode = 0
        stdout = ""
        stderr = ""

    return _Proc()


def test_pipeline_llm_none_produces_deterministic_diagnostic_section(
    tmp_path: Path, monkeypatch
):
    """M2.11 acceptance (deterministic mode): the Diagnostic section
    is always rendered at the top of the report -- right after the
    disclaimer -- even with --llm none."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
        ]
    )
    assert rc == 0
    diag_path = project / "results" / "diagnostic.json"
    assert diag_path.is_file()
    diag = json.loads(diag_path.read_text(encoding="utf-8"))
    # Deterministic stub provenance.
    assert diag["llm_generated"] is False
    # Concrete content checks (not just truthiness).
    assert "deterministic synthesis" in diag["narrative"].lower(), diag["narrative"]
    assert diag["dominant_issue"], "dominant_issue must be non-empty"
    # Deterministic stub confidence sits in the documented [0.2..0.6] band.
    assert 0.2 <= diag["confidence"] <= 0.6
    # The stub always notes its provenance in limitations.
    assert any("deterministic" in lim.lower() for lim in diag["limitations"])

    report = (project / "reports" / "report.md").read_text(encoding="utf-8")
    # Section heading + provenance tag explicit in the rendered report.
    assert "## Diagnostic (M2.11)" in report
    assert "deterministic stub" in report
    assert "LLM-written" not in report.split("## Diagnostic (M2.11)")[1].split("##")[0]
    # The Diagnostic section comes before Project assumptions.
    diag_idx = report.index("## Diagnostic (M2.11)")
    assumptions_idx = report.index("## Project assumptions")
    assert diag_idx < assumptions_idx
    # Dominant-issue line is rendered.
    assert "**Dominant issue:**" in report


def test_pipeline_with_stub_assistant_produces_llm_diagnostic(
    tmp_path: Path, monkeypatch
):
    """M2.11 acceptance (LLM mode): a StubAssistant whose `complete()`
    returns valid narrative JSON drives the synthesis path end-to-end;
    diagnostic.json is llm_generated=True and the report tags it
    'LLM-written'."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    # complete() is called by the 11 agents AND by the synthesiser. Route
    # them with a callback so the synthesis purpose gets a valid narrative
    # JSON while agents still get a (separately) valid finding JSON.
    def _route(_messages, purpose):
        if purpose == "synthesis.diagnostic":
            return json.dumps({
                "title": "Stub: input filter resonance dominates",
                "narrative": (
                    "Stub LLM synthesis: 3 agents converge on DM-side "
                    "input-filter resonance. Variant ranking confirms a "
                    "modest baseline-vs-corner spread. Hypothesis."
                ),
                "dominant_issue": "Stub: input filter resonance dominates the conducted-EMI band.",
                "confidence": 0.62,
                "cited_findings": ["dcdc", "filtering"],
                "cited_variants": ["baseline"],
                "cited_rule_ids": ["R-074"],
                "limitations": ["Stub LLM -- not a real synthesis."],
            })
        # Per-agent calls: emit a minimally valid AgentFinding shape.
        return json.dumps({
            "confidence": 0.5,
            "findings": [{"title": "stub finding", "detail": "stub detail", "severity": "info"}],
            "risks": [],
            "recommendations": [],
            "missing_data": [],
            "simulation_requests": [],
            "sources": [],
            "limitations": [],
        })

    stub = StubAssistant(completion_callback=_route)
    original = resolve_module.make_assistant

    def _make_with_stub(options, *, layout, run_id):
        options.stub_assistant = stub
        return original(options, layout=layout, run_id=run_id)

    monkeypatch.setattr(resolve_module, "make_assistant", _make_with_stub)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
            "--llm",
            "openai",
            "--llm-mode",
            "replace",
        ]
    )
    assert rc == 0

    # The synthesiser made exactly one call with the right purpose.
    synthesis_calls = [c for c in stub.complete_calls if c[1] == "synthesis.diagnostic"]
    assert len(synthesis_calls) == 1
    # And the 11 specialist agents each made one call.
    agent_calls = [c for c in stub.complete_calls if c[1].startswith("agent.")]
    assert len(agent_calls) == 11

    # diagnostic.json picked up the LLM content.
    diag = json.loads(
        (project / "results" / "diagnostic.json").read_text(encoding="utf-8")
    )
    assert diag["llm_generated"] is True
    assert diag["title"] == "Stub: input filter resonance dominates"
    assert diag["confidence"] == 0.62
    assert diag["cited_findings"] == ["dcdc", "filtering"]
    assert diag["cited_rule_ids"] == ["R-074"]

    # Report renders the LLM-written tag and the canned title.
    report = (project / "reports" / "report.md").read_text(encoding="utf-8")
    diag_section = report.split("## Diagnostic (M2.11)")[1].split("##")[0]
    assert "LLM-written" in diag_section
    assert "deterministic stub" not in diag_section
    assert "Stub: input filter resonance dominates" in diag_section
    assert "dcdc" in diag_section and "filtering" in diag_section
    assert "R-074" in diag_section


def test_pipeline_accept_parasitics_splices_x_trace_into_testbench(
    tmp_path: Path, monkeypatch
):
    """M2.10 acceptance: --accept-parasitics writes an injection plan and
    splices X_TRACE_VIN into testbench.cir + every variant."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--accept-wiring",
            "--accept-parasitics",
        ]
    )
    assert rc == 0
    # Audit file written.
    audit_path = project / "generated" / "parasitics_wiring.json"
    assert audit_path.is_file()
    audit = json.loads(audit_path.read_text(encoding="utf-8"))
    assert len(audit) >= 1
    assert audit[0]["subckt_name"] == "TRACE_RLC"
    assert audit[0]["instance_name"].startswith("X_")
    # Testbench has the X-instance + cable rerouted to n_dut_in_pre.
    tb = (project / "generated" / "testbench.cir").read_text(encoding="utf-8")
    assert "X_TRACE_VIN" in tb
    assert "n_dut_in_pre" in tb
    # Every variant also has the splice.
    variants_dir = project / "generated" / "variants"
    cir_files = list(variants_dir.glob("*.cir"))
    assert cir_files, "no variant .cir files produced"
    for cir_path in cir_files:
        text = cir_path.read_text(encoding="utf-8")
        assert "X_TRACE_VIN" in text, f"missing injection in {cir_path.name}"


def test_pipeline_no_parasitics_preserves_m261_behaviour(tmp_path: Path, monkeypatch):
    """M2.10 regression: --no-parasitics matches M2.6.1 wiring exactly."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--accept-wiring",
            "--no-parasitics",
        ]
    )
    assert rc == 0
    # No audit file written.
    assert not (project / "generated" / "parasitics_wiring.json").exists()
    # Testbench has the M2.6.1 cable wiring directly to dut_supply_net.
    tb = (project / "generated" / "testbench.cir").read_text(encoding="utf-8")
    assert "n_dut_in_pre" not in tb
    assert "X_TRACE_VIN" not in tb


def test_pipeline_llm_none_produces_eleven_agent_findings(tmp_path: Path, monkeypatch):
    """M2.9 + M2.10.1 acceptance: --llm none produces 11 finding JSONs (10 M2.9 + signal_map)."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
        ]
    )
    assert rc == 0

    findings_dir = project / "results" / "findings"
    assert findings_dir.is_dir()
    json_files = sorted(p.name for p in findings_dir.glob("*.json"))
    expected = {
        "dcdc.json",
        "filtering.json",
        "power_integrity.json",
        "decoupling.json",
        "parasitics.json",
        "stackup.json",
        "high_speed.json",
        "mixed_signal.json",
        "ic_vendor.json",
        "layout_risk.json",
        "signal_map.json",
    }
    assert set(json_files) == expected

    # Every finding is schema-valid (the orchestrator validates on write,
    # but assert here too to lock in the format).
    for f in json_files:
        data = json.loads((findings_dir / f).read_text(encoding="utf-8"))
        assert data["llm_generated"] is False
        assert data["recommendations"], f"{f}: no recommendations"

    # Report has the specialist findings section with 10 subsections.
    report = (project / "reports" / "report.md").read_text(encoding="utf-8")
    assert "## Specialist findings (per area)" in report
    # Every agent has a level-3 subheading.
    for agent_name in (
        "dcdc",
        "filtering",
        "power_integrity",
        "decoupling",
        "parasitics",
        "stackup",
        "high_speed",
        "mixed_signal",
        "ic_vendor",
        "layout_risk",
        "signal_map",
    ):
        assert f"`{agent_name}`" in report, f"missing subsection for {agent_name}"


def test_pipeline_llm_none_is_byte_equivalent_to_baseline(tmp_path: Path, monkeypatch):
    """`--llm none` regression: M2.7 must not change the deterministic output."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
            # implicit --llm none default
        ]
    )
    assert rc == 0
    recs_path = project / "generated" / "recommendations.json"
    assert recs_path.is_file()
    recs = json.loads(recs_path.read_text(encoding="utf-8"))
    assert len(recs) > 0
    # llm_generated must be False everywhere under --llm none
    assert all(r.get("llm_generated") is False for r in recs)
    # citations is present but empty
    assert all(r.get("citations") == [] for r in recs)


def test_pipeline_with_stub_assistant_replace_mode_writes_llm_recs(
    tmp_path: Path, monkeypatch
):
    """Inject a StubAssistant; assert the report carries llm_generated recs."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    stub = StubAssistant()

    # Monkey-patch _make_assistant so cmd_report_generate picks up our stub.
    original = resolve_module.make_assistant

    def _make_with_stub(options, *, layout, run_id):
        options.stub_assistant = stub
        return original(options, layout=layout, run_id=run_id)

    monkeypatch.setattr(resolve_module, "make_assistant", _make_with_stub)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
            "--llm",
            "openai",  # value doesn't matter; stub is forced
            "--llm-mode",
            "replace",
        ]
    )
    assert rc == 0
    assert stub.call_count == 1
    assert stub.last_mode == "replace"
    # Snippets were retrieved and passed to the assistant.
    assert len(stub.last_snippets) > 0
    # Recommendations on disk are LLM-flagged.
    recs = json.loads(
        (project / "generated" / "recommendations.json").read_text(encoding="utf-8")
    )
    assert any(r.get("llm_generated") for r in recs)
    assert any(r.get("citations") for r in recs)


def test_pipeline_with_stub_assistant_augment_mode_keeps_baseline_ids(
    tmp_path: Path, monkeypatch
):
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    stub = StubAssistant()
    original = resolve_module.make_assistant

    def _make_with_stub(options, *, layout, run_id):
        options.stub_assistant = stub
        return original(options, layout=layout, run_id=run_id)

    monkeypatch.setattr(resolve_module, "make_assistant", _make_with_stub)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
            "--llm",
            "openai",
            "--llm-mode",
            "augment",
        ]
    )
    assert rc == 0
    assert stub.last_mode == "augment"
    assert stub.last_baseline_recs is not None
    # Augment mode preserves the deterministic baseline's ID count.
    recs = json.loads(
        (project / "generated" / "recommendations.json").read_text(encoding="utf-8")
    )
    assert all(r.get("llm_generated") for r in recs)
    # Every augmented rec should mention a citation
    assert any(r.get("citations") for r in recs)


def test_pipeline_budget_exceeded_aborts_with_clear_error(
    tmp_path: Path, monkeypatch, capsys
):
    """A trivially-small --llm-budget-usd must abort cleanly with rc=2 before any OpenAI call."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setenv("OPENAI_API_KEY", "fake-key-not-used")
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
            "--llm",
            "openai",
            "--llm-budget-usd",
            "1e-12",
        ]
    )
    assert rc == 2
    captured = capsys.readouterr()
    assert "Estimated LLM cost" in captured.out
    assert "exceeds budget" in captured.out


def test_pipeline_llm_openai_writes_privacy_log_with_no_raw_bodies(
    tmp_path: Path, monkeypatch
):
    """Live OpenAI is mocked at the client level; assert the audit log is written and contains
    only redacted snippet content (no raw vendor-document body)."""
    project = _copy_example(tmp_path)
    fake_exe = _make_ltspice_stub(tmp_path)
    monkeypatch.setenv("LTSPICE_PATH", str(fake_exe))
    monkeypatch.setenv("OPENAI_API_KEY", "fake")
    monkeypatch.setattr(subprocess, "run", _fake_subprocess_run)

    # Patch the assistant factory to build an OpenAiAssistant pre-injected with a fake client.
    from tests.test_llm_openai_provider import _FakeOpenAi
    from emc_assistant.llm.openai_provider import OpenAiAssistant

    def _factory_with_fake_client(options, *, layout, run_id):
        # Force a stub embedder so the M2.9.1 per-agent retrieval path
        # doesn't load the real sentence-transformers model in CI.
        from emc_assistant.knowledge.embedder import EmbedderStub
        options.stub_embedder = EmbedderStub()
        log_path = layout.results_dir / "llm" / f"{run_id}.jsonl"
        return (
            OpenAiAssistant(
                model="gpt-5-mini",
                budget_usd=1.0,
                privacy_log_path=log_path,
                client=_FakeOpenAi(),
            ),
            str(log_path),
        )

    monkeypatch.setattr(resolve_module, "make_assistant", _factory_with_fake_client)

    rc = main(
        [
            "pipeline",
            "run",
            str(project),
            "--mode",
            "local-run",
            "--rank-metric",
            "v_meas_peak",
            "--llm",
            "openai",
        ]
    )
    assert rc == 0
    llm_dir = project / "results" / "llm"
    assert llm_dir.is_dir()
    log_files = list(llm_dir.glob("*.jsonl"))
    assert len(log_files) == 1
    log_content = log_files[0].read_text(encoding="utf-8")
    # No raw vendor body should be in the log
    assert "PROPRIETARY VENDOR TEXT" not in log_content
    # Each entry parses as JSON and has the required fields
    for line in log_content.splitlines():
        entry = json.loads(line)
        assert entry["model"] == "gpt-5-mini"
        assert entry["prompt_messages"]
        assert "estimated_cost_usd" in entry
