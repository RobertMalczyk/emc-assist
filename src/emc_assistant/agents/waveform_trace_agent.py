"""Waveform-trace suggestion agent (M2.18).

Picks the comparison traces shown in the Results screen's time-domain
waveform analyzer. The analyzer stacks two time-aligned panels: the
primary measured voltage ``V(meas)`` on top, and one selectable
comparison trace below. The default comparison trace is the load current
``I(Rload)``; the user can switch it to one of four further traces that
this agent deduces are most relevant for correlating circuit behaviour
with the measured conducted-EMI voltage.

- **Default** is fixed (the load current) — resolved deterministically
  from the available ``.raw`` traces, never the LLM.
- **The four other choices** come from the LLM when one is configured
  (``--llm openai`` / cloud LLM on), and from a topology-aware heuristic
  otherwise. Any LLM error / malformed reply / unknown trace falls back to
  the heuristic (fail-safe).

This is a small UI-support deduction, not a post-simulation report agent,
so it does not implement the :class:`~emc_assistant.agents.base.Agent`
fan-out contract. It only ever selects *which traces to plot* — a
visualization aid; it fabricates no values and makes no compliance claim.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from emc_assistant.agents.base import PROMPTS_AGENTS_DIR, parse_json_object

_UNIT_BY_KIND = {
    "voltage": "V",
    "device_current": "A",
    "subckt_current": "A",
    "current": "A",
}


def _unit_for_kind(kind: str) -> str:
    return _UNIT_BY_KIND.get((kind or "").strip().lower(), "")


@dataclass
class TraceChoice:
    """One selectable trace in the comparison-subplot dropdown."""

    trace: str
    label: str
    unit: str
    reason: str
    source: str  # "default" | "llm" | "deterministic"

    def to_dict(self) -> dict:
        return {
            "trace": self.trace,
            "label": self.label,
            "unit": self.unit,
            "reason": self.reason,
            "source": self.source,
        }


@dataclass
class WaveformTraceSuggestions:
    default: TraceChoice
    suggestions: list[TraceChoice]  # the 4 comparison choices (excl. default & primary)
    llm_generated: bool

    def to_dict(self) -> dict:
        opts = [self.default.to_dict()] + [s.to_dict() for s in self.suggestions]
        return {
            "default": self.default.to_dict(),
            "suggestions": [s.to_dict() for s in self.suggestions],
            "options": opts,  # selector order: default first, then the four
            "llm_generated": self.llm_generated,
        }


class WaveformTraceAgent:
    name = "waveform_trace"
    prompt_filename = "waveform_trace_agent.md"
    n_suggestions = 4

    @property
    def prompt_path(self):
        return PROMPTS_AGENTS_DIR / self.prompt_filename

    # ------------------------------------------------------------------
    # Primary entry point
    # ------------------------------------------------------------------

    def suggest(
        self,
        *,
        available_traces: list[str],
        kinds: dict[str, str],
        primary_trace: str = "V(meas)",
        topology: Any = None,
        problem_context: Any = None,
        signals: Any = None,
        assistant: Any = None,
    ) -> WaveformTraceSuggestions:
        avail = [t for t in available_traces if t and t.strip().lower() != "time"]
        lower = {t.lower(): t for t in avail}
        kind_lower = {k.lower(): v for k, v in (kinds or {}).items()}

        default = self._resolve_default(lower, kind_lower)
        exclude = {primary_trace.lower(), default.trace.lower()}

        if assistant is not None and getattr(assistant, "name", "") != "deterministic":
            try:
                sugg = self._llm_suggestions(
                    avail, kind_lower, lower, primary_trace, default,
                    topology, problem_context, signals, assistant, exclude,
                )
                if len(sugg) < self.n_suggestions:
                    seen = exclude | {s.trace.lower() for s in sugg}
                    sugg += self._heuristic_suggestions(lower, kind_lower, topology, seen)
                return WaveformTraceSuggestions(
                    default=default,
                    suggestions=sugg[: self.n_suggestions],
                    llm_generated=True,
                )
            except Exception:  # noqa: BLE001 — fail-safe to the heuristic
                pass

        sugg = self._heuristic_suggestions(lower, kind_lower, topology, set(exclude))
        return WaveformTraceSuggestions(
            default=default,
            suggestions=sugg[: self.n_suggestions],
            llm_generated=False,
        )

    # ------------------------------------------------------------------
    # Default trace (deterministic — fixed to the load current)
    # ------------------------------------------------------------------

    def _resolve_default(self, lower: dict, kind_lower: dict) -> TraceChoice:
        load_reason = "Current delivered to the load — the converter's output behaviour."
        for cand in ("i(rload)", "i(rout)", "i(rl)", "i(r_load)"):
            if cand in lower:
                return self._choice(lower[cand], "Load current", load_reason, "default", kind_lower)
        # any non-parasitic resistor current as a load proxy
        for nl in lower:
            if nl.startswith("i(r") and "_par" not in nl:
                return self._choice(lower[nl], "Load current", "Current through the load resistor.", "default", kind_lower)
        # no load-current trace -> fall back to the load-node voltage
        for cand in ("v(vout)", "v(out)"):
            if cand in lower:
                return self._choice(lower[cand], "Output voltage", "Load voltage (no load-current trace was saved).", "default", kind_lower)
        # last resorts: first current, then first voltage, then anything
        for nl in lower:
            if "current" in kind_lower.get(nl, ""):
                return self._choice(lower[nl], lower[nl], "Default comparison trace.", "default", kind_lower)
        for nl in lower:
            if "voltage" in kind_lower.get(nl, ""):
                return self._choice(lower[nl], lower[nl], "Default comparison trace.", "default", kind_lower)
        any_name = next(iter(lower.values()), "")
        return self._choice(any_name, any_name or "(none)", "Default comparison trace.", "default", kind_lower)

    # ------------------------------------------------------------------
    # Heuristic comparison traces (deterministic fallback / padding)
    # ------------------------------------------------------------------

    def _heuristic_suggestions(self, lower, kind_lower, topology, seen) -> list[TraceChoice]:
        out: list[TraceChoice] = []

        def add(name_lower: str, label: str, reason: str) -> None:
            if not name_lower or name_lower in seen or name_lower not in lower:
                return
            seen.add(name_lower)
            out.append(self._choice(lower[name_lower], label, reason, "deterministic", kind_lower))

        # 1. Supply / input current — the conducted-EMI source current.
        add("i(v_rail)", "Input current",
            "Total current drawn through the LISN from the supply — the conducted-EMI source current.")

        # 2. A switching-node voltage (or a switch device current).
        sw = False
        for net in (getattr(topology, "switching_node_candidates", None) or []):
            nl = f"v({str(net).lower()})"
            if nl in lower and nl not in seen:
                add(nl, f"Switching node {lower[nl]}",
                    "Fast dv/dt switching edge — the primary broadband EMI source.")
                sw = True
                break
        if not sw:
            for cand in ("id(m1)", "is(m1)", "id(m2)", "id(q1)"):
                if cand in lower and cand not in seen:
                    add(cand, "Switch current", "Switch (FET) current — switching-loop di/dt.")
                    break

        # 3. Main inductor current (skip the parasitic L_par_* branches).
        ind = next(
            (n for n in lower if n.startswith("i(l") and "_par" not in n),
            None,
        )
        if ind:
            add(ind, f"Inductor current {lower[ind]}", "Main inductor ripple current.")

        # 4. CM / DM probe.
        if "v(cm)" in lower and "v(cm)" not in seen:
            add("v(cm)", "CM probe", "Common-mode noise component (V_cm).")
        elif "v(dm)" in lower and "v(dm)" not in seen:
            add("v(dm)", "DM probe", "Differential-mode noise component (V_dm).")

        # Fill toward four with sensible rails.
        for nl, label, reason in (
            ("v(dm)", "DM probe", "Differential-mode noise component (V_dm)."),
            ("v(cm)", "CM probe", "Common-mode noise component (V_cm)."),
            ("v(vin)", "Input voltage", "Supply rail voltage into the DUT."),
            ("v(hv_in_rail)", "Input rail voltage", "Supply rail voltage into the DUT."),
            ("v(vout)", "Output voltage", "Converter output voltage."),
            ("v(out)", "Output voltage", "Converter output voltage."),
        ):
            if len(out) >= self.n_suggestions:
                break
            add(nl, label, reason)

        # Last-ditch fill: any remaining voltage, then any remaining trace.
        if len(out) < self.n_suggestions:
            for nl in sorted(lower):
                if len(out) >= self.n_suggestions:
                    break
                if "voltage" in kind_lower.get(nl, ""):
                    add(nl, lower[nl], "Additional trace.")
        if len(out) < self.n_suggestions:
            for nl in sorted(lower):
                if len(out) >= self.n_suggestions:
                    break
                add(nl, lower[nl], "Additional trace.")
        return out

    # ------------------------------------------------------------------
    # LLM path
    # ------------------------------------------------------------------

    def _llm_suggestions(
        self, avail, kind_lower, lower, primary, default,
        topology, problem_context, signals, assistant, exclude,
    ) -> list[TraceChoice]:
        raw = assistant.complete(
            messages=self._messages(avail, kind_lower, primary, default, topology, problem_context, signals),
            purpose=f"agent.{self.name}",
            expected_output_tokens=500,
        )
        data = parse_json_object(raw)
        items = data.get("suggestions") or data.get("traces") or []
        out: list[TraceChoice] = []
        seen = set(exclude)
        for it in items:
            if len(out) >= self.n_suggestions:
                break
            if not isinstance(it, dict):
                continue
            name = str(it.get("trace", "")).strip()
            nl = name.lower()
            if not nl or nl in seen or nl not in lower:
                continue  # drop unknown / duplicate / excluded traces
            seen.add(nl)
            reason = str(it.get("reason", "")).strip() or "LLM-selected comparison trace."
            label = str(it.get("label", "")).strip() or lower[nl]
            out.append(self._choice(lower[nl], label, reason, "llm", kind_lower))
        return out

    def _messages(self, avail, kind_lower, primary, default, topology, problem_context, signals):
        system = self.prompt_path.read_text(encoding="utf-8")
        payload: dict[str, Any] = {
            "primary_trace": primary,
            "fixed_default_comparison_trace": default.trace,
            "n_requested": self.n_suggestions,
            "available_traces": [
                {"trace": t, "kind": kind_lower.get(t.lower(), "")} for t in avail
            ],
            "topology": topology.to_schema_dict() if topology is not None else None,
            "problem_context": {
                "project_type": getattr(problem_context, "topology", ""),
                "switching_frequency_hz": getattr(problem_context, "switching_frequency_hz", None),
                "problem_hypothesis": getattr(problem_context, "problem_hypothesis", ""),
            },
            "user_signals": signals if isinstance(signals, list) else None,
        }
        user = (
            "Choose the comparison traces for the time-domain waveform analyzer.\n\n"
            + json.dumps(payload, indent=1, ensure_ascii=True)
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    # ------------------------------------------------------------------

    def _choice(self, exact, label, reason, source, kind_lower) -> TraceChoice:
        unit = _unit_for_kind(kind_lower.get((exact or "").lower(), ""))
        return TraceChoice(trace=exact, label=label or exact, unit=unit, reason=reason, source=source)
