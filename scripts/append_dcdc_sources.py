"""One-shot script: append SRC-071 .. SRC-075 entries to the EMC sources manifest.

These are the five DC/DC conducted-EMI PDFs the user is dropping into
knowledge/raw_sources/conducted_emissions/dcdc/ for M2.8 ingestion.
"""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "knowledge" / "seed" / "baza_wiedzy_emc_ltspice_sources.jsonl"

NEW_ENTRIES: list[dict] = [
    {
        "id": "SRC-071",
        "area": "Conducted EMI / DCDC",
        "subarea": "noise mechanisms, mitigation, practical filter workflow",
        "title": "AN-2162: Simple Success With Conducted EMI From DC-DC Converters",
        "organization": "Texas Instruments",
        "type": "Application note PDF",
        "year_or_updated": "",
        "url": "",
        "priority": 5,
        "agent_use": (
            "Core source for DC/DC conducted EMI mechanisms, mitigation strategies, "
            "and practical filter design workflow. Foundational reference for the filtering agent."
        ),
        "tags": ["conducted EMI", "DCDC", "buck", "input filter", "mitigation", "practical workflow"],
        "notes": (
            "Local PDF (public TI application note). Filename: "
            "SRC-071__an2162_simple_success_conducted_emi_dcdc.pdf in "
            "knowledge/raw_sources/conducted_emissions/dcdc/ti/."
        ),
    },
    {
        "id": "SRC-072",
        "area": "Conducted EMI / DCDC",
        "subarea": "automotive buck, conducted emission model, validation",
        "title": "SNVA886: Reduce Conducted EMI in Automotive Buck Converter Applications",
        "organization": "Texas Instruments",
        "type": "Application note PDF",
        "year_or_updated": "",
        "url": "",
        "priority": 5,
        "agent_use": (
            "Buck-specific conducted EMI: model plus filter design plus layout/shielding "
            "mitigation plus measurement validation. Directly relevant to case_001 buck demo."
        ),
        "tags": ["conducted EMI", "buck", "automotive", "CISPR-25", "measurement validation", "filter design"],
        "notes": "Local PDF (public TI app note). Filename: SRC-072__snva886_reduce_conducted_emi_automotive_buck.pdf.",
    },
    {
        "id": "SRC-073",
        "area": "Conducted EMI / DCDC",
        "subarea": "EMI filter for non-isolated DC/DC, discrete + module",
        "title": "ANS018: EMI Filter Design for Non-Isolated DC/DC Converter",
        "organization": "Würth Elektronik",
        "type": "Application note PDF",
        "year_or_updated": "",
        "url": "",
        "priority": 5,
        "agent_use": (
            "EMI filter design tailored to non-isolated DC/DC. Discrete and module-based "
            "variants. Good source for filter-agent rules in M2.9."
        ),
        "tags": ["EMI filter", "DCDC", "non-isolated", "damping", "filter selection"],
        "notes": (
            "Local PDF (public Würth app note). Filename: "
            "SRC-073__ans018_emi_filter_design_non_isolated_dcdc.pdf in "
            "knowledge/raw_sources/conducted_emissions/dcdc/wurth/."
        ),
    },
    {
        "id": "SRC-074",
        "area": "Conducted EMI / DCDC",
        "subarea": "input filter stability, pi-filter, damping, oscillation",
        "title": "SLUA929: Simple Solution for Input Filter Stability Issue in DC/DC Converters",
        "organization": "Texas Instruments",
        "type": "Application note PDF",
        "year_or_updated": "",
        "url": "",
        "priority": 5,
        "agent_use": (
            "Critical for the filter-vs-stability tradeoff. Covers pi input filters, "
            "damping techniques, oscillation risk and stability margins. Helps prevent the "
            "common failure where adding an EMI filter breaks loop stability."
        ),
        "tags": ["input filter", "stability", "damping", "pi filter", "oscillation", "DCDC"],
        "notes": "Local PDF (public TI app note). Filename: SRC-074__slua929_input_filter_stability_dcdc.pdf.",
    },
    {
        "id": "SRC-075",
        "area": "Conducted EMI / DCDC",
        "subarea": "LC input filter design, resonance, damping, EMC motivation",
        "title": "SNVA801: Analysis and Design of Input Filter for DC-DC Circuit",
        "organization": "Texas Instruments",
        "type": "Application note PDF",
        "year_or_updated": "",
        "url": "",
        "priority": 5,
        "agent_use": (
            "Deterministic LC input filter design: resonance frequency, damping factor "
            "calculation, EMC-pass motivation. Direct input to the variant engine and filter agent."
        ),
        "tags": ["input filter", "LC filter", "resonance", "damping", "DCDC", "filter design"],
        "notes": "Local PDF (public TI app note). Filename: SRC-075__snva801_input_filter_design_dcdc.pdf.",
    },
]


def main() -> int:
    text = MANIFEST.read_text(encoding="utf-8")
    existing_ids: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            existing_ids.add(json.loads(line).get("id", ""))
        except json.JSONDecodeError:
            continue

    to_append: list[dict] = []
    skipped: list[str] = []
    for entry in NEW_ENTRIES:
        sid = entry["id"]
        if sid in existing_ids:
            skipped.append(sid)
            continue
        to_append.append(entry)

    if to_append:
        with MANIFEST.open("a", encoding="utf-8") as fh:
            for entry in to_append:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        print(f"Appended {len(to_append)} entries: {[e['id'] for e in to_append]}")
    if skipped:
        print(f"Skipped (already present): {skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
