"""Minimal SPICE `.cir` netlist parser.

Recognises element prefixes R, L, C, V, I, X, M, D. Directives
(``.include``, ``.model``, ``.param``, ``.tran``, ``.ac``, ``.step``,
``.end``) are kept as a separate list without interpretation. A full
graphical `.asc` parser is intentionally out of MVP scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


ELEMENT_PREFIXES = "RLCVIXMDSQJ"
"""Recognised element prefixes. S = voltage-controlled switch (4 nodes),
Q = BJT (3 nodes), J = JFET (3 nodes) were added so the switching node
of a behavioural converter is parsed — it's the dominant conducted-EMI
net and the per-net parasitic estimator must see it."""


@dataclass
class NetlistElement:
    refdes: str
    kind: str  # first letter, uppercased
    nodes: list[str]
    value: str = ""
    extra: list[str] = field(default_factory=list)
    raw: str = ""


@dataclass
class NetlistDirective:
    name: str  # e.g. ".tran"
    args: list[str]
    raw: str = ""


@dataclass
class ParsedNetlist:
    title: str
    elements: list[NetlistElement] = field(default_factory=list)
    directives: list[NetlistDirective] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)

    def elements_by_kind(self, kind: str) -> list[NetlistElement]:
        kind = kind.upper()
        return [el for el in self.elements if el.kind == kind]


_TOKEN_SPLIT = re.compile(r"\s+")


def _read_cir_text(path: Path) -> str:
    """Read a .cir tolerant of LTspice's encoding quirks.

    LTspice writes .cir/.net as latin-1 / cp1252 on Windows (µ, Ω etc.
    as non-ASCII bytes) with no BOM. Older versions emitted UTF-16 LE.
    Try several encodings; we only need to read element / directive
    tokens for parsing, so ``errors="replace"`` is safe.
    """
    for enc in ("utf-8", "latin-1", "cp1252", "utf-16-le", "utf-16"):
        try:
            return path.read_text(encoding=enc, errors="replace")
        except (UnicodeError, ValueError):
            continue
    return path.read_text(encoding="latin-1", errors="replace")


def parse_cir(source: str | Path) -> ParsedNetlist:
    text = _read_cir_text(Path(source)) if isinstance(source, Path) else str(source)
    lines = text.splitlines()
    title = lines[0].strip() if lines else ""
    elements: list[NetlistElement] = []
    directives: list[NetlistDirective] = []
    comments: list[str] = []

    for raw_line in lines[1:]:
        line = raw_line.rstrip()
        if not line.strip():
            continue
        stripped = line.lstrip()
        if stripped.startswith("*"):
            comments.append(stripped[1:].strip())
            continue
        # Strip a SPICE inline comment (`;` to end of line). LTspice
        # emits these on X-instance lines (e.g. `;§pnba _RETRY)EN)...`);
        # without this the comment tokens leak into the node list.
        if ";" in stripped:
            head, _, tail = stripped.partition(";")
            if tail.strip():
                comments.append(tail.strip())
            stripped = head.rstrip()
            if not stripped:
                continue
        if stripped.startswith("."):
            tokens = _TOKEN_SPLIT.split(stripped)
            directives.append(
                NetlistDirective(name=tokens[0].lower(), args=tokens[1:], raw=stripped)
            )
            continue
        first = stripped[0].upper()
        if first not in ELEMENT_PREFIXES:
            comments.append(stripped)
            continue
        tokens = _TOKEN_SPLIT.split(stripped)
        if len(tokens) < 3:
            comments.append(stripped)
            continue
        refdes = tokens[0]
        # Node count depends on element kind: R/L/C/V/I/D → 2 nodes,
        # M/S → 4 nodes, Q/J → 3 nodes, X → variable (subckt name is the
        # last non-`key=value` token).
        if first in {"R", "L", "C", "V", "I", "D"}:
            nodes = tokens[1:3]
            tail = tokens[3:]
            value = tail[0] if tail else ""
            extra = tail[1:]
        elif first in {"M", "S"}:
            # M = MOSFET (D G S B), S = voltage-controlled switch
            # (n+ n- ctrl+ ctrl-) — both carry 4 nodes then a model name.
            nodes = tokens[1:5]
            value = tokens[5] if len(tokens) > 5 else ""
            extra = tokens[6:]
        elif first in {"Q", "J"}:
            # Q = BJT (C B E [substrate]), J = JFET (D G S) — 3 nodes
            # then a model name.
            nodes = tokens[1:4]
            value = tokens[4] if len(tokens) > 4 else ""
            extra = tokens[5:]
        elif first == "X":
            # X = subcircuit instance: `Xname node... subckt [param=value...]`.
            # Node count is variable, so locate the subcircuit name as the
            # last token that is NOT a `key=value` parameter; everything
            # before it is a node, everything after is a parameter.
            body = tokens[1:]
            subckt_idx = next(
                (i for i in range(len(body) - 1, -1, -1) if "=" not in body[i]),
                None,
            )
            if subckt_idx is None:
                nodes = body
                value = ""
                extra = []
            else:
                nodes = body[:subckt_idx]
                value = body[subckt_idx]
                extra = body[subckt_idx + 1 :]
        else:  # pragma: no cover — covered above
            nodes = tokens[1:]
            value = ""
            extra = []
        elements.append(
            NetlistElement(
                refdes=refdes,
                kind=first,
                nodes=list(nodes),
                value=value,
                extra=list(extra),
                raw=stripped,
            )
        )

    return ParsedNetlist(title=title, elements=elements, directives=directives, comments=comments)
