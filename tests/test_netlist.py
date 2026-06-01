"""Tests for the minimal netlist parser."""

from __future__ import annotations

from pathlib import Path

from emc_assistant.netlist import parse_cir


REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLE_CIR = (
    REPO_ROOT
    / "examples"
    / "case_001_buck_conducted_emi"
    / "input"
    / "placeholder_original.cir"
)


def test_parse_example_cir():
    parsed = parse_cir(EXAMPLE_CIR)
    assert parsed.title.startswith("*")
    kinds = {el.kind for el in parsed.elements}
    assert {"V", "R", "C", "L", "I"}.issubset(kinds)
    assert any(d.name == ".tran" for d in parsed.directives)


def test_parse_inline_string():
    src = (
        "* test\n"
        "Vin in 0 DC 5\n"
        "R1 in out 100\n"
        "C1 out 0 1u\n"
        ".tran 0 1m\n"
        ".end\n"
    )
    parsed = parse_cir(src)
    refdes = [el.refdes for el in parsed.elements]
    assert refdes == ["Vin", "R1", "C1"]
    assert parsed.elements_by_kind("R")[0].nodes == ["in", "out"]


def test_x_subckt_separates_nodes_params_and_comment():
    """An X instance with `key=value` params and a `;` inline comment:
    the subckt name, params and comment must not leak into the nodes."""
    src = (
        "* test\n"
        "X1 in out vdd 0 MYSUB gain=2 mode=fast ;§pnba a)b)c\n"
        ".end\n"
    )
    x = parse_cir(src).elements_by_kind("X")[0]
    assert x.nodes == ["in", "out", "vdd", "0"]
    assert x.value == "MYSUB"
    assert x.extra == ["gain=2", "mode=fast"]


def test_x_subckt_without_params():
    x = parse_cir("* t\nX1 a b SUB\n.end\n").elements_by_kind("X")[0]
    assert x.nodes == ["a", "b"]
    assert x.value == "SUB"
    assert x.extra == []


def test_inline_comment_stripped_from_element():
    """A `;` inline comment must not become an element value/node."""
    r = parse_cir("* t\nR1 a b 1k ; pull-up\n.end\n").elements_by_kind("R")[0]
    assert r.nodes == ["a", "b"]
    assert r.value == "1k"
    assert "pull-up" not in r.extra
