"""Tests for the structured logging seam (``emc_assistant.logging_setup``).

This module is used by every service module, the CLI and the UI but had
no dedicated test — only indirect exercise through CLI tests. Here we
pin the behaviour that those indirect tests would not catch a regression
in: the JSONL log-file format, ``configure_logging`` idempotency, the
level mapping, and the ``_StdoutHandler`` stdout rebinding.
"""

from __future__ import annotations

import io
import json
import logging
import sys
from pathlib import Path

import pytest

from emc_assistant import logging_setup as ls


@pytest.fixture(autouse=True)
def _restore_root_logger():
    """Snapshot / restore the ``emc_assistant`` logger so a test that
    reconfigures it cannot leak into the rest of the suite."""
    logger = logging.getLogger("emc_assistant")
    saved = (list(logger.handlers), logger.level, logger.propagate)
    try:
        yield
    finally:
        logger.handlers = saved[0]
        logger.setLevel(saved[1])
        logger.propagate = saved[2]


def test_get_logger_namespaces_under_emc_assistant():
    assert ls.get_logger("cli").name == "emc_assistant.cli"
    assert ls.get_logger().name == "emc_assistant.cli"  # default component


def test_configure_logging_is_idempotent():
    """Re-calling must not accumulate handlers — it rebuilds them."""
    ls.configure_logging("info")
    first = len(logging.getLogger("emc_assistant").handlers)
    ls.configure_logging("info")
    ls.configure_logging("debug")
    assert len(logging.getLogger("emc_assistant").handlers) == first
    assert first == 1  # just the console handler when no file / ui handler


def test_configure_logging_does_not_propagate_to_root():
    ls.configure_logging("info")
    assert logging.getLogger("emc_assistant").propagate is False


@pytest.mark.parametrize(
    "name, expected",
    [
        ("debug", logging.DEBUG),
        ("info", logging.INFO),
        ("warning", logging.WARNING),
        ("quiet", logging.WARNING),  # "quiet" is an alias for WARNING
    ],
)
def test_level_name_mapping(name, expected):
    ls.configure_logging(name)
    assert logging.getLogger("emc_assistant").level == expected


def test_level_accepts_a_raw_logging_int():
    ls.configure_logging(logging.ERROR)
    assert logging.getLogger("emc_assistant").level == logging.ERROR


def test_console_emits_message_verbatim(capsys):
    """The console handler formats ``%(message)s`` — byte-identical to
    the old ``print()`` output, regardless of level."""
    ls.configure_logging("info")
    ls.get_logger("cli").info("plain line")
    assert capsys.readouterr().out == "plain line\n"


def test_quiet_level_filters_info_but_keeps_warning(capsys):
    ls.configure_logging("quiet")
    log = ls.get_logger("cli")
    log.info("should be hidden")
    log.warning("should show")
    out = capsys.readouterr().out
    assert "should be hidden" not in out
    assert "should show" in out


def test_stdout_handler_tracks_the_current_stream():
    """``_StdoutHandler`` resolves ``sys.stdout`` at emit time — this is
    what keeps it correct under pytest's ``capsys`` / a UI redirect."""
    handler = ls._StdoutHandler()
    assert handler.stream is sys.stdout
    swapped = io.StringIO()
    original = sys.stdout
    try:
        sys.stdout = swapped
        assert handler.stream is swapped
    finally:
        sys.stdout = original
    # The setter is a deliberate no-op — assigning never overrides it.
    handler.stream = io.StringIO()
    assert handler.stream is sys.stdout


def test_jsonl_formatter_emits_one_valid_object_per_record():
    record = logging.LogRecord(
        name="emc_assistant.simulate",
        level=logging.WARNING,
        pathname=__file__,
        lineno=1,
        msg="[sim] %s variants",
        args=(3,),
        exc_info=None,
    )
    line = ls._JsonlFormatter().format(record)
    obj = json.loads(line)
    assert set(obj) == {"timestamp", "level", "component", "message"}
    assert obj["level"] == "WARNING"
    assert obj["component"] == "simulate"  # the emc_assistant. prefix is stripped
    assert obj["message"] == "[sim] 3 variants"  # args are interpolated


def test_configure_logging_with_log_file_writes_jsonl(tmp_path: Path):
    log_file = tmp_path / "run.jsonl"
    ls.configure_logging("info", log_file=log_file)
    ls.get_logger("report").info("report done")
    for h in logging.getLogger("emc_assistant").handlers:
        h.flush()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    obj = json.loads(lines[0])
    assert obj["component"] == "report"
    assert obj["message"] == "report done"


def test_run_log_file_lifecycle(tmp_path: Path):
    """``add_run_log_file`` attaches a JSONL sink; ``remove_handler``
    detaches and closes it so later records do not reach the closed file."""
    ls.configure_logging("info")
    log_file = tmp_path / "per_run.jsonl"
    handler = ls.add_run_log_file(log_file)
    assert handler in logging.getLogger("emc_assistant").handlers

    ls.get_logger("pipeline").info("during the run")
    handler.flush()
    ls.remove_handler(handler)
    assert handler not in logging.getLogger("emc_assistant").handlers

    ls.get_logger("pipeline").info("after the run")  # must not be recorded
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["message"] == "during the run"


class _Cp1250Stream:
    """Mimics a Windows cp1250 console: ``write`` rejects unencodable chars."""

    encoding = "cp1250"

    def __init__(self) -> None:
        self.text = ""

    def write(self, s: str) -> int:
        s.encode(self.encoding)  # raises UnicodeEncodeError on →, ≈, Ω, …
        self.text += s
        return len(s)

    def flush(self) -> None:
        pass


def test_stdout_handler_survives_non_utf8_console(monkeypatch):
    """A cp1250 console must not crash logging (or spam "--- Logging error
    ---") on characters it can't encode — the handler pre-sanitizes to the
    stream's own codec. Regression for the Polish-Windows UI crash."""
    ls.configure_logging("info")
    stream = _Cp1250Stream()
    monkeypatch.setattr(sys, "stdout", stream)
    # The very text that crashed the UI: an LLM/sim-setup line with → and ≈.
    ls.get_logger("cli").info("sim-setup: 50 ns → Nyquist 10 MHz; C ≈ 2.7 pF")
    assert "sim-setup: 50 ns" in stream.text  # nothing raised; text preserved
    assert "Nyquist 10 MHz" in stream.text
    assert stream.text.endswith("\n")


def test_ensure_utf8_stdio_reconfigures_both_streams(monkeypatch):
    calls: list[dict] = []

    class _S:
        def reconfigure(self, **kw):
            calls.append(kw)

    monkeypatch.setattr(sys, "stdout", _S())
    monkeypatch.setattr(sys, "stderr", _S())
    ls.ensure_utf8_stdio()
    assert len(calls) == 2
    assert all(c["encoding"] == "utf-8" for c in calls)


def test_ui_handler_is_attached_when_supplied():
    captured: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record):
            captured.append(record)

    ui = _Capture()
    ls.configure_logging("info", ui_handler=ui)
    assert ui in logging.getLogger("emc_assistant").handlers
    ls.get_logger("cli").info("ui sees this")
    assert [r.getMessage() for r in captured] == ["ui sees this"]
