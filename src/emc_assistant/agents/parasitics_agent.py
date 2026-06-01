"""Parasitics specialist agent.

M2.9 role: explains the deterministic calculators' output, flags wide
bands, proposes sweep selections.

M2.10 extension: also emits a parasitic-injection plan — a list of
:class:`ParasiticInjection` entries proposing which composer-generated
subcircuits (TRACE_RLC, VIA_L, CAP_ESR_ESL) to splice into
``testbench.cir`` between the LISN/cable and the user fragment. The
agent reads :class:`emc_assistant.netlist.topology.TopologyReport`
from the context and picks net names from there.
"""

from __future__ import annotations

import json
from typing import Any

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    SimulationRequest,
    parse_json_object,
    select_metrics_by_prefix,
)
from emc_assistant.agents.injection import (
    ParasiticInjection,
    SeriesParasitic,
    ShuntParasitic,
)
from emc_assistant.logging_setup import get_logger
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.recommendations.engine import Recommendation

_log = get_logger("parasitics")

CABLE_OUT_NET: str = "n_dut_in_pre"


def _clamp01(value: Any) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.5


def _coerce_band(value: Any) -> list[float] | None:
    """Coerce an LLM-returned band into ``[min, typ, max]`` of finite,
    positive, ascending floats — or ``None`` if it isn't a usable band.

    Accepts a 3-list ``[min, typ, max]`` or a dict ``{min, typ, max}``.
    Sorts defensively so a model that returns them out of order still
    yields min <= typ <= max. Rejects non-finite / non-positive values
    (a PCB parasitic R/L/C is always > 0)."""
    import math

    if isinstance(value, dict):
        raw = [value.get("min"), value.get("typ"), value.get("max")]
    elif isinstance(value, (list, tuple)) and len(value) == 3:
        raw = list(value)
    else:
        return None
    try:
        nums = [float(x) for x in raw]
    except (TypeError, ValueError):
        return None
    if any(not math.isfinite(x) or x <= 0 for x in nums):
        return None
    nums.sort()
    return nums  # [min, typ, max]
"""M2.10 composer convention: when an injection plan is present, the
cable's downstream port lands on this net (instead of directly on the
user's supply net). The parasitics agent splices a series element
between this net and the user supply net so the parasitic actually
sits in the signal path."""


class ParasiticsAgent(Agent):
    name = "parasitics"
    area_title = "PCB and cable parasitics"
    prompt_filename = "parasitics_agent.md"
    keywords = [
        "trace",
        "via",
        "polygon",
        "plane",
        "parasitic",
        "esl",
        "esr",
        "inductance",
        "capacitance",
        "cable",
    ]
    metric_prefixes: list[str] = []

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        notes = [
            "Focus: parasitic band widths and dominant contributors.",
            "M2.10: propose at least one TRACE_RLC injection between "
            f"the composer cable output ('{CABLE_OUT_NET}') and the user supply net "
            "so the variant sweep actually moves V(MEAS).",
        ]
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, ["v_meas", "dm_", "cm_"]),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=notes,
            topology=ctx.topology,
            dut_supply_net=ctx.dut_supply_net,
            dut_return_net=ctx.dut_return_net,
        )

    def _default_injection_plan(self, inputs: AgentInputs) -> list[ParasiticInjection]:
        """Heuristic plan: splice trace L between cable output and user supply.

        Picks the user supply net from (in priority order) ``inputs.dut_supply_net``,
        then the topology report's first power-supply candidate, then the literal
        ``"in"``. Picks the trace-L parasitic id from ``inputs.parasitics``.
        Returns an empty list when no parasitic is available.
        """
        supply_net = inputs.dut_supply_net
        if not supply_net and inputs.topology is not None:
            supply_net = next(iter(inputs.topology.power_supply_candidates), "")
        if not supply_net:
            return []
        trace_l = _first(
            inputs.parasitics, structure="trace", parasitic_type="L"
        )
        if trace_l is None:
            return []
        return [
            ParasiticInjection(
                instance_name="X_TRACE_VIN",
                subckt_name="TRACE_RLC",
                nets=[CABLE_OUT_NET, supply_net, inputs.dut_return_net or "DUT_GND"],
                rationale=(
                    f"Series trace R+L+C between the cable output ({CABLE_OUT_NET}) "
                    f"and the DUT supply net ({supply_net}); puts the parasitic-L "
                    "band actually in the signal path so the variant sweep moves V(MEAS)."
                ),
                rule_id="engineering_estimate",
                parasitic_id=trace_l.id,
                corner="typ",
                agent="parasitics",
            )
        ]

    def default_shunt_plan(
        self,
        inputs: AgentInputs,
        *,
        return_net: str = "DUT_GND",
        series_nets: tuple[str, ...] = (),
        overrides: dict[str, dict] | None = None,
    ) -> list[ShuntParasitic]:
        """Per-net shunt-C plan (M2.10.5): every user net gets a parasitic.

        Walks every net of the user fragment and proposes a shunt
        capacitance to ``return_net``. A shunt C needs no clean cut
        point, so it applies to star/bus nets that cannot take a series
        splice — this is how "every single net gets a parasitic" holds.

        Excluded: the return/ground net itself (it *is* the reference),
        the composer's intermediate cable net, and any ``series_nets``
        that already receive a series TRACE_RLC (whose subckt carries
        its own shunt C). ``overrides`` is the per-net project-setup
        map: ``{net: {"skip": True}}`` drops a net, ``{net: {"c_pf": N}}``
        pins an explicit value.
        """
        if inputs.topology is None:
            return []
        from emc_assistant.parasitics.per_net import estimate_all_nets

        overrides = overrides or {}
        skip_nets = {return_net, "0", CABLE_OUT_NET, *series_nets}
        out: list[ShuntParasitic] = []
        for est in estimate_all_nets(inputs.topology):
            net = est.net
            if est.role == "return" or net in skip_nets:
                continue
            ov = overrides.get(net, {})
            if ov.get("skip"):
                continue
            if "c_pf" in ov:
                cap = float(ov["c_pf"]) * 1e-12
                source = "project_override"
                rule_id = "project_override"
            else:
                cap = est.rlc.capacitance.value
                source = "rule_of_thumb"
                rule_id = "engineering_estimate"
            if cap <= 0:
                continue
            out.append(
                ShuntParasitic(
                    net=net,
                    capacitance_f=cap,
                    return_net=return_net,
                    rule_id=rule_id,
                    source=source,
                    rationale=(
                        f"Stray capacitance of {est.role} net '{net}' to the "
                        "return node; first-order per-net parasitic estimate."
                    ),
                )
            )
        return out

    def default_series_plan(
        self,
        inputs: AgentInputs,
        *,
        return_net: str = "DUT_GND",
        exclude_nets: tuple[str, ...] = (),
        overrides: dict[str, dict] | None = None,
    ) -> list[SeriesParasitic]:
        """Per-net series-parasitic plan (M2.10.6).

        Every clean 2-element internal net (``injectable`` per M2.10.4)
        gets a series R+L splice plus a shunt C. The input-rail supply
        net is excluded — it already receives the ``TRACE_RLC``
        injection — along with anything in ``exclude_nets``.

        Project overrides accept any combination of:

        - ``{"skip": True}`` drops the net entirely;
        - ``{"r_mohm": N}`` pins the series R (milliohm — display unit);
        - ``{"l_nh": N}`` pins the series L (nanohenry);
        - ``{"c_pf": N}`` pins the shunt C (picofarad).

        Any override flips ``source`` / ``rule_id`` to
        ``"project_override"``. R / L overrides only make sense for
        ``injectable`` (series) nets — the schema doesn't forbid them
        elsewhere but no other plan reads them.

        The caller must feed the matching ``series_split_nets`` to the
        fragment preprocessor so ``<net>__pre`` actually exists.
        """
        if inputs.topology is None:
            return []
        from emc_assistant.parasitics.per_net import estimate_all_nets

        overrides = overrides or {}
        skip_nets = {return_net, "0", CABLE_OUT_NET, *exclude_nets}
        out: list[SeriesParasitic] = []
        for est in estimate_all_nets(inputs.topology):
            if not est.injectable or est.net in skip_nets:
                continue
            ov = overrides.get(est.net, {})
            if ov.get("skip"):
                continue
            r = (
                float(ov["r_mohm"]) * 1e-3 if "r_mohm" in ov
                else est.rlc.resistance.value
            )
            l = (
                float(ov["l_nh"]) * 1e-9 if "l_nh" in ov
                else est.rlc.inductance.value
            )
            c = (
                float(ov["c_pf"]) * 1e-12 if "c_pf" in ov
                else est.rlc.capacitance.value
            )
            has_override = any(k in ov for k in ("r_mohm", "l_nh", "c_pf"))
            source = "project_override" if has_override else "rule_of_thumb"
            rule_id = "project_override" if has_override else "engineering_estimate"
            if r <= 0 or l <= 0 or c <= 0:
                continue
            out.append(
                SeriesParasitic(
                    net=est.net,
                    resistance_ohm=r,
                    inductance_h=l,
                    capacitance_f=c,
                    return_net=return_net,
                    rule_id=rule_id,
                    source=source,
                    rationale=(
                        f"Series trace R+L+C on clean 2-element {est.role} "
                        f"net '{est.net}'; cut at its first element."
                    ),
                )
            )
        return out

    def _negligibility_messages(
        self, candidates: list[dict], *, context_line: str
    ) -> list[dict[str, Any]]:
        """Build the chat messages for the M2.10.7 negligibility screen."""
        system = (
            "You screen first-order per-net parasitic estimates for a "
            "conducted-EMI (150 kHz - 30 MHz) pre-compliance analysis of a "
            "DC/DC converter. For each candidate decide whether the parasitic "
            "is NEGLIGIBLE - i.e. it cannot plausibly change conducted "
            "emissions in that band for this circuit. Bias strongly toward "
            "KEEPING: mark negligible only when you are confident. Always keep "
            "parasitics on a switching node, a power/supply rail, or any fast "
            "di/dt path. A few pF of stray capacitance on a high-impedance "
            "static bias or feedback net is a typical negligible case. These "
            "are engineering estimates, not measurements - do not invent "
            "values. Reply with ONLY a JSON object: "
            '{"verdicts":[{"net":"<net>","negligible":true|false,'
            '"reason":"<short>"}]}. Include every input net exactly once.'
        )
        user = (
            f"{context_line}\n\n"
            f"Candidate per-net parasitics (JSON):\n{json.dumps(candidates, indent=1)}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def filter_negligible(
        self,
        entries: list,
        *,
        kind: str,
        assistant,
        context_line: str,
        purpose: str = "parasitics.negligibility",
    ) -> tuple[list, list]:
        """LLM negligibility screen for a per-net parasitic plan (M2.10.7).

        ``entries`` is a list of :class:`ShuntParasitic` or
        :class:`SeriesParasitic`. Returns ``(kept, dropped)`` where
        ``dropped`` is a list of ``{"net","kind","reason"}`` dicts.

        Fail-safe: any LLM error, malformed response, or a net missing
        from the verdict list keeps that entry. The screen can only
        *remove* parasitics it is confident are negligible — it never
        adds or alters values.
        """
        if not entries:
            return [], []
        candidates = [
            {
                "net": e.net,
                "kind": kind,
                "r_ohm": getattr(e, "resistance_ohm", None),
                "l_h": getattr(e, "inductance_h", None),
                "c_f": e.capacitance_f,
                "context": e.rationale,
            }
            for e in entries
        ]
        messages = self._negligibility_messages(candidates, context_line=context_line)
        try:
            raw = assistant.complete(
                messages=messages, purpose=purpose, expected_output_tokens=900
            )
            verdicts = parse_json_object(raw).get("verdicts", [])
        except Exception as exc:  # noqa: BLE001 - fail-safe: keep everything
            _log.warning(
                f"[parasitics] negligibility screen failed ({exc}); "
                f"keeping all {len(entries)} {kind} parasitic(s)."
            )
            return list(entries), []
        drop_reason: dict[str, str] = {}
        for v in verdicts:
            if isinstance(v, dict) and v.get("negligible") is True:
                net = str(v.get("net", "")).strip()
                if net:
                    drop_reason[net] = str(v.get("reason") or "LLM judged negligible")
        kept = [e for e in entries if e.net not in drop_reason]
        dropped = [
            {"net": e.net, "kind": kind, "reason": drop_reason[e.net]}
            for e in entries
            if e.net in drop_reason
        ]
        return kept, dropped

    def _reevaluate_messages(
        self, candidates: list[dict], *, context_line: str
    ) -> list[dict[str, Any]]:
        """Build the chat messages for the M2.17 value re-evaluation pass."""
        system = (
            "You refine first-order per-net PCB-trace parasitic estimates "
            "(R, L, C) for a conducted-EMI (150 kHz - 30 MHz) pre-compliance "
            "analysis of a DC/DC converter, using ONLY the provided knowledge "
            "snippets (PCB-parasitics references) and each net's deterministic "
            "PRIOR band. Rules: "
            "(1) NEVER a single certain value - always a min/typ/max band. "
            "(2) These are estimates, not measurements - do not invent precise "
            "numbers. If the snippets do not support a change, KEEP the prior "
            "band (you may widen it) and set a LOW confidence. "
            "(3) Every refined value must be justified by a cited Source_ID "
            "from the snippets; if you cannot cite a source, return the prior "
            "band with cited_sources:[] (it stays an engineering estimate). "
            "(4) Stay physically plausible for a PCB trace: R in the mOhm-Ohm "
            "range, L in the nH to tens-of-nH range, C from sub-pF to tens of "
            "pF. Units: R in ohm, L in henry, C in farad. "
            "Reply with ONLY a JSON object: "
            '{"refined":[{"net":"<net>","r_band":[min,typ,max],'
            '"l_band":[min,typ,max],"c_band":[min,typ,max],'
            '"confidence":0.0-1.0,"rationale":"<short>",'
            '"cited_sources":["<Source_ID>"]}]}. '
            "Include every input net exactly once."
        )
        user = (
            f"{context_line}\n\n"
            "Per-net deterministic priors + retrieved snippets (JSON):\n"
            f"{json.dumps(candidates, indent=1)}"
        )
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    def reevaluate_values(
        self,
        candidates: list[dict],
        *,
        assistant,
        context_line: str,
        purpose: str = "parasitics.reevaluate",
    ) -> dict[str, dict]:
        """LLM/RAG value re-evaluation for a per-net parasitic plan (M2.17).

        ``candidates`` is a list of per-net dicts carrying ``net``, ``role``,
        the deterministic ``prior`` bands, and ``snippets`` (already redacted).
        Returns a ``{net: {r_band, l_band, c_band, confidence, rationale,
        cited_sources}}`` map of *proposed* refinements — bands only, never a
        single value.

        Fail-safe (mirrors :meth:`filter_negligible`): any LLM error, malformed
        response, or a net with an unusable band is simply omitted from the
        result, so the caller keeps that net's deterministic prior. This pass
        never fabricates a value with no band, and never replaces the prior on
        error — it only ever *proposes* citation-backed bands.
        """
        if not candidates:
            return {}
        messages = self._reevaluate_messages(candidates, context_line=context_line)
        try:
            raw = assistant.complete(
                messages=messages, purpose=purpose, expected_output_tokens=1600
            )
            refined = parse_json_object(raw).get("refined", [])
        except Exception as exc:  # noqa: BLE001 - fail-safe: keep priors
            _log.warning(
                f"[parasitics] value re-evaluation failed ({exc}); "
                f"keeping all {len(candidates)} deterministic prior(s)."
            )
            return {}
        out: dict[str, dict] = {}
        for r in refined:
            if not isinstance(r, dict):
                continue
            net = str(r.get("net", "")).strip()
            if not net:
                continue
            bands: dict[str, list[float]] = {}
            for key in ("r_band", "l_band", "c_band"):
                band = _coerce_band(r.get(key))
                if band is None:
                    break
                bands[key] = band
            if len(bands) != 3:
                continue  # unusable band → keep this net's prior
            out[net] = {
                **bands,
                "confidence": _clamp01(r.get("confidence", 0.5)),
                "rationale": str(r.get("rationale") or ""),
                "cited_sources": [
                    str(s) for s in (r.get("cited_sources") or []) if str(s).strip()
                ],
            }
        return out

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        ctx = inputs.problem_context
        findings: list[Finding] = []
        sim_requests: list[SimulationRequest] = []

        # M2.10.4: per-net rule-of-thumb parasitic estimate. The agent
        # walks every net of the user fragment, not just the bulk
        # calculator outputs — "estimate every net like in the paper".
        if inputs.topology is not None:
            from emc_assistant.parasitics.per_net import estimate_all_nets
            net_estimates = estimate_all_nets(inputs.topology)
            injectable = [n for n in net_estimates if n.injectable]
            by_role: dict[str, int] = {}
            for n in net_estimates:
                by_role[n.role] = by_role.get(n.role, 0) + 1
            role_summary = ", ".join(f"{k}:{v}" for k, v in sorted(by_role.items()))
            findings.append(
                Finding(
                    title=f"Per-net parasitic estimate covers {len(net_estimates)} nets",
                    detail=(
                        f"Every net of the user fragment received a rule-of-thumb "
                        f"R/L/C band from role-tuned trace geometry ({role_summary}). "
                        f"{len(injectable)} clean 2-element net(s) are injectable; "
                        "3+-element star/bus nets are estimated but need layout to "
                        "place the splice. All values are engineering estimates "
                        "pending 3D extraction (see the per-net table in the report)."
                    ),
                    severity="info",
                )
            )

        wide_band_ids: list[str] = []
        for p in inputs.parasitics:
            if p.min_value > 0 and (p.max_value / p.min_value) > 3.0:
                wide_band_ids.append(p.id)

        if inputs.parasitics:
            findings.append(
                Finding(
                    title=f"{len(inputs.parasitics)} parasitic estimates received",
                    detail=(
                        "Each estimate carries a min/typ/max band drawn from the "
                        "deterministic calculators. Wider bands → less confidence."
                    ),
                    severity="info",
                )
            )
        else:
            findings.append(
                Finding(
                    title="No parasitic estimates received",
                    detail=(
                        "The parasitics module produced no estimates for this run. "
                        "Provide trace geometry, via dimensions, or capacitor part "
                        "numbers in the project context to enable a meaningful analysis."
                    ),
                    severity="info",
                )
            )
        if wide_band_ids:
            findings.append(
                Finding(
                    title="Wide parasitic bands flagged",
                    detail=(
                        f"max/min > 3× on: {', '.join(wide_band_ids)}. Layout extraction "
                        "would narrow these and stabilise the variant ranking."
                    ),
                    severity="medium",
                )
            )
            sim_requests.append(
                SimulationRequest(
                    description=(
                        "Per-corner sweep of the wide-band parasitics to quantify their "
                        "effect on V(MEAS)."
                    ),
                    kind="sweep",
                    parameters={"parasitic_ids": wide_band_ids},
                )
            )
        recs = [
            Recommendation(
                id="REC-001",
                area=self.name,
                severity="info",
                confidence=0.4,
                problem=(
                    "Deterministic fallback for the parasitics agent. Bands and "
                    "dominant contributors are surfaced; --llm openai adds "
                    "narrative on which parasitic matters at which frequency."
                ),
                evidence=[
                    f"{len(inputs.parasitics)} parasitic estimates inspected; "
                    f"{len(wide_band_ids)} have max/min > 3×."
                ],
                proposed_change={
                    "type": "investigate",
                    "description": (
                        "Consider extracting layout parasitics (M7) to tighten the "
                        "bands flagged above."
                    ),
                },
                simulation_required=False,
                user_action="Re-run with --llm openai for frequency-resolved reasoning.",
                limitations=["Deterministic fallback; no LLM was invoked."],
                sources=["engineering_estimate"],
            )
        ]
        limitations: list[str] = []
        if not ctx.has_layout:
            limitations.append(
                "No layout — parasitic bands fall back to geometric defaults."
            )
        if not ctx.has_stackup:
            limitations.append("No stack-up — trace inductance assumes FR-4 εr=4.3.")
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.45 if inputs.parasitics else 0.25,
            findings=findings,
            risks=[],
            recommendations=recs,
            missing_data=[],
            simulation_requests=sim_requests,
            sources=["engineering_estimate"],
            limitations=limitations,
            llm_generated=False,
            injections=self._default_injection_plan(inputs),
        )


def _first(
    parasitics: list[ParasiticEstimate], *, structure: str, parasitic_type: str
) -> ParasiticEstimate | None:
    for p in parasitics:
        if p.structure == structure and p.parasitic_type == parasitic_type:
            return p
    return None
