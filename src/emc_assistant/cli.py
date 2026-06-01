"""``emc-assistant`` CLI — a thin argparse adapter over the service layer.

Each ``cmd_*`` function translates an ``argparse.Namespace`` into a
:class:`~emc_assistant.service.options.CommandOptions` (or plain
parameters), calls the matching ``emc_assistant.service`` function, and
maps the result / :class:`ServiceError` to console output + an exit code.
The M3 UI calls the same service functions directly.
"""

from __future__ import annotations

import argparse
import functools
import json
import sys
from datetime import datetime, timezone

from emc_assistant import __version__, service
from emc_assistant.knowledge.embedder import DEFAULT_SENTENCE_TRANSFORMERS_MODEL
from emc_assistant.llm.openai_provider import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL
from emc_assistant.logging_setup import (
    add_run_log_file,
    configure_logging,
    get_logger,
    remove_handler,
)
from emc_assistant.project.model import load_project
from emc_assistant.service import CommandOptions, ServiceError
# Re-exported so `from emc_assistant.cli import build_project_status` keeps working.
from emc_assistant.service.project import build_project_status  # noqa: F401

_log = get_logger("cli")


def _with_run_log(prefix: str):
    """Decorator: attach a per-run ``results/log/<run-id>.jsonl`` handler for
    the duration of a long command, so the run's operational log persists.

    Best-effort — if the project cannot be resolved, the command still runs
    (and reports the configuration error itself); only the file log is
    skipped.
    """
    def decorator(fn):
        @functools.wraps(fn)
        def wrapper(args: argparse.Namespace) -> int:
            handler = None
            try:
                _config, layout, errs = load_project(args.project_root)
                if not errs:
                    log_dir = layout.results_dir / "log"
                    log_dir.mkdir(parents=True, exist_ok=True)
                    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
                    handler = add_run_log_file(log_dir / f"{prefix}-{stamp}.jsonl")
            except Exception:  # noqa: BLE001 - file logging must never abort a run
                handler = None
            try:
                return fn(args)
            finally:
                if handler is not None:
                    remove_handler(handler)
        return wrapper
    return decorator


def _fail(exc: ServiceError) -> int:
    """CLI adapter: render a service-layer failure as logged error output
    and return its exit code. An empty message means the service already
    logged the reason (e.g. an invalid-settings warning)."""
    if exc.message:
        _log.error(exc.message)
    for detail in exc.details:
        _log.error(f"  - {detail}")
    return exc.exit_code


def cmd_project_create(args: argparse.Namespace) -> int:
    try:
        result = service.project.create_project(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    _log.info(f"Created project '{result.project_id}' at {result.root}")
    _log.info(f"  wrote {result.config_path}")
    _log.info(f"  wrote {result.models_dir}/")
    _log.info(
        "  next: drop a schematic into input/ and set inputs.netlist_path "
        "in project.yaml"
    )
    return 0


def cmd_project_validate(args: argparse.Namespace) -> int:
    try:
        result = service.project.validate_project(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    _log.info(
        f"Project OK: {result.project_id} ({result.name}) v{result.version}"
    )
    _log.info(f"  scope: {result.analysis_scope}")
    _log.info(f"  root:  {result.root}")
    return 0


def cmd_project_status(args: argparse.Namespace) -> int:
    """Emit per-stage project state + LLM cost as JSON (for the UI)."""
    try:
        status = service.project.get_project_status(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    _log.info(json.dumps(status, indent=2))
    return 0


def cmd_knowledge_list(args: argparse.Namespace) -> int:
    result = service.knowledge.list_rules(
        domain=args.domain, area=args.area, limit=args.limit
    )
    _log.info(f"Loaded {result.parasitic_rule_count} PCB parasitic rules.")
    _log.info(f"Loaded {result.emc_rule_count} EMC/LTspice rules.")
    if result.domain:
        _log.info(
            f"\nParasitic rules matching domain~='{result.domain}': "
            f"{len(result.domain_matches)}"
        )
        for r in result.domain_matches[: result.limit]:
            _log.info(
                f"  - {r.rule_id}: {r.structure} / {r.parasitic} [{r.confidence}]"
            )
    if result.area:
        _log.info(
            f"\nEMC rules matching area~='{result.area}': "
            f"{len(result.area_matches)}"
        )
        for r in result.area_matches[: result.limit]:
            _log.info(f"  - {r.rule_id}: {r.rule}")
    return 0


def cmd_knowledge_index(args: argparse.Namespace) -> int:
    try:
        service.knowledge.build_index(
            use_stub=getattr(args, "embedder_stub", False),
            embedder_model=getattr(args, "embedder_model", None),
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0


def cmd_knowledge_search(args: argparse.Namespace) -> int:
    try:
        hits = service.knowledge.search_index(
            args.query,
            k=int(args.k),
            use_stub=getattr(args, "embedder_stub", False),
            embedder_model=getattr(args, "embedder_model", None),
        )
    except ServiceError as exc:
        return _fail(exc)
    _log.info(f"[knowledge search] query='{args.query}' k={args.k} → {len(hits)} hits")
    for hit in hits:
        _log.info(
            f"  [{hit.rank}] score={hit.score:.3f} | "
            f"[{hit.tier} / {hit.source_id} / {hit.rule_id}] {hit.title[:80]}"
        )
    return 0


def cmd_knowledge_build_pack(args: argparse.Namespace) -> int:
    try:
        service.knowledge.build_pack(
            args.project_root,
            k=int(args.k),
            use_stub=getattr(args, "embedder_stub", False),
            embedder_model=getattr(args, "embedder_model", None),
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0


def cmd_parasitics_estimate(args: argparse.Namespace) -> int:
    try:
        result = service.parasitics.estimate_parasitics(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    for p in result.parasitics:
        _log.info(
            f"  - {p.id}: {p.structure}/{p.parasitic_type} "
            f"min={p.min_value:.3g} typ={p.value:.3g} max={p.max_value:.3g} {p.unit}"
        )
    return 0


def cmd_parasitics_per_net(args: argparse.Namespace) -> int:
    try:
        service.parasitics.estimate_per_net(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    return 0


def cmd_parasitics_reevaluate(args: argparse.Namespace) -> int:
    try:
        res = service.parasitics.reevaluate_parasitics(
            args.project_root,
            CommandOptions.from_namespace(args),
            apply=getattr(args, "apply", False),
        )
    except ServiceError as exc:
        return _fail(exc)
    _log.info(
        f"Re-evaluated {res.refined_count}/{res.considered} net(s) "
        f"({res.cited_count} citation-backed), cost ~${res.cost_usd:.4f}. "
        f"Audit: {res.audit_path}"
        + (f" Applied {res.applied} typ override(s)." if getattr(args, "apply", False) else "")
    )
    return 0


def cmd_testbench_compose(args: argparse.Namespace) -> int:
    try:
        service.testbench.compose_testbench(
            args.project_root, CommandOptions.from_namespace(args)
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0


@_with_run_log("sim")
def cmd_simulate_run(args: argparse.Namespace) -> int:
    try:
        result = service.simulate.run_testbench(
            args.project_root, CommandOptions.from_namespace(args)
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0 if result.ok else 1


def cmd_netlist_inspect(args: argparse.Namespace) -> int:
    try:
        result = service.netlist.inspect_netlist(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    _log.info(f"Title: {result.title}")
    _log.info(
        f"Elements: {len(result.elements)}, directives: {len(result.directives)}"
    )
    for el in result.elements:
        _log.info(f"  - {el.refdes} ({el.kind}) nodes={el.nodes} value={el.value}")
    for d in result.directives:
        _log.info(f"  . {d.name} {' '.join(d.args)}")
    return 0


def cmd_variants_compose(args: argparse.Namespace) -> int:
    try:
        service.testbench.compose_variants(
            args.project_root, CommandOptions.from_namespace(args)
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0


def cmd_variants_run(args: argparse.Namespace) -> int:
    try:
        result = service.simulate.run_variants(
            args.project_root, CommandOptions.from_namespace(args)
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0 if result.ok else 1


def cmd_recommendations_list(args: argparse.Namespace) -> int:
    try:
        result = service.recommendations.list_recommendations(args.project_root)
    except ServiceError as exc:
        return _fail(exc)
    if not result.rows:
        _log.info(
            "No recommendations found. Run the pipeline first so "
            "results/findings/<area>.json exists."
        )
        return 0
    _log.info(f"Recommendations for {result.project_id} ({len(result.rows)}):")
    for row in result.rows:
        _log.info(
            f"  [{row.status:8}] {row.area}/{row.rec_id}  "
            f"({row.severity})  {row.problem[:66]}"
        )
    return 0


def _cmd_recommendations_decide(args: argparse.Namespace, status: str) -> int:
    try:
        result = service.recommendations.decide_recommendation(
            args.project_root, args.key, status, getattr(args, "reason", "")
        )
    except ServiceError as exc:
        return _fail(exc)
    suffix = f" — {result.reason}" if result.reason else ""
    _log.info(f"Recorded: {result.key} -> {result.status}{suffix}")
    _log.info(f"  decisions/ updated in {result.decisions_dir}")
    return 0


def cmd_recommendations_accept(args: argparse.Namespace) -> int:
    return _cmd_recommendations_decide(args, "accepted")


def cmd_recommendations_reject(args: argparse.Namespace) -> int:
    return _cmd_recommendations_decide(args, "rejected")


def cmd_report_generate(args: argparse.Namespace) -> int:
    try:
        service.report.generate_report(
            args.project_root, CommandOptions.from_namespace(args)
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0


@_with_run_log("pipeline")
def cmd_pipeline_run(args: argparse.Namespace) -> int:
    """One-shot: parasitics -> testbench -> variants -> simulate -> report."""
    try:
        service.pipeline.run_pipeline(
            args.project_root, CommandOptions.from_namespace(args)
        )
    except ServiceError as exc:
        return _fail(exc)
    return 0


def cmd_raw_inspect(args: argparse.Namespace) -> int:
    try:
        result = service.raw.inspect_raw(args.raw_path)
    except ServiceError as exc:
        return _fail(exc)
    _log.info(f"Title:     {result.title}")
    _log.info(f"Plotname:  {result.plotname}")
    _log.info(f"Flags:     {', '.join(result.flags)}")
    _log.info(f"Variables: {result.n_variables}; Points: {result.n_points}")
    if result.axis_min is not None:
        _log.info(f"Axis range: {result.axis_min:.6g} .. {result.axis_max:.6g}")
    _log.info("Traces:")
    for var in result.traces:
        _log.info(f"  - [{var.index}] {var.name} ({var.kind})")
    return 0


def cmd_raw_export_csv(args: argparse.Namespace) -> int:
    try:
        result = service.raw.export_raw_csv(args.raw_path, args.trace, args.output)
    except ServiceError as exc:
        return _fail(exc)
    _log.info(f"Wrote CSV: {result.output_path} (traces={result.traces})")
    return 0


def _fmt_margin(margin: float | None) -> str:
    """Human-readable compliance margin (reading − limit, in dB)."""
    if margin is None:
        return "n/a (centre frequency outside the standard's limit range)"
    if margin < -0.005:
        return f"{margin:+.2f} dB (below limit)"
    if margin > 0.005:
        return f"{margin:+.2f} dB (over limit)"
    return "0.00 dB (at limit)"


def _fmt_worst_margin(worst) -> str:
    """Human-readable worst sweep margin (a WorstMargin or None)."""
    if worst is None:
        return "n/a (no swept frequency inside the standard's limit range)"
    side = "over limit" if worst.margin_db > 0.005 else "below limit"
    return (
        f"{worst.margin_db:+.2f} dB at {worst.freq_hz / 1e6:.3g} MHz ({side})"
    )


def cmd_raw_quasi_peak(args: argparse.Namespace) -> int:
    """Mode 2 — receiver-like quasi-peak estimate at one frequency."""
    try:
        report = service.raw.quasi_peak(
            args.raw_path,
            center_hz=args.frequency,
            trace=args.trace,
            skip_fraction=args.skip,
            standard_id=args.standard,
        )
    except ServiceError as exc:
        return _fail(exc)
    r = report.reading
    if not r.usable:
        _log.error(f"Quasi-peak not available: {r.note}")
        return 1
    _log.info(
        f"Receiver-like quasi-peak — trace {report.trace} "
        f"@ {r.center_hz:.6g} Hz"
    )
    _log.info(
        f"  CISPR Band {r.band}  RBW {r.rbw_hz:.0f} Hz  mode {r.mode}"
    )
    _log.info(f"  peak        = {r.peak_dbuv:8.2f} dBuV")
    _log.info(f"  quasi-peak  = {r.quasi_peak_dbuv:8.2f} dBuV")
    _log.info(f"  average     = {r.average_dbuv:8.2f} dBuV")
    if report.standard_name:
        _log.info(f"  vs {report.standard_name} limit:")
        _log.info(
            f"    quasi-peak margin = {_fmt_margin(report.quasi_peak_margin_db)}"
        )
        _log.info(
            f"    average margin    = {_fmt_margin(report.average_margin_db)}"
        )
    if r.note:
        _log.warning(f"  note: {r.note}")
    _log.info(
        "  CISPR-like pre-compliance diagnostic — not a certified EMI-"
        "receiver measurement."
    )
    return 0


def cmd_raw_quasi_peak_sweep(args: argparse.Namespace) -> int:
    """Mode 3 — receiver-like quasi-peak sweep across CISPR Band B."""
    try:
        report = service.raw.quasi_peak_sweep(
            args.raw_path,
            trace=args.trace,
            skip_fraction=args.skip,
            standard_id=args.standard,
            n_points=args.points,
        )
    except ServiceError as exc:
        return _fail(exc)
    sweep = report.sweep
    if not sweep.usable:
        _log.error(f"Quasi-peak sweep not available: {sweep.note}")
        return 1
    _log.info(
        f"Receiver-like sweep — trace {report.trace}, CISPR Band {sweep.band}, "
        f"{sweep.freq_hz.size} points"
    )
    _log.info(f"  band-max peak        = {float(sweep.peak_dbuv.max()):8.2f} dBuV")
    _log.info(
        f"  band-max quasi-peak  = {float(sweep.quasi_peak_dbuv.max()):8.2f} dBuV"
    )
    _log.info(
        f"  band-max average     = {float(sweep.average_dbuv.max()):8.2f} dBuV"
    )
    if report.standard_name:
        _log.info(f"  vs {report.standard_name} limit:")
        _log.info(
            f"    worst quasi-peak margin = "
            f"{_fmt_worst_margin(report.quasi_peak_worst)}"
        )
        _log.info(
            f"    worst average margin    = "
            f"{_fmt_worst_margin(report.average_worst)}"
        )
    if sweep.note:
        _log.warning(f"  note: {sweep.note}")
    _log.info(
        "  CISPR-like pre-compliance diagnostic — not a certified EMI-"
        "receiver measurement."
    )
    return 0


def cmd_version(args: argparse.Namespace) -> int:
    _log.info(f"emc-assistant {__version__}")
    return 0


def _add_embedder_flags(parser: argparse.ArgumentParser) -> None:
    """Shared --embedder-* flags for the `knowledge index|search|build-pack` subcommands."""
    parser.add_argument(
        "--embedder-model",
        default=None,
        help=f"sentence-transformers model name. Default: {DEFAULT_SENTENCE_TRANSFORMERS_MODEL}. "
        "Requires the `[embeddings]` extra (`pip install 'emc-assistant[embeddings]'`).",
    )
    parser.add_argument(
        "--embedder-stub",
        action="store_true",
        default=False,
        help="Use the deterministic hash-based stub embedder (for CI / no-dep environments). "
        "Embeddings have no semantic meaning; useful only for plumbing tests.",
    )


def _add_llm_flags(parser: argparse.ArgumentParser) -> None:
    """Attach the LLM-related flags to a subcommand parser."""
    parser.add_argument(
        "--llm",
        choices=("none", "openai"),
        default="none",
        help="LLM backend: 'none' = deterministic fallback (M2.6.1 behavior); "
        "'openai' = use OpenAI API (requires OPENAI_API_KEY).",
    )
    parser.add_argument(
        "--llm-mode",
        choices=("replace", "augment"),
        default="replace",
        help="In 'replace' mode the LLM writes recommendations from scratch; "
        "in 'augment' mode it rewrites the deterministic baseline.",
    )
    parser.add_argument(
        "--llm-budget-usd",
        type=float,
        default=1.0,
        help="Hard cap on the estimated cost (USD) of a single pipeline run's "
        "LLM calls. The call aborts before any network I/O if the estimate "
        "exceeds this budget. Default: 1.00.",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help=f"OpenAI model name. Default: {OPENAI_DEFAULT_MODEL}.",
    )
    parser.add_argument(
        "--llm-top-k",
        type=int,
        default=5,
        help="Number of top retrieved knowledge snippets to include in the prompt.",
    )


def _add_wiring_flags(parser: argparse.ArgumentParser) -> None:
    """Add the wiring acceptance flags to a subcommand parser."""
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--accept-wiring",
        dest="accept_wiring",
        action="store_true",
        default=False,
        help="Accept the testbench_wiring proposal without interactive prompt.",
    )
    group.add_argument(
        "--no-wiring",
        dest="no_wiring",
        action="store_true",
        default=False,
        help="Skip emitting the LISN/cable X-instances even if testbench_wiring is set.",
    )
    pgroup = parser.add_mutually_exclusive_group()
    pgroup.add_argument(
        "--accept-parasitics",
        dest="accept_parasitics",
        action="store_true",
        default=False,
        help=(
            "M2.10: opt in to the parasitics agent's deterministic injection plan. "
            "Splices TRACE_RLC (and possibly VIA_L / CAP_ESR_ESL) X-instances into "
            "testbench.cir so the variant sweep actually moves V(MEAS)."
        ),
    )
    pgroup.add_argument(
        "--no-parasitics",
        dest="no_parasitics",
        action="store_true",
        default=False,
        help="M2.10: explicitly skip the parasitic-injection plan (M2.6.1 behaviour).",
    )
    parser.add_argument(
        "--parasitics-report-only",
        dest="parasitics_report_only",
        action="store_true",
        default=False,
        help=(
            "M2.10.8: estimate the per-net series + shunt parasitics (report "
            "table, schematic annotation, audit JSON) but do NOT inject them "
            "into the simulated testbench.cir. The input-rail TRACE_RLC still "
            "goes in. Use when the full per-net testbench is too slow to "
            "simulate."
        ),
    )
    sgroup = parser.add_mutually_exclusive_group()
    sgroup.add_argument(
        "--accept-signals",
        dest="accept_signals",
        action="store_true",
        default=False,
        help=(
            "M2.10.1: opt in to the feature-keeper's signal-map proposal. "
            "Persists the resolved map back into user_context.json and emits "
            "per-signal .meas directives in testbench.cir."
        ),
    )
    sgroup.add_argument(
        "--no-signals",
        dest="no_signals",
        action="store_true",
        default=False,
        help="M2.10.1: explicitly skip the signal-map step.",
    )
    parser.add_argument(
        "--no-asc-export",
        dest="no_asc_export",
        action="store_true",
        default=False,
        help=(
            "M2.10.3: skip writing generated/testbench.asc + symbols. "
            "The .cir is always written; .asc is a visualisation aid only."
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="emc-assistant", description="Local EMC/LTspice Assistant — MVP")
    parser.add_argument("--version", action="version", version=f"emc-assistant {__version__}")
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose output — log at DEBUG level",
    )
    parser.add_argument(
        "-q", "--quiet", action="store_true",
        help="Quiet output — log warnings and errors only",
    )
    parser.add_argument(
        "--log-file", default=None,
        help="Also write a JSONL operational log to this path",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_proj = sub.add_parser("project", help="Project operations")
    p_proj_sub = p_proj.add_subparsers(dest="subcommand", required=True)
    p_create = p_proj_sub.add_parser("create", help="Create a new .emcproj project")
    p_create.add_argument("project_root", help="New project directory")
    p_create.set_defaults(func=cmd_project_create)
    p_validate = p_proj_sub.add_parser("validate", help="Validate project.yaml")
    p_validate.add_argument("project_root", help="Project directory (.emcproj)")
    p_validate.set_defaults(func=cmd_project_validate)
    p_status = p_proj_sub.add_parser(
        "status", help="Per-stage project state + LLM cost (JSON)"
    )
    p_status.add_argument("project_root", help="Project directory (.emcproj)")
    p_status.set_defaults(func=cmd_project_status)

    p_kb = sub.add_parser("knowledge", help="Knowledge-base operations")
    p_kb_sub = p_kb.add_subparsers(dest="subcommand", required=True)
    p_list = p_kb_sub.add_parser("list", help="List rules")
    p_list.add_argument("--domain", default=None)
    p_list.add_argument("--area", default=None)
    p_list.add_argument("--limit", type=int, default=10)
    p_list.set_defaults(func=cmd_knowledge_list)

    p_kb_index = p_kb_sub.add_parser("index", help="Build the local vector index")
    _add_embedder_flags(p_kb_index)
    p_kb_index.set_defaults(func=cmd_knowledge_index)

    p_kb_search = p_kb_sub.add_parser("search", help="Query the local vector index")
    p_kb_search.add_argument("query")
    p_kb_search.add_argument("--k", type=int, default=5, help="Top-K results")
    _add_embedder_flags(p_kb_search)
    p_kb_search.set_defaults(func=cmd_knowledge_search)

    p_kb_pack = p_kb_sub.add_parser("build-pack", help="Build knowledge_pack.json for a project")
    p_kb_pack.add_argument("project_root")
    p_kb_pack.add_argument("--k", type=int, default=8, help="Top-K snippets in the pack")
    _add_embedder_flags(p_kb_pack)
    p_kb_pack.set_defaults(func=cmd_knowledge_build_pack)

    p_par = sub.add_parser("parasitics", help="Parasitic calculators")
    p_par_sub = p_par.add_subparsers(dest="subcommand", required=True)
    p_estimate = p_par_sub.add_parser("estimate", help="Estimate parasitics for the project")
    p_estimate.add_argument("project_root")
    p_estimate.set_defaults(func=cmd_parasitics_estimate)
    p_pernet = p_par_sub.add_parser(
        "per-net", help="Write per-net topology + parasitic estimates (no compose)"
    )
    p_pernet.add_argument("project_root")
    p_pernet.set_defaults(func=cmd_parasitics_per_net)
    p_reeval = p_par_sub.add_parser(
        "reevaluate",
        help="LLM/RAG re-evaluation of per-net parasitic VALUES into "
        "citation-backed bands (M2.17); needs --llm openai",
    )
    p_reeval.add_argument("project_root")
    p_reeval.add_argument(
        "--apply", action="store_true", default=False,
        help="Persist the refined typ values as user overrides "
        "(min/typ/max bands stay in the audit only)",
    )
    _add_llm_flags(p_reeval)
    p_reeval.set_defaults(func=cmd_parasitics_reevaluate)

    p_tb = sub.add_parser("testbench", help="SPICE testbench generator")
    p_tb_sub = p_tb.add_subparsers(dest="subcommand", required=True)
    p_compose = p_tb_sub.add_parser("compose", help="Compose the full testbench.cir")
    p_compose.add_argument("project_root")
    _add_wiring_flags(p_compose)
    _add_llm_flags(p_compose)
    p_compose.set_defaults(func=cmd_testbench_compose)

    p_var = sub.add_parser("variants", help="Corner sweep — parasitic variants")
    p_var_sub = p_var.add_subparsers(dest="subcommand", required=True)
    p_var_compose = p_var_sub.add_parser("compose", help="Generate .cir per variant")
    p_var_compose.add_argument("project_root")
    _add_wiring_flags(p_var_compose)
    _add_llm_flags(p_var_compose)
    p_var_compose.set_defaults(func=cmd_variants_compose)
    p_var_run = p_var_sub.add_parser("run", help="Run LTspice for each variant")
    p_var_run.add_argument("project_root")
    p_var_run.add_argument("--mode", choices=("dry-run", "local-run"), default=None)
    p_var_run.set_defaults(func=cmd_variants_run)

    p_sim = sub.add_parser("simulate", help="Run LTspice locally (or dry-run)")
    p_sim_sub = p_sim.add_subparsers(dest="subcommand", required=True)
    p_run = p_sim_sub.add_parser("run", help="Run testbench.cir")
    p_run.add_argument("project_root")
    p_run.add_argument(
        "--mode",
        choices=("dry-run", "local-run"),
        default=None,
        help="Defaults to project.yaml (ltspice.mode)",
    )
    p_run.set_defaults(func=cmd_simulate_run)

    p_nl = sub.add_parser("netlist", help=".cir netlist parser")
    p_nl_sub = p_nl.add_subparsers(dest="subcommand", required=True)
    p_inspect = p_nl_sub.add_parser("inspect", help="Inspect the input netlist")
    p_inspect.add_argument("project_root")
    p_inspect.set_defaults(func=cmd_netlist_inspect)

    p_rep = sub.add_parser("report", help="Reports")
    p_rep_sub = p_rep.add_subparsers(dest="subcommand", required=True)
    p_rgen = p_rep_sub.add_parser("generate", help="Generate Markdown report")
    p_rgen.add_argument("project_root")
    p_rgen.add_argument(
        "--rank-metric",
        default=None,
        help="Metric key from simulation_run.json used for variant ranking",
    )
    p_rgen.add_argument(
        "--higher-is-better",
        dest="lower_is_better",
        action="store_false",
        default=True,
        help="By default lower metric is better",
    )
    p_rgen.add_argument(
        "--html",
        action="store_true",
        default=False,
        help="Also write reports/report.html (styled HTML view of the report)",
    )
    p_rgen.add_argument(
        "--pdf",
        action="store_true",
        default=False,
        help="Also write reports/report.pdf (requires the [pdf] extra)",
    )
    _add_llm_flags(p_rgen)
    p_rgen.set_defaults(func=cmd_report_generate)

    p_recs = sub.add_parser(
        "recommendations", help="Accept / reject agent recommendations (M2.12)"
    )
    p_recs_sub = p_recs.add_subparsers(dest="subcommand", required=True)
    p_recs_list = p_recs_sub.add_parser("list", help="List recommendations + status")
    p_recs_list.add_argument("project_root")
    p_recs_list.set_defaults(func=cmd_recommendations_list)
    p_recs_acc = p_recs_sub.add_parser("accept", help="Accept a recommendation")
    p_recs_acc.add_argument("project_root")
    p_recs_acc.add_argument("key", help="Recommendation key <area>/<rec_id>, e.g. filtering/REC-003")
    p_recs_acc.add_argument("--reason", default="", help="Optional note")
    p_recs_acc.set_defaults(func=cmd_recommendations_accept)
    p_recs_rej = p_recs_sub.add_parser("reject", help="Reject a recommendation")
    p_recs_rej.add_argument("project_root")
    p_recs_rej.add_argument("key", help="Recommendation key <area>/<rec_id>")
    p_recs_rej.add_argument("--reason", default="", help="Why it was rejected (required)")
    p_recs_rej.set_defaults(func=cmd_recommendations_reject)

    p_pipe = sub.add_parser("pipeline", help="End-to-end pipeline")
    p_pipe_sub = p_pipe.add_subparsers(dest="subcommand", required=True)
    p_prun = p_pipe_sub.add_parser("run", help="One-shot pipeline (compose→variants→simulate→report)")
    p_prun.add_argument("project_root")
    p_prun.add_argument("--mode", choices=("dry-run", "local-run"), default=None)
    p_prun.add_argument("--rank-metric", default=None)
    p_prun.add_argument(
        "--html",
        action="store_true",
        default=False,
        help="Also write reports/report.html",
    )
    p_prun.add_argument(
        "--pdf",
        action="store_true",
        default=False,
        help="Also write reports/report.pdf (requires the [pdf] extra)",
    )
    p_prun.add_argument(
        "--higher-is-better",
        dest="lower_is_better",
        action="store_false",
        default=True,
    )
    _add_wiring_flags(p_prun)
    _add_llm_flags(p_prun)
    p_prun.set_defaults(func=cmd_pipeline_run)

    p_raw = sub.add_parser("raw", help="Inspect and export .raw files")
    p_raw_sub = p_raw.add_subparsers(dest="subcommand", required=True)
    p_rinspect = p_raw_sub.add_parser("inspect", help="List variables, flags, axis range")
    p_rinspect.add_argument("raw_path")
    p_rinspect.set_defaults(func=cmd_raw_inspect)
    p_rexport = p_raw_sub.add_parser("export-csv", help="Export selected traces to CSV")
    p_rexport.add_argument("raw_path")
    p_rexport.add_argument("--trace", action="append", default=[], help="Trace name (repeatable)")
    p_rexport.add_argument("--output", required=True)
    p_rexport.set_defaults(func=cmd_raw_export_csv)
    p_rqp = p_raw_sub.add_parser(
        "quasi-peak",
        help="Receiver-like quasi-peak estimate at a frequency (CISPR Band B)",
    )
    p_rqp.add_argument("raw_path")
    p_rqp.add_argument(
        "--frequency", type=float, required=True,
        help="Centre frequency in Hz, e.g. 1e6 (CISPR Band B: 150e3–30e6)",
    )
    p_rqp.add_argument(
        "--trace", default=None,
        help="Trace name to analyse (default: auto-pick V(meas)/V(out)/…)",
    )
    p_rqp.add_argument(
        "--skip", type=float, default=0.0,
        help="Fraction of the startup transient to skip (default: 0.0)",
    )
    p_rqp.add_argument(
        "--standard", default=None,
        help="Compliance standard id for the margin (default: en55022_class_b)",
    )
    p_rqp.set_defaults(func=cmd_raw_quasi_peak)
    p_rqps = p_raw_sub.add_parser(
        "quasi-peak-sweep",
        help="Receiver-like quasi-peak sweep across CISPR Band B (Mode 3)",
    )
    p_rqps.add_argument("raw_path")
    p_rqps.add_argument(
        "--trace", default=None,
        help="Trace name to analyse (default: auto-pick V(meas)/V(out)/…)",
    )
    p_rqps.add_argument(
        "--skip", type=float, default=0.0,
        help="Fraction of the startup transient to skip (default: 0.0)",
    )
    p_rqps.add_argument(
        "--standard", default=None,
        help="Compliance standard id for the margin (default: en55022_class_b)",
    )
    p_rqps.add_argument(
        "--points", type=int, default=128,
        help="Number of swept centre frequencies (default: 128)",
    )
    p_rqps.set_defaults(func=cmd_raw_quasi_peak_sweep)

    p_ver = sub.add_parser("version", help="Tool version")
    p_ver.set_defaults(func=cmd_version)

    return parser


def _ensure_utf8_stdio() -> None:
    """Force UTF-8 on stdout/stderr (Windows cp1250 cannot encode e.g. Ω).

    Thin wrapper over the shared seam so the CLI and UI use one implementation.
    """
    from emc_assistant.logging_setup import ensure_utf8_stdio

    ensure_utf8_stdio()


def main(argv: list[str] | None = None) -> int:
    _ensure_utf8_stdio()
    parser = build_parser()
    args = parser.parse_args(argv)
    if getattr(args, "verbose", False):
        level = "debug"
    elif getattr(args, "quiet", False):
        level = "warning"
    else:
        level = "info"
    configure_logging(level, log_file=getattr(args, "log_file", None))
    return int(args.func(args))


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
