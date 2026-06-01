"""Tests for the cooperative cancel-run mechanism
(``service.pipeline.request_cancel`` / ``_check_cancel``) and the
matching ``Api.cancel_run`` bridge method.

The cancel is intentionally cooperative — it does **not** kill an
in-flight LTspice subprocess. The pipeline checks the flag at six
boundaries; a cancel takes effect when the current stage finishes.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from emc_assistant.service import pipeline as pipeline_service
from emc_assistant.service.options import CommandOptions
from emc_assistant.service.pipeline import (
    RunCancelled,
    _check_cancel,
    _reset_cancel,
    request_cancel,
)
from emc_assistant.ui.bridge import Api


@pytest.fixture(autouse=True)
def _isolated_cancel_flag():
    """Reset the module-level cancel flag around every test so cross-test
    pollution can't masquerade as a real cancel."""
    _reset_cancel()
    yield
    _reset_cancel()


# ---- the flag primitives ---------------------------------------------------


def test_check_cancel_noop_when_flag_clear():
    _reset_cancel()
    # Should NOT raise.
    _check_cancel("any-stage")


def test_check_cancel_raises_run_cancelled_when_flag_set():
    request_cancel()
    with pytest.raises(RunCancelled) as exc_info:
        _check_cancel("compose-testbench")
    assert exc_info.value.stage == "compose-testbench"
    assert exc_info.value.exit_code == 130


def test_check_cancel_clears_the_flag_on_raise():
    """After RunCancelled fires once, the flag is clear so the next
    pipeline call starts fresh (no stale cancel from a prior run)."""
    request_cancel()
    with pytest.raises(RunCancelled):
        _check_cancel("parasitics")
    # Second call: flag has been cleared.
    _check_cancel("parasitics")


def test_request_cancel_is_idempotent():
    request_cancel()
    request_cancel()
    request_cancel()
    with pytest.raises(RunCancelled):
        _check_cancel("any-stage")
    _check_cancel("any-stage")  # cleared


# ---- bridge wrapper --------------------------------------------------------


def test_bridge_cancel_run_sets_the_flag_and_returns_envelope():
    res = Api().cancel_run()
    assert res["ok"] is True
    assert res["data"] == {"requested": True}
    with pytest.raises(RunCancelled):
        _check_cancel("any-stage")


# ---- integration with run_pipeline -----------------------------------------


def test_run_pipeline_clears_a_stale_cancel_flag_at_the_start(tmp_path: Path):
    """A cancel flag set _before_ run_pipeline begins is dropped at the
    top of the function so the new run starts clean; the pipeline is
    NOT aborted just because the flag was set previously."""
    examples = Path(__file__).resolve().parents[1] / "examples"
    src = examples / "case_001_buck_conducted_emi"
    if not (src / "project.yaml").is_file():
        pytest.skip("case_001 example not present")
    dst = tmp_path / "case"
    shutil.copytree(src, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)

    request_cancel()  # flag SET before the pipeline starts
    opts = CommandOptions(
        accept_wiring=True, accept_signals=True, accept_parasitics=True,
    )
    result = pipeline_service.run_pipeline(dst, opts)
    assert result.report.report_path.is_file()


def test_run_pipeline_aborts_when_cancel_fires_between_stages(
    tmp_path: Path, monkeypatch
):
    """When ``request_cancel`` is called mid-run (from another thread in
    production; simulated here via a monkeypatched checkpoint), the
    pipeline raises ``RunCancelled`` and does not generate a report."""
    examples = Path(__file__).resolve().parents[1] / "examples"
    src = examples / "case_001_buck_conducted_emi"
    if not (src / "project.yaml").is_file():
        pytest.skip("case_001 example not present")
    dst = tmp_path / "case"
    shutil.copytree(src, dst)
    for sub in ("generated", "results", "reports"):
        shutil.rmtree(dst / sub, ignore_errors=True)

    # Trigger the cancel at the second checkpoint ("compose-testbench")
    # by wrapping _check_cancel to set the flag on its second call.
    real_check = pipeline_service._check_cancel
    state = {"n": 0}

    def _wrapped(stage: str) -> None:
        state["n"] += 1
        if state["n"] == 2:
            request_cancel()
        real_check(stage)

    monkeypatch.setattr(pipeline_service, "_check_cancel", _wrapped)

    opts = CommandOptions(
        accept_wiring=True, accept_signals=True, accept_parasitics=True,
    )
    with pytest.raises(RunCancelled) as exc_info:
        pipeline_service.run_pipeline(dst, opts)
    assert exc_info.value.stage == "compose-testbench"
    # The pipeline aborted before the report stage — no report.md.
    assert not (dst / "reports" / "report.md").is_file()
