"""Corner-sweep variant engine for the testbench.

MVP strategy:
- one ``baseline`` variant — all parasitics at ``typ``,
- for each parasitic, two variants: ``<id>=min`` and ``<id>=max``
  (the rest stay at ``typ``).

That gives ``1 + 2N`` variants where N is the number of parasitics.
For the default six parasitics this is 13 variants — a sweet spot
between observability and simulation cost. The full 3^N cross-product
is intentionally skipped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import ClassVar, Iterable

from emc_assistant.parasitics.model import ParasiticEstimate


@dataclass
class Variant:
    __test__: ClassVar[bool] = False  # not a pytest test class
    label: str
    description: str
    overrides: dict[str, str] = field(default_factory=dict)
    """Map ``parasitic.id`` -> ``'min'|'typ'|'max'``."""
    parasitics: list[ParasiticEstimate] = field(default_factory=list)

    def short_id(self) -> str:
        """Path- and SPICE-safe form of the label."""
        return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in self.label)


def enumerate_corner_variants(
    parasitics: Iterable[ParasiticEstimate],
    *,
    sweep_only_types: tuple[str, ...] = ("R", "L", "C"),
) -> list[Variant]:
    """Enumerate variants: baseline + per-parasitic min/max.

    ``sweep_only_types`` limits the sweep to certain parasitic types
    (default R/L/C — skips e.g. the diagnostic ``frequency`` from
    ``lc_resonance``).
    """
    base_list = list(parasitics)
    baseline = Variant(
        label="baseline",
        description="All parasitics held at their typical value.",
        overrides={p.id: "typ" for p in base_list},
        parasitics=list(base_list),
    )
    variants: list[Variant] = [baseline]
    for p in base_list:
        if p.parasitic_type not in sweep_only_types:
            continue
        for corner in ("min", "max"):
            modified = [p.at_corner(corner) if q.id == p.id else q for q in base_list]
            variants.append(
                Variant(
                    label=f"{p.id}-{corner}",
                    description=f"Parasitic {p.id} set to {corner}; others at typ.",
                    overrides={**baseline.overrides, p.id: corner},
                    parasitics=modified,
                )
            )
    return variants
