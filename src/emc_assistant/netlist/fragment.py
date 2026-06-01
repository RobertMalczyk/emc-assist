"""Preprocess a user netlist into a composer-ready "fragment".

The testbench composer adds its own control directives (``.tran``,
``.end``, optionally ``.step``). To avoid duplicate directives we copy
the user file into ``generated/user_circuit_fragment.cir`` with control
directives stripped. The source file is never modified in place.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable


SERIES_PRE_SUFFIX: str = "__pre"
"""Suffix for the cut-off side of a series-parasitic splice. Splitting
net ``N`` renames it to ``N__pre`` on one element; the composer then
wires a series R+L+C between ``N__pre`` and ``N`` (M2.10.6)."""


def series_pre_net(net: str) -> str:
    """The ``<net>__pre`` name used for the cut-off side of a splice."""
    return f"{net}{SERIES_PRE_SUFFIX}"


STRIPPED_DIRECTIVES: frozenset[str] = frozenset({
    ".tran",
    ".ac",
    ".dc",
    ".op",
    ".noise",
    ".tf",
    ".end",
    ".step",
    ".options",
    ".option",
    ".four",
    ".meas",
    ".measure",
    ".save",
    ".probe",
    ".print",
    ".plot",
    ".backanno",
})
"""Directives removed from the user netlist; simulation control belongs to the composer."""


def strip_control_directives(
    text: str,
    *,
    strip_sources: Iterable[str] = (),
) -> tuple[str, list[str]]:
    """Return (cleaned_text, removed_lines).

    ``strip_sources`` removes element lines whose first token matches one of
    the given names (case-insensitive). Use it when the testbench composer
    is taking over a user-side voltage source — the LISN+cable chain
    replaces it in the assembled netlist.
    """
    sources = {name.lower() for name in strip_sources if name}
    out: list[str] = []
    removed: list[str] = []
    for raw_line in text.splitlines():
        stripped = raw_line.lstrip()
        if stripped.startswith("."):
            head = stripped.split(None, 1)[0].lower()
            if head in STRIPPED_DIRECTIVES:
                removed.append(raw_line.strip())
                continue
        elif sources and stripped and not stripped.startswith("*"):
            head = stripped.split(None, 1)[0].lower()
            if head in sources:
                removed.append(raw_line.strip())
                continue
        out.append(raw_line)
    cleaned = "\n".join(out)
    if not cleaned.endswith("\n"):
        cleaned += "\n"
    return cleaned, removed


def write_user_fragment(
    src: Path,
    dst: Path,
    *,
    strip_sources: Iterable[str] = (),
    rename_ground_to: str | None = None,
    series_split_nets: Iterable[str] = (),
) -> list[str]:
    """Read ``src``, strip control directives, optionally rename ``0`` →
    ``rename_ground_to`` in node positions, optionally split nets for
    series-parasitic injection, and write ``dst``.

    Returns the list of removed lines (for logging/reporting).
    The source file is never modified.

    Pass ``rename_ground_to`` (e.g., ``"DUT_GND"``) when the composer is
    going to wire a dual-LISN topology and needs the user's local ground
    lifted off SPICE's universal ``0`` reference. See
    ``rename_ground_node`` for the renaming rules.

    Pass ``series_split_nets`` (M2.10.6) to cut clean 2-element nets for
    a series-parasitic splice — see :func:`split_series_nets`.
    """
    src = Path(src)
    dst = Path(dst)
    if not src.is_file():
        raise FileNotFoundError(f"User netlist not found: {src}")
    original = src.read_text(encoding="utf-8")
    cleaned, removed = strip_control_directives(original, strip_sources=strip_sources)
    renamed_note = ""
    if rename_ground_to:
        cleaned = rename_ground_node(cleaned, old_node="0", new_node=rename_ground_to)
        renamed_note = f"* Ground rename: '0' -> '{rename_ground_to}' in node positions (dual-LISN).\n"
    split_note = ""
    split_nets = [n for n in series_split_nets if n]
    if split_nets:
        cleaned, did_split = split_series_nets(cleaned, split_nets)
        if did_split:
            pairs = ", ".join(f"{n}->{series_pre_net(n)}" for n in did_split)
            split_note = f"* Series-splice cuts (M2.10.6): {pairs}\n"
    header = (
        f"* Auto-processed copy of {src.name} (control directives stripped).\n"
        f"* Do not edit by hand — regenerate via emc-assistant.\n"
        f"{renamed_note}"
        f"{split_note}"
    )
    if removed:
        header += "* Removed directives: " + ", ".join(removed) + "\n"
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(header + cleaned, encoding="utf-8")
    return removed


_NODE_COUNTS_FIXED: dict[str, int] = {
    # Two-node elements
    "B": 2, "C": 2, "D": 2, "F": 2, "H": 2, "I": 2, "L": 2, "R": 2, "V": 2, "W": 2,
    # Four-node elements (VCVS, VCCS, MOSFET, switch, transmission lines, lossy TL)
    "E": 4, "G": 4, "M": 4, "S": 4, "T": 4, "O": 4,
    # Three-node elements (BJT — fourth substrate is optional and rarely used)
    "Q": 3, "J": 3, "U": 3,
    # K (coupled inductor) takes inductor names not nodes; skip
}


def _node_token_indices(tokens: list[str]) -> list[int]:
    """Indices into ``tokens`` that hold node names (``tokens[0]`` is the
    refdes). Mirrors the per-kind node-position rules used by
    :func:`rename_ground_node`. Returns ``[]`` for ``K`` lines and any
    kind with no fixed node count."""
    if not tokens or not tokens[0]:
        return []
    kind = tokens[0][0].upper()
    if kind == "K":
        return []
    if kind == "X":
        param_start = len(tokens)
        for i, t in enumerate(tokens):
            if "=" in t:
                param_start = i
                break
        return list(range(1, max(1, param_start - 1)))
    n_nodes = _NODE_COUNTS_FIXED.get(kind, 0)
    return list(range(1, min(1 + n_nodes, len(tokens))))


def split_series_nets(text: str, nets: Iterable[str]) -> tuple[str, list[str]]:
    """Cut each net in ``nets`` for a series-parasitic splice (M2.10.6).

    For each target net, the FIRST element line that references it in a
    node position has that net renamed to ``series_pre_net(net)``. After
    the cut, one element sees ``<net>__pre`` and the rest of the circuit
    still sees ``<net>``; the composer wires a series R+L+C between them.

    Only clean 2-element nets should be passed — splitting a star/bus
    net would silently move just one branch. Returns
    ``(new_text, nets_actually_split)``; a net not found in any node
    position is skipped (not in the returned list).
    """
    pending = {n for n in nets if n}
    if not pending:
        return (text if text.endswith("\n") else text + "\n"), []
    out_lines: list[str] = []
    did: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not pending or not stripped or stripped[0] in "*.":
            out_lines.append(line)
            continue
        tokens = stripped.split()
        idxs = _node_token_indices(tokens)
        hit = next((tokens[i] for i in idxs if tokens[i] in pending), None)
        if hit is None:
            out_lines.append(line)
            continue
        leading_ws = line[: len(line) - len(stripped)]
        renamed = list(tokens)
        for i in idxs:
            if renamed[i] == hit:
                renamed[i] = series_pre_net(hit)
        out_lines.append(leading_ws + " ".join(renamed))
        pending.discard(hit)
        did.append(hit)
    out = "\n".join(out_lines)
    if not out.endswith("\n"):
        out += "\n"
    return out, did


def rename_ground_node(text: str, *, old_node: str = "0", new_node: str = "DUT_GND") -> str:
    """Replace the ``old_node`` token with ``new_node`` in SPICE node positions only.

    Node positions vary by element kind:

    - R/C/L/V/I/D/F/H/W/B: nodes at indices 1, 2
    - E/G/M/S/T/O: nodes at indices 1..4
    - Q/J/U: nodes at indices 1..3
    - X (subcircuit instance): every positional token between the refdes
      and the subckt name is a node. The subckt name is the last
      positional token before any ``key=value`` parameter token.

    Comments (lines starting with ``*``), control directives (``.tran``,
    ``.lib``, ``.model``, …) and blank lines are passed through unchanged.
    ``K`` (coupled inductor) lines are also left alone because their
    "ports" are inductor instance names rather than node names.

    Tokens are matched by exact string equality — ``0`` is renamed but
    ``0n``, ``10``, ``0.5m`` are left alone because they're value tokens.
    """
    out_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.lstrip()
        if not stripped or stripped[0] in "*.":
            out_lines.append(line)
            continue
        leading_ws = line[: len(line) - len(stripped)]
        tokens = stripped.split()
        if not tokens:
            out_lines.append(line)
            continue
        kind = tokens[0][0].upper() if tokens[0] else ""
        if kind == "K":
            out_lines.append(line)
            continue
        if kind == "X":
            # Subcircuit instance: nodes are positional tokens before
            # the subckt name. The subckt name is the LAST positional
            # token before the first key=value parameter (or end of line).
            param_start = len(tokens)
            for i, t in enumerate(tokens):
                if "=" in t:
                    param_start = i
                    break
            # tokens[1:param_start-1] are nodes; tokens[param_start-1] is the subckt name.
            last_node_idx_exclusive = max(1, param_start - 1)
            renamed = list(tokens)
            for i in range(1, last_node_idx_exclusive):
                if renamed[i] == old_node:
                    renamed[i] = new_node
            out_lines.append(leading_ws + " ".join(renamed))
            continue
        n_nodes = _NODE_COUNTS_FIXED.get(kind, 0)
        if n_nodes == 0:
            out_lines.append(line)
            continue
        renamed = list(tokens)
        for i in range(1, min(1 + n_nodes, len(renamed))):
            if renamed[i] == old_node:
                renamed[i] = new_node
        out_lines.append(leading_ws + " ".join(renamed))
    out = "\n".join(out_lines)
    if not out.endswith("\n"):
        out += "\n"
    return out
