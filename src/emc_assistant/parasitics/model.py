"""Common result model for parasitic calculators."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal


Confidence = Literal["low", "medium", "high"]
Structure = Literal[
    "trace", "via", "plane_pair", "polygon", "cable", "capacitor_mount", "loop", "coupling"
]
ParasiticType = Literal["R", "L", "C", "G", "K", "RLC", "transmission_line", "frequency"]


@dataclass(frozen=True)
class ValueBand:
    """min/typ/max value band."""

    min: float
    typ: float
    max: float

    def __post_init__(self) -> None:
        if not (self.min <= self.typ <= self.max):
            raise ValueError(
                f"Invalid ValueBand: min={self.min}, typ={self.typ}, max={self.max}"
            )


@dataclass
class ParasiticEstimate:
    """Parasitic calculator result; matches ``parasitic_model.schema.json``."""

    id: str
    structure: Structure
    parasitic_type: ParasiticType
    band: ValueBand
    unit: str
    confidence: Confidence
    assumptions: list[str] = field(default_factory=list)
    formula: str = ""
    inputs: dict = field(default_factory=dict)
    source_ids: list[str] = field(default_factory=list)
    ltspice_representation: str = ""
    notes: str = ""

    @property
    def value(self) -> float:
        return self.band.typ

    @property
    def min_value(self) -> float:
        return self.band.min

    @property
    def max_value(self) -> float:
        return self.band.max

    def at_corner(self, corner: str) -> "ParasiticEstimate":
        """Return a copy with ``band.typ`` shifted to the chosen corner.

        ``min`` and ``max`` are preserved; the sweep only affects the
        default value emitted by the SPICE fragment for this variant.
        """
        if corner not in {"min", "typ", "max"}:
            raise ValueError(f"Invalid corner: {corner!r} (expected min|typ|max)")
        if corner == "typ":
            return self
        target = self.min_value if corner == "min" else self.max_value
        new_band = ValueBand(
            min=min(self.min_value, target),
            typ=target,
            max=max(self.max_value, target),
        )
        return ParasiticEstimate(
            id=self.id,
            structure=self.structure,
            parasitic_type=self.parasitic_type,
            band=new_band,
            unit=self.unit,
            confidence=self.confidence,
            assumptions=list(self.assumptions) + [f"Variant: typ={corner} corner"],
            formula=self.formula,
            inputs=dict(self.inputs),
            source_ids=list(self.source_ids),
            ltspice_representation=self.ltspice_representation,
            notes=self.notes,
        )

    def to_schema_dict(self) -> dict:
        return {
            "id": self.id,
            "structure": self.structure,
            "parasitic_type": self.parasitic_type,
            "value": self.value,
            "unit": self.unit,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "confidence": self.confidence,
            "assumptions": list(self.assumptions),
            "formula": self.formula,
            "inputs": dict(self.inputs),
            "source_ids": list(self.source_ids),
            "ltspice_representation": self.ltspice_representation,
        }
