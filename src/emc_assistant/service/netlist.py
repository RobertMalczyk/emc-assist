"""User-netlist inspection — service layer."""

from __future__ import annotations

from dataclasses import dataclass

from emc_assistant.netlist import parse_cir
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError


@dataclass
class NetlistElement:
    refdes: str
    kind: str
    nodes: list[str]
    value: str | None


@dataclass
class NetlistDirective:
    name: str
    args: list[str]


@dataclass
class NetlistInspectResult:
    title: str
    elements: list[NetlistElement]
    directives: list[NetlistDirective]


def inspect_netlist(project_root) -> NetlistInspectResult:
    """Parse the project's input ``.cir`` netlist and return its title,
    elements and directives."""
    config, layout = require_project(project_root)
    rel = config.inputs.get("netlist_path", "")
    if not rel:
        raise ServiceError("Missing `inputs.netlist_path` in project.yaml.")
    path = (layout.root / rel).resolve()
    if not path.is_file():
        raise ServiceError(f"Netlist file does not exist: {path}")
    parsed = parse_cir(path)
    return NetlistInspectResult(
        title=parsed.title,
        elements=[
            NetlistElement(el.refdes, el.kind, list(el.nodes), el.value)
            for el in parsed.elements
        ],
        directives=[
            NetlistDirective(d.name, list(d.args)) for d in parsed.directives
        ],
    )
