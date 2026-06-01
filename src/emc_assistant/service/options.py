"""``CommandOptions`` — the typed parameter object for the orchestration
service functions (compose / variants / simulate / report / pipeline).

The CLI builds one from its ``argparse.Namespace``; the M3 UI builds one
directly. It also carries *pre-resolved* decisions: the pipeline resolves
wiring / parasitics / signals once and threads them to each sub-step via
:meth:`child` (replacing the old ``args._resolved_*`` stash).
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

# Sentinel: a resolved-decision field still at _UNSET has not been
# pre-resolved by a parent step, so the step resolves it itself.
_UNSET: Any = object()


@dataclass
class CommandOptions:
    # --- explicit user flags -------------------------------------------------
    accept_wiring: bool = False
    no_wiring: bool = False
    accept_parasitics: bool = False
    no_parasitics: bool = False
    accept_signals: bool = False
    no_signals: bool = False
    parasitics_report_only: bool = False
    no_asc_export: bool = False
    mode: str | None = None
    rank_metric: str | None = None
    lower_is_better: bool = True
    html: bool = False
    pdf: bool = False
    # --- LLM -----------------------------------------------------------------
    llm: str = "none"
    llm_mode: str = "replace"
    llm_budget_usd: float = 1.0
    llm_model: str | None = None
    llm_top_k: int = 5
    # --- pre-resolved decisions (parent → child); _UNSET = resolve here ------
    resolved_wiring: Any = _UNSET
    resolved_strip: Any = _UNSET
    resolved_injection_plan: Any = _UNSET
    resolved_shunt_plan: Any = _UNSET
    resolved_series_plan: Any = _UNSET
    resolved_signals: Any = _UNSET
    # --- test hooks ----------------------------------------------------------
    stub_assistant: Any = None
    stub_embedder: Any = None

    @classmethod
    def from_namespace(cls, args) -> "CommandOptions":
        """Build options from a CLI ``argparse.Namespace`` (tolerant of
        missing attributes — each command parser only defines a subset)."""
        def g(name, default):
            return getattr(args, name, default)

        opts = cls(
            accept_wiring=g("accept_wiring", False),
            no_wiring=g("no_wiring", False),
            accept_parasitics=g("accept_parasitics", False),
            no_parasitics=g("no_parasitics", False),
            accept_signals=g("accept_signals", False),
            no_signals=g("no_signals", False),
            parasitics_report_only=g("parasitics_report_only", False),
            no_asc_export=g("no_asc_export", False),
            mode=g("mode", None),
            rank_metric=g("rank_metric", None),
            lower_is_better=bool(g("lower_is_better", True)),
            html=bool(g("html", False)),
            pdf=bool(g("pdf", False)),
            llm=g("llm", "none") or "none",
            llm_mode=g("llm_mode", "replace") or "replace",
            llm_budget_usd=float(g("llm_budget_usd", 1.0)),
            llm_model=g("llm_model", None),
            llm_top_k=int(g("llm_top_k", 5)),
            stub_assistant=g("_stub_assistant", None),
            stub_embedder=g("_stub_embedder", None),
        )
        # A parent command (or a test) may have stashed resolved decisions.
        for src, dst in (
            ("_resolved_wiring", "resolved_wiring"),
            ("_resolved_strip", "resolved_strip"),
            ("_resolved_injection_plan", "resolved_injection_plan"),
            ("_resolved_shunt_plan", "resolved_shunt_plan"),
            ("_resolved_series_plan", "resolved_series_plan"),
            ("_resolved_signals", "resolved_signals"),
        ):
            if hasattr(args, src):
                setattr(opts, dst, getattr(args, src))
        return opts

    def child(self, **overrides) -> "CommandOptions":
        """A copy with some fields overridden — used by the pipeline to
        thread pre-resolved decisions into each sub-step."""
        return replace(self, **overrides)
