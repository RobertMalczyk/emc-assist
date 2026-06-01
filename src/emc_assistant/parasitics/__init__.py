"""First-order PCB parasitic calculators.

Every result is returned as a ``ParasiticEstimate`` with explicit
min/typ/max bands, listed assumptions, and source IDs. We never emit a
single "certain" value — parasitics are always treated as ranges.
"""

from emc_assistant.parasitics.model import ParasiticEstimate, ValueBand
from emc_assistant.parasitics.calculators import (
    trace_resistance,
    trace_inductance_no_plane,
    trace_capacitance_from_z0_delay,
    polygon_plane_capacitance,
    via_inductance,
    lc_resonance,
)

__all__ = [
    "ParasiticEstimate",
    "ValueBand",
    "trace_resistance",
    "trace_inductance_no_plane",
    "trace_capacitance_from_z0_delay",
    "polygon_plane_capacitance",
    "via_inductance",
    "lc_resonance",
]
