"""Tests for ``service.project.set_schematic`` + the ``Api.set_schematic``
bridge method — the "drop a schematic into a project" flow used by the
M3 UI's Import & context screen.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from emc_assistant.service import project as project_service
from emc_assistant.service.results import ServiceError
from emc_assistant.ui.bridge import Api


def _fresh_project(tmp_path: Path) -> Path:
    """Create an empty ``.emcproj`` under ``tmp_path`` and return its root."""
    root = tmp_path / "fresh_project"
    project_service.create_project(root)
    return root


def _yaml_inputs(project_root: Path) -> dict:
    raw = yaml.safe_load((project_root / "project.yaml").read_text(encoding="utf-8"))
    return raw["inputs"]


# ---- service function ------------------------------------------------------


def test_set_schematic_copies_asc_into_input_and_updates_yaml(tmp_path: Path):
    project = _fresh_project(tmp_path)
    src = tmp_path / "elsewhere" / "demo.asc"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text("Version 4\n* placeholder LTspice .asc\n", encoding="utf-8")

    result = project_service.set_schematic(project, src)

    assert result.copied is True
    assert result.netlist_path == "input/demo.asc"
    assert result.schematic_path == "input/demo.asc"      # .asc gets both
    assert result.destination == project / "input" / "demo.asc"
    assert result.destination.is_file()
    inputs = _yaml_inputs(project)
    assert inputs["netlist_path"] == "input/demo.asc"
    assert inputs["schematic_path"] == "input/demo.asc"


def test_set_schematic_cir_source_updates_netlist_only(tmp_path: Path):
    project = _fresh_project(tmp_path)
    src = tmp_path / "buck.cir"
    src.write_text("* buck\nV1 vin 0 12\n.end\n", encoding="utf-8")

    result = project_service.set_schematic(project, src)
    assert result.netlist_path == "input/buck.cir"
    assert result.schematic_path is None      # .cir leaves schematic_path
    inputs = _yaml_inputs(project)
    assert inputs["netlist_path"] == "input/buck.cir"


def test_set_schematic_idempotent_when_source_already_in_input(tmp_path: Path):
    project = _fresh_project(tmp_path)
    src = project / "input" / "in_place.asc"
    src.write_text("Version 4\n", encoding="utf-8")

    result = project_service.set_schematic(project, src)

    assert result.copied is False                # nothing to copy
    assert result.destination == src
    assert src.is_file()
    assert _yaml_inputs(project)["netlist_path"] == "input/in_place.asc"


def test_set_schematic_overwrites_an_existing_same_named_file(tmp_path: Path):
    """The semantic is 'replace the project's schematic with this one' —
    a same-named file in input/ from a previous drop is overwritten."""
    project = _fresh_project(tmp_path)
    (project / "input" / "demo.asc").write_text("old", encoding="utf-8")

    src = tmp_path / "demo.asc"
    src.write_text("new", encoding="utf-8")
    project_service.set_schematic(project, src)
    assert (project / "input" / "demo.asc").read_text(encoding="utf-8") == "new"


def test_set_schematic_preserves_unrelated_project_yaml_keys(tmp_path: Path):
    """Updating inputs must not erase the rest of project.yaml — privacy,
    ltspice, name etc. round-trip untouched."""
    project = _fresh_project(tmp_path)
    src = tmp_path / "demo.cir"
    src.write_text("* demo\n", encoding="utf-8")

    project_service.set_schematic(project, src)

    raw = yaml.safe_load((project / "project.yaml").read_text(encoding="utf-8"))
    # Skeleton wrote privacy + ltspice blocks; they should still be present.
    assert "privacy" in raw
    assert "ltspice" in raw
    assert raw["inputs"]["netlist_path"] == "input/demo.cir"


def test_set_schematic_missing_source_raises_service_error(tmp_path: Path):
    project = _fresh_project(tmp_path)
    with pytest.raises(ServiceError, match="Source file not found"):
        project_service.set_schematic(project, tmp_path / "absent.asc")


def test_set_schematic_unsupported_suffix_raises_service_error(tmp_path: Path):
    project = _fresh_project(tmp_path)
    src = tmp_path / "demo.txt"
    src.write_text("not a schematic", encoding="utf-8")
    with pytest.raises(ServiceError, match="Unsupported schematic format"):
        project_service.set_schematic(project, src)


def test_set_schematic_no_project_raises_service_error(tmp_path: Path):
    with pytest.raises(ServiceError):
        project_service.set_schematic(tmp_path / "no_such_project", tmp_path / "x.cir")


# ---- bridge wrapper --------------------------------------------------------


def test_bridge_set_schematic_returns_ok_envelope(tmp_path: Path):
    project = _fresh_project(tmp_path)
    src = tmp_path / "buck.cir"
    src.write_text("* buck\n", encoding="utf-8")

    res = Api().set_schematic(str(project), str(src))
    assert res["ok"] is True
    assert res["data"]["netlist_path"] == "input/buck.cir"
    assert res["data"]["copied"] is True


def test_bridge_set_schematic_reports_missing_source_as_error_envelope(tmp_path: Path):
    project = _fresh_project(tmp_path)
    res = Api().set_schematic(str(project), str(tmp_path / "nope.cir"))
    assert res["ok"] is False
    assert "not found" in res["error"]["message"].lower()


def test_bridge_project_inputs_returns_netlist_path(tmp_path: Path):
    """The Import screen reads the configured schematic filename from
    `project_inputs`; after a set_schematic it reflects the new netlist."""
    project = _fresh_project(tmp_path)
    src = tmp_path / "buck.cir"
    src.write_text("* buck\n", encoding="utf-8")
    Api().set_schematic(str(project), str(src))

    res = Api().project_inputs(str(project))
    assert res["ok"] is True
    assert res["data"]["netlist_path"] == "input/buck.cir"
    assert "models_dir" in res["data"]


def test_bridge_project_inputs_missing_project_is_error_envelope(tmp_path: Path):
    res = Api().project_inputs(str(tmp_path / "no_such_project"))
    assert res["ok"] is False
    assert "message" in res["error"]
