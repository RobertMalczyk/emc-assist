"""Decision-resolution helpers for the orchestration service.

These turn a project's ``user_context`` plus the run's
:class:`~emc_assistant.service.options.CommandOptions` into the concrete
decisions the composer needs: testbench wiring, the LISN mode, the
parasitic-injection / shunt / series plans, the signal map, the LLM
assistant, and the prepared user-circuit fragment.

The pipeline resolves these once and threads them to each sub-step via
``CommandOptions.child(...)``; a standalone command resolves them itself.

Note: ``_resolve_wiring`` / ``_resolve_signals`` may call ``input()`` for
an interactive CLI confirmation — guarded by ``sys.stdin.isatty()``. The
M3 UI always passes an explicit accept/decline decision, so it never
reaches the prompt (and a non-TTY context skips it anyway).
"""

from __future__ import annotations

import json
import os
import sys
import uuid as _uuid
from pathlib import Path

from emc_assistant.llm import (
    DeterministicAssistant,
    LlmAssistant,
    OpenAiAssistant,
    ProblemContext,
)
from emc_assistant.llm.budget import BudgetTracker
from emc_assistant.llm.openai_provider import DEFAULT_MODEL as OPENAI_DEFAULT_MODEL
from emc_assistant.logging_setup import get_logger
from emc_assistant.netlist.asc_converter import AscConversionError, convert_asc_to_cir
from emc_assistant.netlist.fragment import write_user_fragment
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.project.model import load_project
from emc_assistant.service.context import build_problem_context
from emc_assistant.service.options import _UNSET, CommandOptions
from emc_assistant.testbench.composer import TestbenchWiring

_log = get_logger("resolve")


# ---- user-circuit fragment -------------------------------------------------


def prepare_user_fragment(
    layout,
    user_netlist,
    *,
    strip_sources=(),
    config=None,
    rename_ground_to: str | None = None,
    series_split_nets=(),
):
    """Return the path to ``generated/user_circuit_fragment.cir`` (or None).

    When ``user_netlist`` points at a ``.asc`` LTspice schematic, we call
    LTspice CLI to produce a cached ``.cir`` sibling first; the fragment
    preprocessor then operates on that.

    ``rename_ground_to`` (e.g. ``"DUT_GND"``) lifts the user's local
    ground off SPICE's universal ``0`` reference when the composer is
    wiring a dual-LISN topology. Skipped for single-LISN mode.
    """
    if user_netlist is None or not Path(user_netlist).is_file():
        return None
    netlist_path = Path(user_netlist)
    if netlist_path.suffix.lower() == ".asc":
        ltspice_exe = None
        if config is not None:
            ltspice_exe = (
                str(config.ltspice.get("executable_path") or "")
                or os.environ.get("LTSPICE_PATH", "")
            )
        else:
            ltspice_exe = os.environ.get("LTSPICE_PATH", "")
        try:
            result = convert_asc_to_cir(netlist_path, ltspice_exe=ltspice_exe or None)
        except AscConversionError as exc:
            _log.warning(f"  asc-to-cir: {exc}")
            return None
        if result.used_cache:
            _log.info(
                f"  asc-to-cir: cached {result.cir_path.name} "
                f"(newer than {result.asc_path.name})"
            )
        else:
            _log.info(
                f"  asc-to-cir: produced {result.cir_path.name} via LTspice -netlist"
            )
        netlist_path = result.cir_path

    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    fragment = layout.generated_dir / "user_circuit_fragment.cir"
    removed = write_user_fragment(
        netlist_path,
        fragment,
        strip_sources=strip_sources,
        rename_ground_to=rename_ground_to,
        series_split_nets=series_split_nets,
    )
    if removed:
        _log.info(f"  fragment: stripped: {', '.join(removed)}")
    if rename_ground_to:
        _log.info(
            f"  fragment: renamed `0` -> `{rename_ground_to}` "
            "in node positions (dual-LISN)"
        )
    return fragment


# ---- LLM assistant ---------------------------------------------------------


def make_assistant(
    options: CommandOptions, *, layout, run_id: str
) -> tuple[LlmAssistant, str | None]:
    """Pick the LLM assistant for this run and return it + an optional log path.

    Honours ``options.stub_assistant`` when set (tests inject one). For
    M2.9 the run-level :class:`BudgetTracker` is attached to the OpenAI
    provider so that the per-recommendations call + the per-agent calls
    share the user's ``--llm-budget-usd`` cap cumulatively.
    """
    if options.stub_assistant is not None:
        return options.stub_assistant, None
    llm_choice = options.llm or "none"
    if llm_choice == "openai":
        log_path = layout.results_dir / "llm" / f"{run_id}.jsonl"
        model = options.llm_model or OPENAI_DEFAULT_MODEL
        budget = float(options.llm_budget_usd)
        budget_tracker = BudgetTracker(cap_usd=budget)
        return (
            OpenAiAssistant(
                model=model,
                budget_usd=budget,
                privacy_log_path=log_path,
                budget_tracker=budget_tracker,
            ),
            str(log_path),
        )
    return DeterministicAssistant(), None


def llm_enabled(options: CommandOptions) -> bool:
    """True when a real (or test-stub) LLM is available for this run.

    The M2.10.7 negligibility screen only runs when the user opted in
    (``--llm openai``) or a test injected a stub — by default the
    pipeline is deterministic and no parasitic is dropped.
    """
    if options.stub_assistant is not None:
        return True
    return (options.llm or "none") == "openai"


def filter_negligible(
    entries: list,
    kind: str,
    *,
    options: CommandOptions,
    layout,
    config,
    user_context: dict,
) -> tuple[list, list]:
    """Run the M2.10.7 LLM negligibility screen over a per-net plan.

    Returns ``(kept, dropped)``. When the LLM is not enabled, or on any
    LLM error, every entry is kept (fail-safe). ``dropped`` is a list of
    ``{"net","kind","reason"}`` dicts.
    """
    if not entries or not llm_enabled(options):
        return list(entries), []
    run_id = f"par-{_uuid.uuid4().hex[:8]}"
    try:
        assistant, _ = make_assistant(options, layout=layout, run_id=run_id)
    except Exception as exc:  # noqa: BLE001
        _log.warning(
            f"[parasitics] LLM unavailable for negligibility screen ({exc}); "
            f"keeping all {len(entries)} {kind} parasitic(s)."
        )
        return list(entries), []
    pc = build_problem_context(config, user_context, [])
    ctx_line = (
        f"Circuit: {pc.topology or 'DC/DC converter'}. "
        f"Conducted-EMI band {int(pc.frequency_range_min_hz or 150_000)}-"
        f"{int(pc.frequency_range_max_hz or 30_000_000)} Hz."
    )
    if pc.switching_frequency_hz:
        ctx_line += f" Switching frequency {pc.switching_frequency_hz:g} Hz."
    from emc_assistant.agents.parasitics_agent import ParasiticsAgent

    kept, dropped = ParasiticsAgent().filter_negligible(
        entries,
        kind=kind,
        assistant=assistant,
        context_line=ctx_line,
        purpose=f"parasitics.negligibility.{kind}",
    )
    tracker = getattr(assistant, "budget_tracker", None)
    if tracker is not None and getattr(tracker, "spent_usd", 0.0) > 0:
        _log.info(
            f"[parasitics] negligibility screen ({kind}): LLM cost ~"
            f"${tracker.spent_usd:.4f} (gpt-5-mini; see results/llm/{run_id}.jsonl)"
        )
    if dropped:
        _log.info(
            f"[parasitics] negligibility screen dropped {len(dropped)}/{len(entries)} "
            f"{kind} parasitic(s):"
        )
        for d in dropped:
            _log.info(f"    - {d['net']}: {d['reason']}")
    return kept, dropped


# ---- simulation settings ---------------------------------------------------


def resolve_simulation_settings(user_context: dict):
    """Build :class:`SimulationSettings` from ``user_context.simulation`` (M2.13).

    Returns a ``SimulationSettings``, or ``None`` when the structured
    settings are invalid (the caller should abort).
    """
    from emc_assistant.testbench.sim_settings import SimulationSettings

    try:
        return SimulationSettings.from_user_context(user_context)
    except ValueError as exc:
        _log.warning(f"[simulation] invalid user_context.simulation: {exc}")
        return None


# ---- LISN mode -------------------------------------------------------------


def resolve_lisn_mode(
    user_context: dict, options: CommandOptions, *, layout, config
) -> str:
    """M2.10.x — pre-composition LISN-mode decision (12th agent).

    An explicit ``dual``/``single`` in
    ``user_context.testbench_wiring.lisn_mode`` always wins. When it is
    absent or ``"auto"``, the :class:`LisnModeAgent` decides: the LLM
    path under ``--llm openai``, the deterministic heuristic otherwise.
    """
    cfg = (user_context or {}).get("testbench_wiring")
    explicit = ""
    if isinstance(cfg, dict):
        explicit = str(cfg.get("lisn_mode", "")).strip().lower()
    if explicit in ("dual", "single"):
        return explicit

    topology = None
    netlist_rel = config.inputs.get("netlist_path", "") if config is not None else ""
    if netlist_rel and layout is not None:
        raw = (layout.root / netlist_rel).resolve()
        try:
            from emc_assistant.netlist.topology import analyse_fragment

            cir = raw
            if raw.suffix.lower() == ".asc":
                ltx = str(config.ltspice.get("executable_path") or "") or os.environ.get(
                    "LTSPICE_PATH", ""
                )
                try:
                    cir = convert_asc_to_cir(raw, ltspice_exe=ltx or None).cir_path
                except AscConversionError:
                    cir = None
            if cir is not None and Path(cir).is_file():
                topology = analyse_fragment(Path(cir))
        except Exception as exc:  # noqa: BLE001
            _log.warning(f"[lisn] topology analysis failed: {exc}")

    problem_context = build_problem_context(config, user_context, [])
    assistant = None
    if llm_enabled(options):
        try:
            assistant, _ = make_assistant(
                options, layout=layout, run_id=f"lisn-{_uuid.uuid4().hex[:8]}"
            )
        except Exception as exc:  # noqa: BLE001
            _log.warning(f"[lisn] LLM unavailable ({exc}); using the heuristic.")

    from emc_assistant.agents.lisn_mode_agent import LisnModeAgent

    decision = LisnModeAgent().decide(
        topology=topology, problem_context=problem_context, assistant=assistant
    )
    _log.info(
        f"[lisn] LISN-mode agent: {decision.mode}-LISN "
        f"(source={decision.source}, confidence={decision.confidence:.2f})"
    )
    _log.info(f"       {decision.rationale}")
    try:
        layout.results_dir.mkdir(parents=True, exist_ok=True)
        (layout.results_dir / "lisn_mode.json").write_text(
            json.dumps(decision.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    except Exception:  # noqa: BLE001
        pass
    return decision.mode


# ---- testbench wiring ------------------------------------------------------


def resolve_wiring(
    user_context: dict, options: CommandOptions, *, layout=None, config=None,
) -> tuple[TestbenchWiring | None, tuple[str, ...]]:
    """Read ``testbench_wiring`` from user_context, confirm, return the decision.

    Returns ``(wiring_or_None, strip_sources_tuple)``. ``wiring`` is None
    when user_context has no wiring block, when ``--no-wiring`` is set,
    when the user declines, or when stdin is not a TTY and
    ``--accept-wiring`` was not passed.
    """
    if options.resolved_wiring is not _UNSET:
        strip = (
            options.resolved_strip
            if options.resolved_strip is not _UNSET
            else ()
        )
        return options.resolved_wiring, strip

    cfg = (user_context or {}).get("testbench_wiring")
    if not isinstance(cfg, dict) or not cfg:
        return None, ()

    lisn_mode = str(cfg.get("lisn_mode", "")).strip().lower()
    if lisn_mode not in ("single", "dual"):
        # M2.10.x: unset or "auto" -> the LISN-mode agent decides.
        lisn_mode = resolve_lisn_mode(user_context, options, layout=layout, config=config)
    proposed = TestbenchWiring(
        external_supply_v=float(cfg.get("external_supply_v", 24.0)),
        dut_supply_net=str(cfg.get("dut_supply_net", "DUT_SUPPLY")),
        dut_return_net=str(cfg.get("dut_return_net", "0")),
        lisn_mode=lisn_mode,
    )
    strip_name = str(cfg.get("user_source_to_strip", "")).strip()
    strip_sources: tuple[str, ...] = (strip_name,) if strip_name else ()

    _log.info(
        f"[wiring] Proposed testbench wiring ({lisn_mode}-LISN) "
        "from user_context.testbench_wiring:"
    )
    _log.info(f"  V_RAIL HV_IN_RAIL 0 DC {proposed.external_supply_v}")
    if lisn_mode == "dual":
        _log.info("  X_LISN_P HV_IN_RAIL HV_DUT_P MEAS_P 0 LISN50UH")
        _log.info("  X_LISN_N 0 DUT_GND MEAS_N 0 LISN50UH")
        _log.info(f"  X_CABLE HV_DUT_P {proposed.dut_supply_net} DUT_GND CABLE_PWR")
        _log.info("  (also: rename `0` -> `DUT_GND` in user fragment node positions)")
    else:
        _log.info("  X_LISN HV_IN_RAIL HV_DUT MEAS 0 LISN50UH")
        _log.info(
            f"  X_CABLE HV_DUT {proposed.dut_supply_net} "
            f"{proposed.dut_return_net} CABLE_PWR"
        )
    if strip_name:
        _log.info(f"  (also: strip user source `{strip_name}` from the fragment)")

    if options.no_wiring:
        _log.info("[wiring] --no-wiring set; emission skipped.")
        return None, ()
    if options.accept_wiring:
        _log.info("[wiring] --accept-wiring set; emission confirmed.")
        return proposed, strip_sources
    try:
        is_tty = sys.stdin.isatty()
    except (AttributeError, ValueError):
        is_tty = False
    if not is_tty:
        _log.info(
            "[wiring] non-interactive stdin and no --accept-wiring; emission skipped."
        )
        return None, ()
    answer = input("Accept this wiring? [y/N]: ").strip().lower()
    if answer in ("y", "yes"):
        return proposed, strip_sources
    _log.info("[wiring] declined; emission skipped.")
    return None, ()


# ---- signal map ------------------------------------------------------------


def resolve_signals(
    user_context: dict, options: CommandOptions, *, layout, project_root_path
) -> list:
    """Resolve the M2.10.1 signal map for this run.

    Reads ``user_context['signals']`` (highest priority), auto-detects
    from ``.asc`` + ``.cir``, then — under ``--accept-signals`` or a TTY
    confirmation — persists the map back to ``user_context.json`` and
    writes ``generated/signals.json``.
    """
    if options.resolved_signals is not _UNSET:
        return list(options.resolved_signals)
    if options.no_signals:
        return []

    from emc_assistant.netlist.signals import (
        detect_signals,
        signals_from_user_context,
    )

    config, _, _ = load_project(project_root_path)
    netlist_rel = config.inputs.get("netlist_path", "")
    schematic_rel = config.inputs.get("schematic_path", "")
    cir_path = (layout.root / netlist_rel).resolve() if netlist_rel else None
    asc_path = (layout.root / schematic_rel).resolve() if schematic_rel else None
    if asc_path is None and cir_path is not None:
        candidate_asc = cir_path.with_suffix(".asc")
        if candidate_asc.is_file():
            asc_path = candidate_asc

    user_signals = signals_from_user_context(user_context)
    proposed = detect_signals(
        asc_path=asc_path if asc_path and asc_path.is_file() else None,
        cir_path=cir_path if cir_path and cir_path.is_file() else None,
        user_signals=user_signals,
    )
    if not proposed:
        _log.info(
            "[signals] no candidate signals detected "
            "(no .asc labels, no recognisable .cir nets)."
        )
        return []

    _log.info(f"[signals] proposed signal map ({len(proposed)} entries):")
    for s in proposed:
        tag = f"[{s.source}]" + (f" (label {s.from_label})" if s.from_label else "")
        _log.info(
            f"  {s.name:12s} {s.kind:9s} {s.expr:20s} "
            f"conf={s.confidence:.2f} {tag}"
        )

    if options.accept_signals:
        _log.info("[signals] --accept-signals: signal map confirmed.")
        accepted = proposed
    else:
        try:
            is_tty = sys.stdin.isatty()
        except (AttributeError, ValueError):
            is_tty = False
        if not is_tty:
            _log.info(
                "[signals] non-interactive stdin and no --accept-signals; "
                "signal map skipped."
            )
            return []
        answer = input("Accept this signal map? [y/N]: ").strip().lower()
        if answer not in ("y", "yes"):
            _log.info("[signals] declined; signal map skipped.")
            return []
        accepted = proposed

    # Persist back to user_context.json
    uc_path = layout.input_dir / "user_context.json"
    if uc_path.is_file():
        try:
            uc_data = json.loads(uc_path.read_text(encoding="utf-8"))
            uc_data["signals"] = [s.to_schema_dict() for s in accepted]
            uc_path.write_text(
                json.dumps(uc_data, indent=2, ensure_ascii=False),
                encoding="utf-8",
            )
            _log.info(f"[signals] persisted {len(accepted)} entries to {uc_path}")
        except (OSError, ValueError) as exc:
            _log.warning(
                f"[signals] could not persist to user_context.json: {exc}"
            )

    audit_path = layout.generated_dir / "signals.json"
    layout.generated_dir.mkdir(parents=True, exist_ok=True)
    audit_path.write_text(
        json.dumps(
            [s.to_schema_dict() for s in accepted], indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    _log.info(f"[signals] audit: {audit_path}")
    return accepted


# ---- parasitic plans -------------------------------------------------------


def resolve_parasitics_injection(
    user_context: dict,
    options: CommandOptions,
    *,
    parasitics: list[ParasiticEstimate],
    user_fragment_path: Path | None,
) -> list:
    """Resolve the M2.10 input-rail injection plan. Opt-in: empty unless
    ``--accept-parasitics``; ``--no-parasitics`` always wins."""
    if options.resolved_injection_plan is not _UNSET:
        return list(options.resolved_injection_plan)
    if options.no_parasitics:
        return []
    if not options.accept_parasitics:
        return []
    wiring_cfg = (user_context or {}).get("testbench_wiring")
    dut_supply_net = ""
    dut_return_net = ""
    if isinstance(wiring_cfg, dict):
        dut_supply_net = str(wiring_cfg.get("dut_supply_net", ""))
        dut_return_net = str(wiring_cfg.get("dut_return_net", ""))
        lisn_mode = str(wiring_cfg.get("lisn_mode", "dual")).strip().lower() or "dual"
        if lisn_mode == "dual" and dut_return_net in {"0", ""}:
            dut_return_net = "DUT_GND"

    topology = None
    if user_fragment_path is not None and user_fragment_path.is_file():
        try:
            from emc_assistant.netlist.topology import analyse_fragment

            topology = analyse_fragment(user_fragment_path)
        except Exception as exc:  # noqa: BLE001
            _log.warning(f"[parasitics] topology analysis failed: {exc}")

    from emc_assistant.agents.base import AgentInputs
    from emc_assistant.agents.parasitics_agent import ParasiticsAgent

    inputs = AgentInputs(
        problem_context=ProblemContext(
            project_id="parasitics-plan",
            analysis_scope="conducted_emi",
            has_layout=False,
            has_stackup=False,
        ),
        parasitics=list(parasitics),
        topology=topology,
        dut_supply_net=dut_supply_net,
        dut_return_net=dut_return_net,
    )
    plan = ParasiticsAgent()._default_injection_plan(inputs)
    if plan:
        _log.info(
            f"[parasitics] --accept-parasitics: deterministic plan has "
            f"{len(plan)} injection(s)."
        )
        for inj in plan:
            _log.info(f"  {inj.to_spice_line()}  ({inj.rationale[:80]})")
    else:
        _log.warning(
            "[parasitics] --accept-parasitics set but no injections could be "
            "built (no topology or no trace-L parasitic)."
        )
    return plan


def resolve_shunt_plan(
    user_context: dict,
    options: CommandOptions,
    *,
    user_fragment_path: Path | None,
    injection_plan: list,
    series_nets: tuple = (),
) -> list:
    """Resolve the M2.10.5 per-net shunt-parasitic plan."""
    if options.resolved_shunt_plan is not _UNSET:
        return list(options.resolved_shunt_plan)
    if options.no_parasitics:
        return []
    if not options.accept_parasitics:
        return []

    overrides: dict = {}
    para_cfg = (user_context or {}).get("parasitics")
    if isinstance(para_cfg, dict):
        if para_cfg.get("skip_all"):
            _log.info(
                "[parasitics] user_context.parasitics.skip_all set — "
                "no per-net shunt parasitics."
            )
            return []
        per_net = para_cfg.get("per_net")
        if isinstance(per_net, dict):
            overrides = {str(k): v for k, v in per_net.items() if isinstance(v, dict)}

    return_net = "DUT_GND"
    wiring_cfg = (user_context or {}).get("testbench_wiring")
    if isinstance(wiring_cfg, dict):
        lisn_mode = str(wiring_cfg.get("lisn_mode", "dual")).strip().lower() or "dual"
        if lisn_mode != "dual":
            return_net = str(wiring_cfg.get("dut_return_net", "0") or "0")

    topology = None
    if user_fragment_path is not None and Path(user_fragment_path).is_file():
        try:
            from emc_assistant.netlist.topology import analyse_fragment

            topology = analyse_fragment(Path(user_fragment_path))
        except Exception as exc:  # noqa: BLE001
            _log.warning(
                f"[parasitics] topology analysis failed (shunt plan): {exc}"
            )
    if topology is None:
        return []

    from emc_assistant.netlist.fragment import series_pre_net

    injection_nets = tuple(
        inj.nets[1]
        for inj in (injection_plan or [])
        if inj.subckt_name == "TRACE_RLC" and len(inj.nets) >= 2
    )
    excluded = (
        injection_nets
        + tuple(series_nets)
        + tuple(series_pre_net(n) for n in series_nets)
    )

    from emc_assistant.agents.base import AgentInputs
    from emc_assistant.agents.parasitics_agent import ParasiticsAgent

    inputs = AgentInputs(
        problem_context=ProblemContext(
            project_id="parasitics-shunt-plan",
            analysis_scope="conducted_emi",
            has_layout=False,
            has_stackup=False,
        ),
        topology=topology,
    )
    shunt = ParasiticsAgent().default_shunt_plan(
        inputs, return_net=return_net, series_nets=excluded, overrides=overrides,
    )
    if shunt:
        n_ov = sum(1 for s in shunt if s.source == "project_override")
        _log.info(
            f"[parasitics] per-net shunt plan: {len(shunt)} net(s) get a shunt C "
            f"({n_ov} project-override, {len(shunt) - n_ov} rule-of-thumb)."
        )
    return shunt


def resolve_series_parasitics(
    user_context: dict, options: CommandOptions, fragment_path: Path | None,
) -> tuple[list, list]:
    """Resolve the M2.10.6 per-net series-parasitic plan.

    Returns ``(series_nets, series_plan)``.
    """
    if options.resolved_series_plan is not _UNSET:
        plan = list(options.resolved_series_plan)
        return [s.net for s in plan], plan
    if options.no_parasitics:
        return [], []
    if not options.accept_parasitics:
        return [], []

    overrides: dict = {}
    para_cfg = (user_context or {}).get("parasitics")
    if isinstance(para_cfg, dict):
        if para_cfg.get("skip_all"):
            return [], []
        per_net = para_cfg.get("per_net")
        if isinstance(per_net, dict):
            overrides = {str(k): v for k, v in per_net.items() if isinstance(v, dict)}

    return_net = "DUT_GND"
    supply_net = ""
    wiring_cfg = (user_context or {}).get("testbench_wiring")
    if isinstance(wiring_cfg, dict):
        lisn_mode = str(wiring_cfg.get("lisn_mode", "dual")).strip().lower() or "dual"
        if lisn_mode != "dual":
            return_net = str(wiring_cfg.get("dut_return_net", "0") or "0")
        supply_net = str(wiring_cfg.get("dut_supply_net", "") or "")

    if fragment_path is None or not Path(fragment_path).is_file():
        return [], []
    try:
        from emc_assistant.netlist.topology import analyse_fragment

        topology = analyse_fragment(Path(fragment_path))
    except Exception as exc:  # noqa: BLE001
        _log.warning(f"[parasitics] topology analysis failed (series plan): {exc}")
        return [], []

    from emc_assistant.agents.base import AgentInputs
    from emc_assistant.agents.parasitics_agent import ParasiticsAgent

    inputs = AgentInputs(
        problem_context=ProblemContext(
            project_id="parasitics-series-plan",
            analysis_scope="conducted_emi",
            has_layout=False,
            has_stackup=False,
        ),
        topology=topology,
    )
    plan = ParasiticsAgent().default_series_plan(
        inputs,
        return_net=return_net,
        exclude_nets=(supply_net,) if supply_net else (),
        overrides=overrides,
    )
    if plan:
        n_ov = sum(1 for s in plan if s.source == "project_override")
        _log.info(
            f"[parasitics] per-net series plan: {len(plan)} clean 2-element "
            f"net(s) get a series R+L+C splice ({n_ov} project-override, "
            f"{len(plan) - n_ov} rule-of-thumb)."
        )
    return [s.net for s in plan], plan


def prepare_user_fragment_with_splices(
    layout,
    user_netlist,
    *,
    strip_sources=(),
    config=None,
    rename_ground_to: str | None = None,
    user_context: dict,
    options: CommandOptions,
    inject_series: bool = True,
) -> tuple:
    """Prepare the fragment, then — if parasitics are accepted — cut its
    clean 2-element nets for series-parasitic injection (M2.10.6).

    Returns ``(fragment_path, series_nets, series_plan, series_dropped)``.
    """
    fragment = prepare_user_fragment(
        layout, user_netlist, strip_sources=strip_sources, config=config,
        rename_ground_to=rename_ground_to,
    )
    if fragment is None:
        return None, [], [], []
    series_nets, series_plan = resolve_series_parasitics(
        user_context, options, fragment
    )
    series_dropped: list = []
    # LLM negligibility screen — only on a freshly resolved plan (a child
    # step reads the parent's already-screened plan from the options).
    if series_plan and options.resolved_series_plan is _UNSET:
        series_plan, series_dropped = filter_negligible(
            series_plan, "series", options=options, layout=layout,
            config=config, user_context=user_context,
        )
        series_nets = [s.net for s in series_plan]
    if series_nets and inject_series:
        fragment = prepare_user_fragment(
            layout, user_netlist, strip_sources=strip_sources, config=config,
            rename_ground_to=rename_ground_to, series_split_nets=series_nets,
        )
        _log.info(
            f"  fragment: series-splice cut {len(series_nets)} net(s): "
            f"{', '.join(series_nets)}"
        )
    elif series_nets and not inject_series:
        _log.info(
            f"  parasitics: --parasitics-report-only — {len(series_nets)} series "
            "+ shunt parasitics estimated for the report but NOT injected into "
            "testbench.cir."
        )
    return fragment, series_nets, series_plan, series_dropped
