"""The Python ⇄ JS bridge — the ``Api`` object the UI page calls.

pywebview exposes an :class:`Api` instance to the page as
``window.pywebview.api``; each public method is callable from JS and
returns a Promise. Every method is a thin wrapper over one
``emc_assistant.service`` use case — it does three things and nothing
else:

1. translate JS arguments into service parameters,
2. convert the typed service result into plain JSON, and
3. turn a :class:`ServiceError` into a structured error object.

So every call returns ``{"ok": True, "data": …}`` or
``{"ok": False, "error": {"message", "exit_code", "details"}}``. An
unexpected bug is *not* swallowed — it propagates (the UI surfaces it as
a rejected promise), matching how ``cli.py`` only catches ``ServiceError``.

See ``docs/design/ui_integration.md``.
"""

from __future__ import annotations

import dataclasses
import json
import math
from pathlib import Path

from emc_assistant import __version__, service
from emc_assistant.service import CommandOptions, ServiceError

_OPTION_FIELDS = {f.name for f in dataclasses.fields(CommandOptions)}


def _jsonable(obj):
    """Recursively convert a service result (dataclasses, Paths, lists)
    into a plain JSON-serialisable structure."""
    if dataclasses.is_dataclass(obj) and not isinstance(obj, type):
        return {
            f.name: _jsonable(getattr(obj, f.name))
            for f in dataclasses.fields(obj)
        }
    if isinstance(obj, dict):
        return {str(k): _jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, Path):
        return str(obj)
    if isinstance(obj, float):
        # JS `JSON.parse` rejects NaN / Infinity, but Python's `json.dumps`
        # (which pywebview uses to ship the return value) emits them as bare
        # tokens — one such value makes the WHOLE payload invalid and blanks
        # the chart. Null them so the payload is always valid JSON; the UI
        # already skips null points.
        return obj if math.isfinite(obj) else None
    if obj is None or isinstance(obj, (str, int, bool)):
        return obj
    return str(obj)


def _ok(data) -> dict:
    return {"ok": True, "data": _jsonable(data)}


def _err(exc: ServiceError) -> dict:
    return {
        "ok": False,
        "error": {
            "message": exc.message,
            "exit_code": exc.exit_code,
            "details": list(exc.details),
        },
    }


def _call(fn, *args, **kwargs) -> dict:
    """Invoke a service function; map result / ServiceError to the
    bridge's response envelope."""
    try:
        return _ok(fn(*args, **kwargs))
    except ServiceError as exc:
        return _err(exc)


def _pick(*, folder: bool, dialog_title: str) -> dict:
    """Open pywebview's native open-dialog (folder or file) and return
    ``{"ok": True, "data": {"path": <abs> | None}}``. A picker failure
    never crashes the UI — it returns a :class:`ServiceError` envelope."""
    try:
        import webview

        window = webview.windows[0] if webview.windows else None
        if window is None:
            return _err(ServiceError("no pywebview window is active"))
        dialog = webview.FOLDER_DIALOG if folder else webview.OPEN_DIALOG
        result = window.create_file_dialog(dialog, allow_multiple=False)
    except Exception as exc:  # noqa: BLE001 — picker must never crash the UI
        return _err(ServiceError(f"file picker failed: {exc}"))
    if not result:
        return {"ok": True, "data": {"path": None}}
    path = result[0] if isinstance(result, (list, tuple)) else result
    return {"ok": True, "data": {"path": str(path)}}


def _options(raw: dict | None) -> CommandOptions:
    """Build a CommandOptions from a plain dict, ignoring unknown keys
    (and never accepting the internal resolved_*/stub_* fields from JS)."""
    raw = raw or {}
    safe = {
        k: v
        for k, v in raw.items()
        if k in _OPTION_FIELDS and not k.startswith(("resolved_", "stub_"))
    }
    return CommandOptions(**safe)


def _cloud_llm_active() -> bool:
    """Cloud LLM is usable only when the user opted in AND a key resolves.

    This is the single gate: the persisted ``cloud_llm_enabled`` flag is a
    *request*; without a resolvable API key (env or key file) the run stays
    deterministic regardless of the flag. So "proper key → on, otherwise
    off"."""
    from emc_assistant.service import settings as settings_service

    if not settings_service.load_settings().cloud_llm_enabled:
        return False
    from emc_assistant.llm.openai_provider import resolve_api_key

    return resolve_api_key() is not None


def _run_options(raw: dict | None) -> CommandOptions:
    """Build CommandOptions for a run-style call, overlaying the saved
    cloud-LLM settings.

    When the user enabled cloud LLM AND a key resolves, route the run
    through OpenAI (model + budget from settings) — unless the caller
    already chose an ``llm`` explicitly. No key or not enabled → the run
    stays ``llm="none"`` (deterministic)."""
    opts = _options(raw)
    if ((raw or {}).get("llm") or "none") != "none":
        return opts  # an explicit caller choice wins over the global setting
    if _cloud_llm_active():
        from emc_assistant.service import settings as settings_service

        st = settings_service.load_settings()
        opts.llm = "openai"
        opts.llm_budget_usd = float(st.llm_budget_usd or opts.llm_budget_usd)
        if st.llm_model:
            opts.llm_model = st.llm_model
    return opts


class Api:
    """The JS-callable bridge. One method per UI action / read."""

    # --- smoke / meta -------------------------------------------------------

    def ping(self) -> dict:
        """Connectivity check for the page on startup."""
        return {"ok": True, "data": {"pong": True, "version": __version__}}

    def pick_folder(self, dialog_title: str = "Open project folder") -> dict:
        """Open pywebview's native folder picker; return the chosen path
        as ``{"path": "<abs path>"}``, or ``{"path": null}`` if cancelled."""
        return _pick(folder=True, dialog_title=dialog_title)

    def pick_file(self, dialog_title: str = "Open file") -> dict:
        """Open pywebview's native file picker; return the chosen path as
        ``{"path": "<abs path>"}``, or ``{"path": null}`` if cancelled.
        File-type filtering is left to the UI prompt — pywebview's filter
        syntax is platform-specific and the bridge stays general."""
        return _pick(folder=False, dialog_title=dialog_title)

    # --- settings -----------------------------------------------------------

    def load_settings(self) -> dict:
        """Return the full app-level settings dict (UI keys included).
        Missing / corrupt file -> ``{}``."""
        from emc_assistant.service import settings as settings_service

        return {"ok": True, "data": settings_service.load_settings_raw()}

    def save_settings(self, updates: dict | None = None) -> dict:
        """Merge ``updates`` into the on-disk settings and persist; return
        the resulting full dict. UI-only keys (theme / density / accent…)
        round-trip untouched alongside the backend-relevant fields."""
        from emc_assistant.service import settings as settings_service

        try:
            merged = settings_service.save_settings(updates or {})
        except OSError as exc:
            return _err(ServiceError(f"could not save settings: {exc}"))
        return {"ok": True, "data": merged}

    def llm_status(self) -> dict:
        """Cloud-LLM readiness for the UI.

        ``key_present``  — an API key resolves (env or key file).
        ``enabled``      — the user opted in (persisted ``cloud_llm_enabled``).
        ``effective``    — both true → the pipeline will actually use the LLM.
        The Settings toggle gates on ``key_present``; the indicator and the
        parasitics "AI: suggest negligible" button gate on ``effective``."""
        from emc_assistant.llm.openai_provider import resolve_api_key
        from emc_assistant.service import settings as settings_service

        st = settings_service.load_settings()
        key_present = resolve_api_key() is not None
        enabled = bool(st.cloud_llm_enabled)
        return {
            "ok": True,
            "data": {
                "key_present": key_present,
                "enabled": enabled,
                "effective": enabled and key_present,
                "model": st.llm_model or "",
                "budget_usd": float(st.llm_budget_usd),
            },
        }

    def detect_ltspice(self) -> dict:
        """Resolve a local LTspice install (configured path -> env ->
        common paths -> ``which``). Returns ``{"path": "<abs>"}`` or
        ``{"path": null}``; pulls the configured path from
        :func:`service.settings.load_settings`."""
        from emc_assistant.ltspice.adapter import discover_ltspice
        from emc_assistant.service import settings as settings_service

        configured = settings_service.load_settings().ltspice_path or None
        found = discover_ltspice(configured)
        return {"ok": True, "data": {"path": str(found) if found else None}}

    # --- projects -----------------------------------------------------------

    def list_projects(self, root_dir: str) -> dict:
        """Scan a directory for ``*/project.yaml`` (UI-side, no command)."""
        base = Path(root_dir)
        found = []
        if base.is_dir():
            for cfg in sorted(base.glob("*/project.yaml")):
                found.append({"name": cfg.parent.name, "path": str(cfg.parent)})
        return {"ok": True, "data": found}

    def create_project(self, project_root: str) -> dict:
        return _call(service.project.create_project, project_root)

    def set_schematic(self, project_root: str, source_path: str) -> dict:
        """Drop a schematic into a project — copy into ``<project>/input/``
        and update ``project.yaml``. Returns the new netlist / schematic
        relative paths and whether a copy actually happened."""
        return _call(service.project.set_schematic, project_root, source_path)

    def validate_project(self, project_root: str) -> dict:
        return _call(service.project.validate_project, project_root)

    def project_status(self, project_root: str) -> dict:
        return _call(service.project.get_project_status, project_root)

    def project_inputs(self, project_root: str) -> dict:
        """Return ``project.yaml``'s ``inputs`` block (``netlist_path`` /
        ``schematic_path`` / ``models_dir``) — the UI's Import screen shows
        the configured schematic filename from here."""
        try:
            config, _layout = service.project.require_project(project_root)
        except ServiceError as exc:
            return _err(exc)
        return _ok(dict(config.inputs))

    # --- circuit context ----------------------------------------------------

    def load_context(self, project_root: str) -> dict:
        try:
            _config, layout = service.project.require_project(project_root)
        except ServiceError as exc:
            return _err(exc)
        return {"ok": True, "data": service.context.load_user_context(layout)}

    def save_context(self, project_root: str, context: dict) -> dict:
        return _call(service.context.save_user_context, project_root, context)

    # --- parasitics ---------------------------------------------------------

    def estimate_parasitics(self, project_root: str) -> dict:
        return _call(service.parasitics.estimate_parasitics, project_root)

    def estimate_per_net(self, project_root: str) -> dict:
        return _call(service.parasitics.estimate_per_net, project_root)

    def suggest_negligible(self, project_root: str, options: dict | None = None) -> dict:
        """Run the M2.10.7 LLM negligibility screen on the per-net plan and
        return the nets it judges negligible (``{dropped:[{net,kind,reason}],
        considered:int}``). Requires cloud LLM active (enabled + key); the
        service raises a ``ServiceError`` otherwise so the UI can prompt."""
        raw = dict(options or {})
        raw.setdefault("accept_parasitics", True)
        raw.setdefault("accept_wiring", True)
        return _call(
            service.parasitics.suggest_negligible, project_root, _run_options(raw)
        )

    def reevaluate_parasitics(self, project_root: str, apply: bool = False) -> dict:
        """M2.17 — LLM/RAG re-evaluation of per-net parasitic values. Refines
        the deterministic bands into citation-backed min/typ/max proposals
        (written to ``generated/parasitics_reevaluated.json``); with
        ``apply=True`` persists only the refined typ values as user overrides.
        Requires cloud LLM active; the service raises ``ServiceError`` otherwise."""
        return _call(
            service.parasitics.reevaluate_parasitics,
            project_root, _run_options(None), apply=bool(apply),
        )

    def apply_reevaluated_parasitics(self, project_root: str) -> dict:
        """Accept step after a preview re-evaluation: persist the refined typ
        values from ``generated/parasitics_reevaluated.json`` as
        ``user_context.parasitics.per_net`` overrides. No LLM call. Returns
        ``{applied:int}``."""
        return _call(service.parasitics.apply_reevaluated_parasitics, project_root)

    # --- testbench / variants / simulate ------------------------------------

    def assess_simulation(self, project_root: str, overrides: dict | None = None) -> dict:
        """Deterministic check of .tran window/timestep vs the conducted-EMI
        band + switching edges. ``overrides`` None → the project's saved
        settings; pass proposed settings to review them before saving (the
        Run-screen edit loop). Returns the assessment (ok + per-check)."""
        return _call(service.testbench.assess_simulation, project_root, overrides)

    def load_simulation_settings(self, project_root: str) -> dict:
        """The project's effective simulation settings for the Run-screen
        panel (incl. the seconds the run will actually use)."""
        return _call(service.testbench.load_simulation_settings, project_root)

    def save_simulation_settings(self, project_root: str, settings: dict) -> dict:
        """Persist the panel's structured simulation settings into
        user_context.simulation (validated). Returns the reloaded settings."""
        return _call(service.testbench.save_simulation_settings, project_root, settings)

    def compose_testbench(self, project_root: str, options: dict | None = None) -> dict:
        return _call(
            service.testbench.compose_testbench, project_root, _run_options(options)
        )

    def compose_variants(self, project_root: str, options: dict | None = None) -> dict:
        return _call(
            service.testbench.compose_variants, project_root, _run_options(options)
        )

    def run_variants(self, project_root: str, options: dict | None = None) -> dict:
        return _call(service.simulate.run_variants, project_root, _run_options(options))

    def run_testbench(self, project_root: str, options: dict | None = None) -> dict:
        return _call(service.simulate.run_testbench, project_root, _run_options(options))

    # --- report / pipeline --------------------------------------------------

    def load_results(self, project_root: str) -> dict:
        """Aggregate a completed run for the Results screen: the diagnostic
        narrative + corner-variant ranking + headline metrics. Degrades
        gracefully (has_metrics False before a local-run)."""
        return _call(service.report.load_results, project_root)

    def generate_report(self, project_root: str, options: dict | None = None) -> dict:
        return _call(
            service.report.generate_report, project_root, _run_options(options)
        )

    def run_pipeline(self, project_root: str, options: dict | None = None) -> dict:
        return _call(service.pipeline.run_pipeline, project_root, _run_options(options))

    def cancel_run(self) -> dict:
        """Request a cooperative cancel of the running pipeline. The
        pipeline finishes its current stage and then aborts (with a
        :class:`RunCancelled` ``ServiceError``); the cancel is **not** a
        subprocess kill — an in-flight LTspice run is allowed to finish
        so partial ``.raw`` files are not orphaned."""
        service.pipeline.request_cancel()
        return {"ok": True, "data": {"requested": True}}

    # --- recommendations ----------------------------------------------------

    def list_recommendations(self, project_root: str) -> dict:
        return _call(service.recommendations.list_recommendations, project_root)

    def accept_recommendation(
        self, project_root: str, key: str, reason: str = ""
    ) -> dict:
        return _call(
            service.recommendations.decide_recommendation,
            project_root, key, "accepted", reason,
        )

    def reject_recommendation(
        self, project_root: str, key: str, reason: str = ""
    ) -> dict:
        return _call(
            service.recommendations.decide_recommendation,
            project_root, key, "rejected", reason,
        )

    # --- netlist / raw ------------------------------------------------------

    def inspect_netlist(self, project_root: str) -> dict:
        return _call(service.netlist.inspect_netlist, project_root)

    def inspect_raw(self, raw_path: str) -> dict:
        return _call(service.raw.inspect_raw, raw_path)

    def export_raw_csv(
        self, raw_path: str, traces: list[str], output_path: str
    ) -> dict:
        return _call(
            service.raw.export_raw_csv, raw_path, traces or [], output_path
        )

    def quasi_peak(
        self,
        raw_path: str,
        center_hz: float,
        trace: str | None = None,
        standard_id: str | None = None,
    ) -> dict:
        """Mode 2 — receiver-like quasi-peak at one frequency + margin."""
        return _call(
            service.raw.quasi_peak, raw_path,
            center_hz=center_hz, trace=trace, standard_id=standard_id,
        )

    def quasi_peak_sweep(
        self,
        raw_path: str,
        trace: str | None = None,
        standard_id: str | None = None,
        n_points: int = 128,
    ) -> dict:
        """Mode 3 — receiver-like quasi-peak sweep across CISPR Band B."""
        return _call(
            service.raw.quasi_peak_sweep, raw_path,
            trace=trace, standard_id=standard_id, n_points=n_points,
        )

    def load_spectrum(self, project_root: str) -> dict:
        """Detector-vs-limit spectrum (peak/QP/average dBµV per frequency +
        the compliance limit curves) from the run's ``.raw`` — the curves the
        Results numbers are read off. Cached; ``{available:false}`` before a
        local-run. The first call may take a few seconds (the sweep)."""
        return _call(service.raw.load_spectrum, project_root)

    def load_waveform(self, project_root: str, trace: str | None = None) -> dict:
        """A min/max envelope of a run's ``.raw`` trace, downsampled for
        plotting (peaks preserved). ``trace`` None → the measured voltage
        ``V(meas)`` (top panel); pass a name for the comparison subplot.
        Cached per trace; ``{available:false}`` before a local-run."""
        return _call(service.raw.load_waveform, project_root, trace=trace)

    def suggest_waveform_traces(self, project_root: str) -> dict:
        """Comparison-subplot trace choices for the waveform analyzer: a
        fixed default (load current) + four relevant traces, LLM-deduced
        when cloud LLM is on, topology heuristic otherwise. Cached."""
        return _call(
            service.waveform.suggest_waveform_traces, project_root, _run_options(None)
        )

    # --- generic artifact read ----------------------------------------------

    def read_artifact(self, project_root: str, rel_path: str) -> dict:
        """Read a JSON / text artifact from inside the ``.emcproj`` folder.

        Path-guarded — ``rel_path`` may not escape the project directory.
        """
        root = Path(project_root).resolve()
        target = (root / rel_path).resolve()
        try:
            target.relative_to(root)
        except ValueError:
            return {
                "ok": False,
                "error": {
                    "message": "path escapes the project directory",
                    "exit_code": 1,
                    "details": [],
                },
            }
        if not target.is_file():
            return {
                "ok": False,
                "error": {
                    "message": f"artifact not found: {rel_path}",
                    "exit_code": 1,
                    "details": [],
                },
            }
        text = target.read_text(encoding="utf-8")
        if target.suffix.lower() == ".json":
            return {"ok": True, "data": json.loads(text)}
        return {"ok": True, "data": text}
