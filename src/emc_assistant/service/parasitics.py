"""Parasitic-estimation service operations: bulk estimate + per-net."""

from __future__ import annotations

import json
import os
import uuid as _uuid
from dataclasses import dataclass
from pathlib import Path

from emc_assistant.logging_setup import get_logger
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.schemas import (
    SchemaValidationError,
    require_all_valid,
    require_valid,
)
from emc_assistant.service.context import (
    build_default_parasitics,
    build_problem_context,
    load_user_context,
)
from emc_assistant.service.project import require_project
from emc_assistant.service.results import ServiceError

_log = get_logger("parasitics")


@dataclass
class EstimateResult:
    output_path: Path
    parasitics: list[ParasiticEstimate]


def estimate_parasitics(project_root) -> EstimateResult:
    """Estimate the default MVP parasitics and write
    ``generated/parasitics.json``."""
    _config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    parasitics = build_default_parasitics(user_context)
    out = [p.to_schema_dict() for p in parasitics]
    try:
        require_all_valid("parasitic_model.schema.json", out)
    except SchemaValidationError as exc:
        raise ServiceError(
            f"Estimated parasitics violate the schema:\n{exc}"
        ) from exc
    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    out_path = layout.generated_dir / "parasitics.json"
    out_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    _log.info(f"Wrote {len(out)} parasitics to {out_path}")
    return EstimateResult(output_path=out_path, parasitics=parasitics)


def _resolve_ground_label(user_context: dict) -> str:
    """The DUT-side return label the composed testbench will use.

    Dual-LISN composition renames the user's local ``0`` to ``DUT_GND``
    (the real ``0`` then exists only on the LISN side); single-LISN keeps
    the configured return net (default ``0``). Mirrors
    :func:`emc_assistant.service.resolve.resolve_shunt_plan` so the
    parasitic-selection screen shows the same net names the simulation
    runs on.
    """
    wiring = (user_context or {}).get("testbench_wiring")
    if isinstance(wiring, dict):
        mode = str(wiring.get("lisn_mode", "dual")).strip().lower() or "dual"
        if mode != "dual":
            return str(wiring.get("dut_return_net", "0") or "0")
    return "DUT_GND"


@dataclass
class PerNetResult:
    topology_path: Path
    per_net_path: Path
    net_count: int
    estimate_count: int
    roles: dict[str, int]
    injectable_count: int


def estimate_per_net(project_root) -> PerNetResult:
    """Per-net parasitic estimation (M2.10.4) as a first-class artifact.

    Analyses the netlist topology and writes ``generated/topology.json``
    and ``generated/parasitics_per_net.json`` — without composing a
    testbench. This is the artifact the UI's parasitic-selection screen
    reads on first open.
    """
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)

    netlist_rel = config.inputs.get("netlist_path", "")
    if not netlist_rel:
        raise ServiceError(
            "No inputs.netlist_path set in project.yaml — nothing to analyse."
        )
    raw = (layout.root / netlist_rel).resolve()
    if not raw.is_file():
        raise ServiceError(f"Netlist not found: {raw}")

    cir = raw
    if raw.suffix.lower() == ".asc":
        from emc_assistant.netlist.asc_converter import (
            AscConversionError,
            convert_asc_to_cir,
        )

        ltx = str(config.ltspice.get("executable_path") or "") or os.environ.get(
            "LTSPICE_PATH", ""
        )
        try:
            cir = convert_asc_to_cir(raw, ltspice_exe=ltx or None).cir_path
        except AscConversionError as exc:
            raise ServiceError(f"asc-to-cir conversion failed: {exc}") from exc

    from emc_assistant.netlist.fragment import rename_ground_node
    from emc_assistant.netlist.parser import _read_cir_text, parse_cir
    from emc_assistant.netlist.topology import build_topology_report
    from emc_assistant.parasitics.per_net import estimate_all_nets

    # Show the same net names the simulation runs on: dual-LISN composition
    # lifts the user's local `0` to DUT_GND (the DUT-side virtual ground),
    # leaving `0` only on the LISN side — which is not part of the user
    # fragment shown on this screen. Mirrors resolve.resolve_shunt_plan.
    ground_label = _resolve_ground_label(user_context)
    text = _read_cir_text(Path(cir))
    if ground_label != "0":
        text = rename_ground_node(text, old_node="0", new_node=ground_label)
    topology = build_topology_report(parse_cir(text))
    estimates = estimate_all_nets(topology)

    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    topo_path = layout.generated_dir / "topology.json"
    topo_path.write_text(
        json.dumps(topology.to_schema_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    per_net_path = layout.generated_dir / "parasitics_per_net.json"
    per_net_path.write_text(
        json.dumps([e.to_dict() for e in estimates], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    by_role: dict[str, int] = {}
    for e in estimates:
        by_role[e.role] = by_role.get(e.role, 0) + 1
    injectable = sum(1 for e in estimates if e.injectable)
    _log.info(f"Wrote {topo_path}  ({len(topology.nets)} nets)")
    _log.info(f"Wrote {per_net_path}  ({len(estimates)} per-net estimates)")
    _log.info(
        f"  roles: {', '.join(f'{k}:{v}' for k, v in sorted(by_role.items()))}"
    )
    _log.info(f"  injectable (clean 2-element) nets: {injectable}")
    return PerNetResult(
        topology_path=topo_path,
        per_net_path=per_net_path,
        net_count=len(topology.nets),
        estimate_count=len(estimates),
        roles=by_role,
        injectable_count=injectable,
    )


@dataclass
class SuggestNegligibleResult:
    dropped: list   # [{"net", "kind", "reason"}]
    considered: int


def suggest_negligible(project_root, options) -> SuggestNegligibleResult:
    """Run the M2.10.7 LLM negligibility screen on the project's per-net
    parasitic plan and report which nets it judges negligible — without
    composing the testbench. Standalone backend for the parasitic-selection
    screen's "AI: suggest negligible" button.

    Requires an active LLM (cloud LLM enabled + a resolvable key); raises
    ``ServiceError`` otherwise so the UI can prompt the user to turn it on.
    """
    from emc_assistant.service import resolve

    if not resolve.llm_enabled(options):
        raise ServiceError(
            "Cloud LLM is off (or no API key resolved) — enable cloud LLM in "
            "Settings and add an API key to run the negligibility screen."
        )
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    parasitics = build_default_parasitics(user_context)
    wiring, strip_sources = resolve.resolve_wiring(
        user_context, options, layout=layout, config=config
    )
    netlist_rel = config.inputs.get("netlist_path", "")
    user_netlist_raw = (layout.root / netlist_rel).resolve() if netlist_rel else None
    rename_ground = "DUT_GND" if (
        wiring is not None and getattr(wiring, "lisn_mode", "dual") == "dual"
    ) else None
    # inject_series=False — we only want the screen's verdicts, not a fragment
    # edit. prepare_user_fragment_with_splices runs the screen on the series
    # plan internally and returns its drops; we run it on the shunt plan here.
    fragment, series_nets, series_plan, series_dropped = (
        resolve.prepare_user_fragment_with_splices(
            layout, user_netlist_raw, strip_sources=strip_sources, config=config,
            rename_ground_to=rename_ground, user_context=user_context,
            options=options, inject_series=False,
        )
    )
    injection_plan = resolve.resolve_parasitics_injection(
        user_context, options, parasitics=parasitics, user_fragment_path=fragment,
    )
    shunt_plan = resolve.resolve_shunt_plan(
        user_context, options, user_fragment_path=fragment,
        injection_plan=injection_plan, series_nets=tuple(series_nets),
    )
    shunt_dropped: list = []
    if shunt_plan:
        _kept, shunt_dropped = resolve.filter_negligible(
            shunt_plan, "shunt", options=options, layout=layout,
            config=config, user_context=user_context,
        )
    dropped = list(series_dropped) + list(shunt_dropped)
    considered = len(series_plan) + len(shunt_plan)
    _log.info(
        f"Negligibility screen: {len(dropped)} of {considered} net(s) "
        "judged negligible."
    )
    return SuggestNegligibleResult(dropped=dropped, considered=considered)


# ---- M2.17: LLM/RAG value re-evaluation -------------------------------------


def _build_per_net_estimates(config, layout, user_context):
    """``(topology, [NetParasitics])`` of deterministic priors for every net.

    The analysis half of :func:`estimate_per_net` (cir/asc → topology →
    rule-of-thumb estimates), without writing any artifact — reused by the
    re-evaluation pass."""
    import os

    from emc_assistant.netlist.fragment import rename_ground_node
    from emc_assistant.netlist.parser import _read_cir_text, parse_cir
    from emc_assistant.netlist.topology import build_topology_report
    from emc_assistant.parasitics.per_net import estimate_all_nets

    netlist_rel = config.inputs.get("netlist_path", "")
    if not netlist_rel:
        raise ServiceError(
            "No inputs.netlist_path set in project.yaml — nothing to analyse."
        )
    raw = (layout.root / netlist_rel).resolve()
    if not raw.is_file():
        raise ServiceError(f"Netlist not found: {raw}")
    cir = raw
    if raw.suffix.lower() == ".asc":
        from emc_assistant.netlist.asc_converter import (
            AscConversionError,
            convert_asc_to_cir,
        )

        ltx = str(config.ltspice.get("executable_path") or "") or os.environ.get(
            "LTSPICE_PATH", ""
        )
        try:
            cir = convert_asc_to_cir(raw, ltspice_exe=ltx or None).cir_path
        except AscConversionError as exc:
            raise ServiceError(f"asc-to-cir conversion failed: {exc}") from exc
    ground_label = _resolve_ground_label(user_context)
    text = _read_cir_text(Path(cir))
    if ground_label != "0":
        text = rename_ground_node(text, old_node="0", new_node=ground_label)
    topology = build_topology_report(parse_cir(text))
    return topology, estimate_all_nets(topology)


@dataclass
class ReevaluateResult:
    audit_path: Path
    considered: int       # non-ground nets sent to the LLM
    refined_count: int    # nets the LLM returned a usable band for
    cited_count: int      # of those, how many carry >=1 citation
    cost_usd: float
    applied: int          # nets persisted as user overrides (apply=True only)


def reevaluate_parasitics(project_root, options, *, apply: bool = False) -> ReevaluateResult:
    """M2.17 — LLM/RAG re-evaluation of the per-net parasitic *values*.

    For every non-ground net: retrieve PCB-parasitics snippets (RAG,
    redacted), then one batched LLM call refines the deterministic
    rule-of-thumb bands into citation-backed min/typ/max *proposals*. The
    deterministic prior stays the fallback — any net the LLM errors on,
    omits, or returns an unusable band for keeps its prior verbatim.

    Always writes the full audit ``generated/parasitics_reevaluated.json``
    (prior + refined min/typ/max, typ delta, confidence, rationale,
    citations, provenance). With ``apply=True`` it *also* persists only the
    refined **typ** values as explicit user overrides
    (``user_context.parasitics.per_net``) — the bands stay in the audit
    only, never silently applied.
    """
    from emc_assistant.service import resolve
    from emc_assistant.agents.parasitics_agent import ParasiticsAgent
    from emc_assistant.knowledge.retrieve import retrieve_for_keywords

    if not resolve.llm_enabled(options):
        raise ServiceError(
            "Cloud LLM is off (or no API key resolved) — enable cloud LLM in "
            "Settings and add an API key to re-evaluate parasitic values."
        )
    config, layout = require_project(project_root)
    user_context = load_user_context(layout)
    _topology, estimates = _build_per_net_estimates(config, layout, user_context)
    targets = [e for e in estimates if e.role != "return"]  # never the reference net

    def _band(est):
        return [est.min_value, est.value, est.max_value]  # [min, typ, max]

    problem_context = build_problem_context(
        config, user_context, build_default_parasitics(user_context)
    )
    # Embedder for RAG retrieval (mirrors service.report): stub in tests, real
    # otherwise, keyword-fallback if the embeddings extra is absent.
    embedder = options.stub_embedder
    if embedder is None and options.stub_assistant is not None:
        from emc_assistant.knowledge.embedder import EmbedderStub

        embedder = EmbedderStub()
    if embedder is None:
        try:
            from emc_assistant.knowledge.embedder import make_embedder

            embedder = make_embedder()
        except Exception as exc:  # noqa: BLE001 — [embeddings] extra may be absent
            _log.warning(
                f"[parasitics] real embedder unavailable ({type(exc).__name__}); "
                "RAG retrieval will use the keyword fallback."
            )
            embedder = None

    candidates = []
    for e in targets:
        snippets = retrieve_for_keywords(
            [e.role, "pcb trace parasitic", "resistance inductance capacitance",
             *list(e.components)],
            problem_context, embedder=embedder, k=4,
        )
        candidates.append({
            "net": e.net,
            "role": e.role,
            "prior": {
                "r_band": _band(e.rlc.resistance),
                "l_band": _band(e.rlc.inductance),
                "c_band": _band(e.rlc.capacitance),
            },
            "snippets": [
                {"rule_id": s.rule_id, "source_id": s.source_id,
                 "summary": s.summary, "excerpt": s.excerpt}
                for s in snippets
            ],
        })

    run_id = f"par-reeval-{_uuid.uuid4().hex[:8]}"
    assistant, _log_path = resolve.make_assistant(options, layout=layout, run_id=run_id)
    pc = problem_context
    ctx_line = (
        f"Circuit: {pc.topology or 'DC/DC converter'}. Conducted-EMI band "
        f"{int(pc.frequency_range_min_hz or 150_000)}-"
        f"{int(pc.frequency_range_max_hz or 30_000_000)} Hz. Refine each net's "
        "R/L/C bands from the cited snippets; keep the prior when unsupported."
    )
    refined_map = ParasiticsAgent().reevaluate_values(
        candidates, assistant=assistant, context_line=ctx_line,
    )

    def _pct(refined_typ, prior_typ):
        if not prior_typ:
            return None
        return round((refined_typ - prior_typ) / prior_typ * 100.0, 1)

    audit: list[dict] = []
    overrides: dict[str, dict] = {}
    cited_count = 0
    for e in targets:
        prior = {
            "r_band": _band(e.rlc.resistance),
            "l_band": _band(e.rlc.inductance),
            "c_band": _band(e.rlc.capacitance),
        }
        ref = refined_map.get(e.net)
        if ref is None:
            entry = {
                "net": e.net, "role": e.role, "value_source": "rule_of_thumb",
                "prior": prior, "refined": None,
            }
        else:
            has_cite = bool(ref["cited_sources"])
            if has_cite:
                cited_count += 1
            entry = {
                "net": e.net, "role": e.role,
                "value_source": "llm_rag" if has_cite else "engineering_estimate",
                "prior": prior,
                "refined": {
                    "r_band": ref["r_band"], "l_band": ref["l_band"],
                    "c_band": ref["c_band"], "confidence": ref["confidence"],
                    "rationale": ref["rationale"], "cited_sources": ref["cited_sources"],
                },
                "typ_delta_pct": {
                    "r": _pct(ref["r_band"][1], prior["r_band"][1]),
                    "l": _pct(ref["l_band"][1], prior["l_band"][1]),
                    "c": _pct(ref["c_band"][1], prior["c_band"][1]),
                },
            }
            # typ-only override (the bands stay in the audit, never auto-applied)
            overrides[e.net] = {
                "r_mohm": round(ref["r_band"][1] * 1e3, 6),
                "l_nh": round(ref["l_band"][1] * 1e9, 6),
                "c_pf": round(ref["c_band"][1] * 1e12, 6),
            }
        audit.append(entry)

    audit_obj = {"run_id": run_id, "nets": audit}
    try:
        require_valid("parasitics_reevaluated.schema.json", audit_obj)
    except SchemaValidationError as exc:
        raise ServiceError(
            f"Re-evaluation audit violates the schema:\n{exc}"
        ) from exc
    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    audit_path = layout.generated_dir / "parasitics_reevaluated.json"
    audit_path.write_text(
        json.dumps(audit_obj, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    applied = (
        _persist_typ_overrides(project_root, user_context, overrides)
        if apply and overrides else 0
    )

    tracker = getattr(assistant, "budget_tracker", None)
    cost = float(getattr(tracker, "spent_usd", 0.0) or 0.0)
    _log.info(
        f"[parasitics] value re-evaluation: {len(refined_map)}/{len(targets)} net(s) "
        f"refined ({cited_count} cited), cost ~${cost:.4f}; audit → {audit_path.name}"
        + (f"; applied {applied} typ override(s)" if apply else "")
    )
    return ReevaluateResult(
        audit_path=audit_path, considered=len(targets),
        refined_count=len(refined_map), cited_count=cited_count,
        cost_usd=cost, applied=applied,
    )


def _persist_typ_overrides(project_root, user_context: dict, overrides: dict) -> int:
    """Merge ``{net: {r_mohm, l_nh, c_pf}}`` typ values into
    ``user_context.parasitics.per_net`` and save. Preserves any existing
    per-net keys (e.g. a ``skip`` flag). Returns the number of nets written."""
    from emc_assistant.service.context import save_user_context

    uc = dict(user_context)
    para = dict(uc.get("parasitics") or {})
    per_net = dict(para.get("per_net") or {})
    for net, vals in overrides.items():
        merged = dict(per_net.get(net) or {})
        merged.update(vals)  # typ-only; never bands
        per_net[net] = merged
    para["per_net"] = per_net
    uc["parasitics"] = para
    save_user_context(project_root, uc)
    return len(overrides)


@dataclass
class ApplyReevalResult:
    applied: int


def apply_reevaluated_parasitics(project_root) -> ApplyReevalResult:
    """Persist the refined **typ** values from the last re-evaluation audit
    (``generated/parasitics_reevaluated.json``) as user overrides — the
    "accept" step after a preview re-evaluation. No LLM call: it reads the
    audit's already-computed refined bands and writes only their typ value
    into ``user_context.parasitics.per_net``."""
    _config, layout = require_project(project_root)
    audit_path = layout.generated_dir / "parasitics_reevaluated.json"
    if not audit_path.is_file():
        raise ServiceError(
            "No re-evaluation audit found — run a parasitics re-evaluation first."
        )
    try:
        data = json.loads(audit_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ServiceError(f"Could not read the re-evaluation audit: {exc}") from exc
    overrides: dict[str, dict] = {}
    for n in data.get("nets", []):
        ref = n.get("refined")
        net = n.get("net")
        if not ref or not net:
            continue
        overrides[net] = {
            "r_mohm": round(ref["r_band"][1] * 1e3, 6),
            "l_nh": round(ref["l_band"][1] * 1e9, 6),
            "c_pf": round(ref["c_band"][1] * 1e12, 6),
        }
    if not overrides:
        return ApplyReevalResult(applied=0)
    applied = _persist_typ_overrides(project_root, load_user_context(layout), overrides)
    _log.info(
        f"[parasitics] applied {applied} re-evaluated typ override(s) from the audit."
    )
    return ApplyReevalResult(applied=applied)
