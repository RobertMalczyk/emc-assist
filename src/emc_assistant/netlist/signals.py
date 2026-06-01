"""User-signal auto-detection from .asc / .cir (M2.10.1).

Builds a candidate :class:`SignalMap` from:

1. Explicit ``FLAG`` labels in a LTspice ``.asc`` file (highest priority —
   the user already named these nets).
2. SPICE net names in the ``.cir`` fragment, filtered by heuristic patterns
   (``out``, ``vin``, ``v_5v``, etc.).
3. Optional user-declared overrides from ``user_context.json``
   ``signals[]`` (top priority — passes through unchanged).

The result is a list of candidate signals with provisional names. The
CLI then asks the user to confirm or edit, and writes the final list
back to ``user_context.json`` and the audit ``generated/signals.json``.

Currents and powers are conservative: the auto-detect does not invent
expressions for them in the MVP. The LLM-driven ``signal_map_agent``
(M2.10.1) refines voltages and proposes currents when supported by the
retrieved knowledge snippets.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from emc_assistant.netlist.parser import parse_cir
from emc_assistant.netlist.topology import _GROUND_TOKENS, build_topology_report


_FLAG_LINE_RE = re.compile(r"^FLAG\s+-?\d+\s+-?\d+\s+(?P<label>\S+)\s*$")


_VOLTAGE_HINT_RE = re.compile(
    r"^(?:v|V)("
    r"out|in|bus|cc|dd|ee|ss|aux|rail|core|sw|drv|gate|sense|ref|fb|comp"
    r"|5v|3v3|12v|24v|1v8|2v5|0v9"
    r")(?:_[A-Za-z0-9]+)?$|"
    r"^(?:V_|VI_|VS_)[A-Za-z0-9_]+$|"
    r"^(?:n_)?(out|outp|outn|vin|vout|vbus)$",
    re.IGNORECASE,
)
"""Net names that smell like voltage rails. Patterns:

- `Vout`, `vin`, `Vbus`, `Vcc`, `V5V`, `V3V3` (rail names with V prefix).
- `V_anything`, `VI_anything`, `VS_anything` (vendor convention).
- `out`, `vin`, `n_out`, `outp`, `outn` (common bare names).
"""


@dataclass
class TargetBand:
    """Optional expected operating band for a signal."""

    min: float | None = None
    typ: float | None = None
    max: float | None = None

    def to_dict(self) -> dict:
        out: dict = {}
        for k in ("min", "typ", "max"):
            v = getattr(self, k)
            if v is not None:
                out[k] = float(v)
        return out


@dataclass
class Signal:
    """One tracked user-meaningful signal."""

    name: str
    kind: str  # voltage | current | power | temperature
    expr: str
    unit: str = ""
    target_band: TargetBand | None = None
    source: str = "auto"  # auto | user | llm
    confidence: float = 0.5
    rationale: str = ""
    from_label: str = ""

    def to_schema_dict(self) -> dict:
        out: dict = {
            "name": self.name,
            "kind": self.kind,
            "expr": self.expr,
            "source": self.source,
        }
        if self.unit:
            out["unit"] = self.unit
        if self.target_band is not None:
            band = self.target_band.to_dict()
            if band:
                out["target_band"] = band
        if self.confidence:
            out["confidence"] = float(self.confidence)
        if self.rationale:
            out["rationale"] = self.rationale
        if self.from_label:
            out["from_label"] = self.from_label
        return out


def _normalise_name(label: str) -> str:
    """Turn an ASC label or net name into a SPICE-identifier-friendly Pythonic name.

    ``VIN`` → ``Vin``. ``vout`` → ``Vout``. ``V_5V`` → ``V_5V``. ``out`` → ``Vout``.
    """
    label = label.strip()
    if not label:
        return ""
    # Already starts with V/I/P prefix and a capital letter? keep as-is canonicalised.
    if re.fullmatch(r"[VIPT]_[A-Za-z0-9_]+", label):
        return label
    upper = label.upper()
    if upper in {"VIN", "VOUT", "VBUS", "VCC", "VDD", "VEE", "VSS"}:
        return upper[:1] + upper[1:].lower()  # Vin, Vout, Vbus, Vcc, Vdd, Vee, Vss
    if upper.startswith("V") and "_" in label:
        return label  # V_5V, VI_AUX preserved
    if upper.startswith("V") and re.fullmatch(r"V[0-9].*", upper):
        return upper  # V5V, V3V3 preserved
    # Bare net like 'out' → 'Vout'; 'in' → 'Vin'
    if upper in {"OUT", "OUTP", "OUTN", "IN", "INP", "INN", "BUS", "RAIL"}:
        return "V" + label[:1].lower() + label[1:].lower()
    if upper.startswith("N_"):
        rest = label[2:]
        if rest.lower() in {"out", "in", "vin", "vout", "bus", "rail"}:
            return _normalise_name(rest)
    return label


def parse_asc_flags(asc_path: Path) -> dict[str, str]:
    """Return a map of net_label -> normalised user-name from a LTspice .asc.

    Skips ground labels (``0``, ``GND``) and duplicates. Reads the file
    as UTF-16 LE first (LTspice on Windows), falls back to UTF-8.
    """
    if not asc_path.is_file():
        return {}
    raw: str = ""
    # LTspice on Windows writes .asc as latin-1 / cp1252 (µ symbol etc.)
    # with no BOM. Older XVII files were UTF-16 LE. Try several encodings;
    # we only need ASCII-clean FLAG lines for label extraction.
    for enc in ("utf-8", "latin-1", "cp1252", "utf-16-le", "utf-16"):
        try:
            raw = asc_path.read_text(encoding=enc, errors="replace")
            break
        except (UnicodeError, ValueError):
            continue
    if not raw:
        return {}
    out: dict[str, str] = {}
    for line in raw.splitlines():
        m = _FLAG_LINE_RE.match(line.strip())
        if not m:
            continue
        label = m.group("label")
        if label in _GROUND_TOKENS:
            continue
        if label not in out:
            out[label] = _normalise_name(label)
    return out


def _looks_like_voltage_net(net: str) -> bool:
    if net in _GROUND_TOKENS:
        return False
    return bool(_VOLTAGE_HINT_RE.match(net))


def detect_signals_from_cir(cir_path: Path) -> list[Signal]:
    """Heuristic deduction from a .cir fragment.

    Walks the user fragment's nets. For each net that matches the
    voltage-hint pattern, emit a Signal of kind=voltage with
    ``expr=V(<net>)``. No currents are emitted from a .cir alone in the
    MVP (which element to probe is ambiguous).
    """
    if not cir_path.is_file():
        return []
    parsed = parse_cir(cir_path)
    topo = build_topology_report(parsed)
    candidates: list[Signal] = []
    seen: set[str] = set()
    for net_usage in topo.nets:
        net = net_usage.name
        if net in seen:
            continue
        seen.add(net)
        if _looks_like_voltage_net(net):
            name = _normalise_name(net)
            candidates.append(
                Signal(
                    name=name,
                    kind="voltage",
                    expr=f"V({net})",
                    unit="V",
                    source="auto",
                    confidence=0.65 if name != net else 0.5,
                    rationale=f"net name matches voltage-rail heuristic; alias from `{net}`",
                )
            )
    return candidates


def merge_signal_maps(
    asc_signals: list[Signal],
    cir_signals: list[Signal],
    user_signals: list[Signal],
) -> list[Signal]:
    """Combine three sources with priority user > asc > cir.

    Dedups by ``expr`` (the SPICE probe string). Earlier entries win.
    Result preserves insertion order.
    """
    out: list[Signal] = []
    seen_exprs: set[str] = set()
    seen_names: set[str] = set()

    def _add(sig: Signal) -> None:
        if sig.expr in seen_exprs:
            return
        # If a different signal already claimed this name, suffix this one.
        name = sig.name
        i = 2
        while name in seen_names:
            name = f"{sig.name}_{i}"
            i += 1
        sig.name = name
        out.append(sig)
        seen_exprs.add(sig.expr)
        seen_names.add(name)

    for sig in user_signals:
        _add(sig)
    for sig in asc_signals:
        _add(sig)
    for sig in cir_signals:
        _add(sig)
    return out


def detect_signals(
    *,
    asc_path: Path | None,
    cir_path: Path | None,
    user_signals: Iterable[Signal] = (),
) -> list[Signal]:
    """Top-level deduction: combine .asc, .cir, and user-declared signals."""
    asc_signals: list[Signal] = []
    if asc_path is not None and asc_path.is_file():
        label_map = parse_asc_flags(asc_path)
        for raw_label, normalised in label_map.items():
            asc_signals.append(
                Signal(
                    name=normalised,
                    kind="voltage",
                    expr=f"V({raw_label})",
                    unit="V",
                    source="auto",
                    confidence=0.85,
                    rationale=f"LTspice .asc FLAG label `{raw_label}`",
                    from_label=raw_label,
                )
            )
    cir_signals: list[Signal] = []
    if cir_path is not None:
        cir_signals = detect_signals_from_cir(cir_path)
    return merge_signal_maps(asc_signals, cir_signals, list(user_signals))


def signals_from_user_context(user_context: dict) -> list[Signal]:
    """Read ``user_context.json``'s ``signals`` block, if present."""
    raw = (user_context or {}).get("signals")
    if not isinstance(raw, list):
        return []
    out: list[Signal] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            band_raw = item.get("target_band")
            band = None
            if isinstance(band_raw, dict) and band_raw:
                band = TargetBand(
                    min=band_raw.get("min"),
                    typ=band_raw.get("typ"),
                    max=band_raw.get("max"),
                )
            out.append(
                Signal(
                    name=str(item["name"]),
                    kind=str(item.get("kind", "voltage")),
                    expr=str(item["expr"]),
                    unit=str(item.get("unit", "")),
                    target_band=band,
                    source="user",
                    confidence=1.0,
                    rationale=str(item.get("rationale", "user-declared in user_context.json")),
                    from_label=str(item.get("from_label", "")),
                )
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out
