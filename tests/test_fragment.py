"""Tests for the user-netlist → fragment preprocessor."""

from __future__ import annotations

from pathlib import Path

from emc_assistant.netlist.fragment import (
    rename_ground_node,
    strip_control_directives,
    write_user_fragment,
)


def test_rename_ground_node_two_node_elements():
    src = "R1 in 0 1k\nC1 out 0 1u\nL1 a b 10n\nV1 vin 0 DC 24\n"
    out = rename_ground_node(src)
    assert "R1 in DUT_GND 1k" in out
    assert "C1 out DUT_GND 1u" in out
    # L1 has no `0` so unchanged
    assert "L1 a b 10n" in out
    # V1 second node = 0 → renamed; "DC 24" value stays
    assert "V1 vin DUT_GND DC 24" in out


def test_rename_ground_node_mosfet_four_nodes():
    src = "M1 drain gate source 0 NMOS_MODEL\n"
    out = rename_ground_node(src)
    # 4th node (body) was 0 → renamed
    assert "M1 drain gate source DUT_GND NMOS_MODEL" in out


def test_rename_ground_node_subcircuit_instance():
    """X-instance: rename node positions but not the subckt name or parameters."""
    src = "X1 vin out 0 DC_BLOCK param1=10 param2=20\n"
    out = rename_ground_node(src)
    # `vin`, `out`, `0` are nodes; `DC_BLOCK` is the subckt name; params untouched.
    assert "X1 vin out DUT_GND DC_BLOCK param1=10 param2=20" in out


def test_rename_ground_node_does_not_touch_values():
    """A `0` token in a VALUE position (e.g., V source DC level) must NOT be renamed."""
    # V1 has nodes [vin, gnd_node] and then VALUE DC 0 — that value 0 stays.
    src = "V1 vin n2 DC 0\n"
    out = rename_ground_node(src)
    assert out.strip() == "V1 vin n2 DC 0"  # nothing renamed (no `0` in node positions)


def test_rename_ground_node_skips_comments_and_directives():
    src = "* this line refers to 0 in a comment\n.tran 0 5m\n.model FOO D(Is=0)\nR1 a 0 1k\n"
    out = rename_ground_node(src)
    assert "* this line refers to 0 in a comment" in out
    assert ".tran 0 5m" in out
    assert ".model FOO D(Is=0)" in out
    assert "R1 a DUT_GND 1k" in out


def test_rename_ground_node_handles_k_element():
    """K (coupled inductor) takes inductor names, not nodes; must be left alone."""
    src = "K1 L1 L2 0.99\n"
    out = rename_ground_node(src)
    # The "0.99" is a coupling coefficient (value), not a node; `0` substring inside doesn't count.
    assert out.strip() == "K1 L1 L2 0.99"


def test_rename_ground_node_only_renames_exact_zero_token():
    """`0` is renamed; `0.5m`, `10`, `00` are not."""
    src = "R1 a 0 0.5m\nR2 b 0 10\nC1 c 0 00\n"
    out = rename_ground_node(src)
    assert "R1 a DUT_GND 0.5m" in out
    assert "R2 b DUT_GND 10" in out
    # `00` is not the same token as `0` — leave it (unusual but be conservative)
    assert "C1 c DUT_GND 00" in out


def test_write_user_fragment_renames_ground_when_requested(tmp_path: Path):
    src = tmp_path / "user.cir"
    src.write_text("* user\nR1 in 0 1k\nC1 out 0 1u\n", encoding="utf-8")
    dst = tmp_path / "out" / "fragment.cir"
    write_user_fragment(src, dst, rename_ground_to="DUT_GND")
    text = dst.read_text(encoding="utf-8")
    assert "R1 in DUT_GND 1k" in text
    assert "C1 out DUT_GND 1u" in text
    # Header comment is added
    assert "Ground rename: '0' -> 'DUT_GND'" in text


def test_write_user_fragment_leaves_ground_alone_by_default(tmp_path: Path):
    src = tmp_path / "user.cir"
    src.write_text("R1 in 0 1k\n", encoding="utf-8")
    dst = tmp_path / "out" / "fragment.cir"
    write_user_fragment(src, dst)  # no rename_ground_to
    text = dst.read_text(encoding="utf-8")
    assert "R1 in 0 1k" in text
    assert "DUT_GND" not in text


def test_strip_removes_control_directives():
    src = (
        "* test\n"
        "Vin in 0 5\n"
        "R1 in out 1k\n"
        ".tran 0 1m\n"
        ".end\n"
    )
    cleaned, removed = strip_control_directives(src)
    assert "Vin in 0 5" in cleaned
    assert ".tran" not in cleaned
    assert ".end" not in cleaned
    assert ".tran 0 1m" in removed
    assert ".end" in removed


def test_strip_keeps_subckts_and_models():
    src = (
        ".subckt FOO IN OUT\n"
        "R1 IN OUT 1k\n"
        ".ends FOO\n"
        ".model D D(Is=1e-14)\n"
        ".tran 0 1m\n"
    )
    cleaned, removed = strip_control_directives(src)
    assert ".subckt" in cleaned.lower()
    assert ".model" in cleaned.lower()
    assert ".tran" not in cleaned
    assert removed == [".tran 0 1m"]


def test_write_user_fragment_does_not_modify_source(tmp_path: Path):
    src = tmp_path / "user.cir"
    original = "* user\nVin in 0 5\n.tran 0 1m\n.end\n"
    src.write_text(original, encoding="utf-8")
    dst = tmp_path / "out" / "fragment.cir"
    removed = write_user_fragment(src, dst)
    # Source file unchanged.
    assert src.read_text(encoding="utf-8") == original
    # Fragment exists; no line is a `.tran` or `.end` directive.
    text = dst.read_text(encoding="utf-8")
    for line in text.splitlines():
        head = line.lstrip()
        if head.startswith("*"):
            continue
        assert not head.lower().startswith(".tran")
        assert not head.lower().startswith(".end")
    assert "Auto-processed copy of user.cir" in text
    assert removed == [".tran 0 1m", ".end"]


def test_strip_removes_named_source():
    src = (
        "* test\n"
        "Vin in 0 DC 24\n"
        "VinFollower in_x in_y 0\n"
        "R1 in out 1k\n"
        ".tran 0 1m\n"
    )
    cleaned, removed = strip_control_directives(src, strip_sources=["Vin"])
    # Exact-name match on first token (case-insensitive); does not eat lines
    # whose refdes merely starts with "Vin" but is a different element name.
    assert "Vin in 0 DC 24" not in cleaned
    assert "VinFollower" in cleaned
    assert "R1 in out 1k" in cleaned
    assert "Vin in 0 DC 24" in removed
    assert ".tran 0 1m" in removed


def test_write_user_fragment_strips_named_source(tmp_path: Path):
    src = tmp_path / "user.cir"
    src.write_text("* user\nVin in 0 DC 24\nR1 in 0 1k\n", encoding="utf-8")
    dst = tmp_path / "out" / "fragment.cir"
    removed = write_user_fragment(src, dst, strip_sources=["Vin"])
    text = dst.read_text(encoding="utf-8")
    # Strip header comments — the removed line appears as a "Removed directives:" annotation.
    body_lines = [ln for ln in text.splitlines() if not ln.lstrip().startswith("*")]
    assert all("Vin" not in ln for ln in body_lines), body_lines
    assert any("R1 in 0 1k" in ln for ln in body_lines)
    assert "Vin in 0 DC 24" in removed
