"""Tests for OpenAI API-key resolution (env var or key file).

The provider reads the key from OPENAI_API_KEY or, failing that, a
plain-text key file (``~/.emc-assistant/openai_key`` or the repo-root
``.openai_key``) — the simple "store the key in a file" path. These tests
isolate the resolution by monkeypatching the candidate-file list so they
never touch the user's real key files.
"""

from __future__ import annotations

from pathlib import Path

from emc_assistant.llm import openai_provider as op


def test_env_var_wins_over_key_file(monkeypatch, tmp_path):
    f = tmp_path / "openai_key"
    f.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")
    monkeypatch.setattr(op, "candidate_key_files", lambda: [f])
    assert op.resolve_api_key() == "env-key"


def test_reads_key_from_file_when_env_absent(monkeypatch, tmp_path):
    f = tmp_path / "openai_key"
    f.write_text("  sk-from-file\n", encoding="utf-8")   # surrounding whitespace
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(op, "candidate_key_files", lambda: [f])
    assert op.resolve_api_key() == "sk-from-file"


def test_first_existing_file_wins(monkeypatch, tmp_path):
    missing = tmp_path / "nope"
    first = tmp_path / "a"
    second = tmp_path / "b"
    first.write_text("key-a", encoding="utf-8")
    second.write_text("key-b", encoding="utf-8")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(op, "candidate_key_files", lambda: [missing, first, second])
    assert op.resolve_api_key() == "key-a"


def test_none_when_no_key_anywhere(monkeypatch, tmp_path):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setattr(op, "candidate_key_files", lambda: [tmp_path / "absent"])
    assert op.resolve_api_key() is None


def test_blank_env_falls_through_to_file(monkeypatch, tmp_path):
    f = tmp_path / "openai_key"
    f.write_text("file-key", encoding="utf-8")
    monkeypatch.setenv("OPENAI_API_KEY", "   ")          # blank → ignored
    monkeypatch.setattr(op, "candidate_key_files", lambda: [f])
    assert op.resolve_api_key() == "file-key"


def test_candidate_files_include_config_dir_and_repo_root(monkeypatch):
    monkeypatch.delenv("EMC_ASSISTANT_OPENAI_KEY_FILE", raising=False)
    paths = op.candidate_key_files()
    assert any(p == Path.home() / ".emc-assistant" / "openai_key" for p in paths)
    assert any(p.name == ".openai_key" for p in paths)


def test_env_override_path_is_searched_first(monkeypatch, tmp_path):
    override = tmp_path / "my_key_file"
    monkeypatch.setenv("EMC_ASSISTANT_OPENAI_KEY_FILE", str(override))
    paths = op.candidate_key_files()
    assert paths[0] == override
