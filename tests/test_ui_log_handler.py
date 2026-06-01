"""Tests for the logging-seam UI handler."""

from __future__ import annotations

import logging

from emc_assistant.ui.log_handler import QueueLogHandler, record_to_dict


def _record(name: str, level: int, msg: str) -> logging.LogRecord:
    return logging.LogRecord(name, level, __file__, 1, msg, None, None)


def test_record_to_dict_shape():
    d = record_to_dict(_record("emc_assistant.pipeline", logging.WARNING, "hi"))
    assert d["level"] == "WARNING"
    assert d["component"] == "pipeline"  # emc_assistant. prefix stripped
    assert d["message"] == "hi"
    assert d["timestamp"].endswith("Z")


def test_queue_mode_buffers_and_drains():
    handler = QueueLogHandler()
    logger = logging.getLogger("emc_assistant.testq")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("one")
        logger.warning("two")
        logger.error("three")
    finally:
        logger.removeHandler(handler)

    drained = handler.drain()
    assert [d["message"] for d in drained] == ["one", "two", "three"]
    assert [d["level"] for d in drained] == ["INFO", "WARNING", "ERROR"]
    assert all(d["component"] == "testq" for d in drained)
    # A second drain yields nothing — the queue was emptied.
    assert handler.drain() == []


def test_callback_mode_notifies_per_record():
    seen: list[dict] = []
    handler = QueueLogHandler(callback=seen.append)
    logger = logging.getLogger("emc_assistant.testcb")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("via callback")
    finally:
        logger.removeHandler(handler)

    assert len(seen) == 1
    assert seen[0]["message"] == "via callback"
    # Callback mode does not also buffer.
    assert handler.drain() == []


def test_bad_callback_does_not_break_logging():
    def _boom(_entry):
        raise RuntimeError("callback blew up")

    handler = QueueLogHandler(callback=_boom)
    logger = logging.getLogger("emc_assistant.testbad")
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    try:
        logger.info("should not raise")  # must not propagate the callback error
    finally:
        logger.removeHandler(handler)
