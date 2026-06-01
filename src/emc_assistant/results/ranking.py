"""Rank variants by a chosen metric.

Input: a sequence of ``(label, metrics_dict)`` pairs.
Output: a list sorted by the chosen metric with ``delta`` and
``delta_pct`` against the ``baseline`` entry. The module is
deterministic — it does not invoke LTspice; it works on dicts loaded
from ``simulation_run.json``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence


@dataclass
class RankedVariant:
    label: str
    metric: float
    delta: float | None
    delta_pct: float | None
    rank: int


def rank_variants(
    metrics: Sequence[tuple[str, dict[str, float]]],
    *,
    metric_key: str,
    lower_is_better: bool = True,
    baseline_label: str = "baseline",
) -> list[RankedVariant]:
    """Rank by ``metric_key``.

    Variants missing ``metric_key`` in their metrics dict are skipped
    (only comparable entries are returned).
    """
    filtered: list[tuple[str, float]] = []
    for label, m in metrics:
        if metric_key in m:
            try:
                filtered.append((label, float(m[metric_key])))
            except (TypeError, ValueError):
                continue
    if not filtered:
        return []

    baseline_value: float | None = None
    for label, value in filtered:
        if label == baseline_label:
            baseline_value = value
            break

    ordered = sorted(filtered, key=lambda kv: kv[1], reverse=not lower_is_better)
    ranked: list[RankedVariant] = []
    for rank, (label, value) in enumerate(ordered, start=1):
        if baseline_value is None or label == baseline_label:
            delta = 0.0 if label == baseline_label else None
            delta_pct = 0.0 if label == baseline_label else None
        else:
            delta = value - baseline_value
            delta_pct = (delta / baseline_value) * 100.0 if baseline_value != 0 else None
        ranked.append(
            RankedVariant(
                label=label,
                metric=value,
                delta=delta,
                delta_pct=delta_pct,
                rank=rank,
            )
        )
    return ranked
