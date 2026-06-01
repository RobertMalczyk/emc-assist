"""Waveform-analyzer support service (M2.18).

Backs the Results screen's two-panel time-domain analyzer: which trace to
plot in the comparison subplot. Returns a fixed default (the load current)
plus four further relevant traces, deduced by the LLM when one is
configured and by a topology-aware heuristic otherwise. Cached to
``results/waveform_traces.json`` (newer-than-raw reuse) so the paid LLM
deduction runs at most once per run.
"""

from __future__ import annotations

import json
import uuid as _uuid
from pathlib import Path

from emc_assistant.logging_setup import get_logger
from emc_assistant.service.context import build_problem_context, load_user_context
from emc_assistant.service.project import require_project

_log = get_logger("waveform")


def _primary_trace(available: list[str], kinds: dict[str, str]) -> str:
    """The top-panel trace — the measured LISN voltage. Mirrors
    :func:`results.metrics.pick_default_trace`."""
    lower = {t.lower(): t for t in available}
    for cand in ("v(meas)", "v(meas_lisn)", "v(out)", "v(vout)"):
        if cand in lower:
            return lower[cand]
    for t in available:
        if (kinds.get(t, "") or "").lower() == "voltage":
            return t
    return available[0] if available else "V(meas)"


def _safe_topology(config, layout, user_context):
    """Best-effort topology for the LLM/heuristic; ``None`` on any trouble.

    Skips ``.asc`` conversion (too costly for a UI aid) — the heuristic
    still works from the trace names alone."""
    try:
        netlist_rel = config.inputs.get("netlist_path", "") if config is not None else ""
        if not netlist_rel:
            return None
        raw = (layout.root / netlist_rel).resolve()
        if not raw.is_file() or raw.suffix.lower() == ".asc":
            return None
        from emc_assistant.netlist.topology import analyse_fragment

        return analyse_fragment(raw)
    except Exception:  # noqa: BLE001 — topology is optional context
        return None


def suggest_waveform_traces(project_root, options=None) -> dict:
    """Resolve the comparison-subplot trace choices for the Results screen.

    Returns ``{available, primary, default, suggestions[], options[],
    llm_generated}`` or ``{available: False, note}`` before a local-run.
    Never raises for the UI (degrades to ``available: False``)."""
    config, layout = require_project(project_root)
    raw_path = layout.generated_dir / "testbench.raw"
    cache = layout.results_dir / "waveform_traces.json"
    if not raw_path.is_file():
        return {"available": False, "note": "no testbench.raw — run in local-run mode"}
    if cache.is_file() and cache.stat().st_mtime >= raw_path.stat().st_mtime:
        try:
            return json.loads(cache.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            pass

    from emc_assistant.service.raw import inspect_raw

    info = inspect_raw(raw_path)
    available = [t.name for t in info.traces if t.kind.lower() != "time"]
    kinds = {t.name: t.kind for t in info.traces}
    if not available:
        return {"available": False, "note": "no plottable traces in testbench.raw"}

    user_context = load_user_context(layout)
    problem_context = build_problem_context(config, user_context, [])
    topology = _safe_topology(config, layout, user_context)
    signals = user_context.get("signals") if isinstance(user_context, dict) else None
    primary = _primary_trace(available, kinds)

    assistant = None
    if options is not None:
        from emc_assistant.service import resolve

        if resolve.llm_enabled(options):
            try:
                assistant, _ = resolve.make_assistant(
                    options, layout=layout, run_id=f"wave-{_uuid.uuid4().hex[:8]}"
                )
            except Exception as exc:  # noqa: BLE001 — fall back to the heuristic
                _log.warning(f"[waveform] LLM unavailable ({exc}); using the heuristic.")

    from emc_assistant.agents.waveform_trace_agent import WaveformTraceAgent

    result = WaveformTraceAgent().suggest(
        available_traces=available,
        kinds=kinds,
        primary_trace=primary,
        topology=topology,
        problem_context=problem_context,
        signals=signals,
        assistant=assistant,
    )
    out = {"available": True, "primary": primary, **result.to_dict()}
    try:
        layout.results_dir.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass
    _log.info(
        f"[waveform] comparison default={out['default']['trace']} "
        f"+ {len(out['suggestions'])} suggestion(s) (llm={out['llm_generated']})"
    )
    return out
