"""Tests for ``emc_assistant.service.resolve`` — the decision-resolution layer.

``resolve.py`` is the largest service module but had no dedicated test —
it was exercised only indirectly through the pipeline tests and touched
as a monkeypatch target. This pins the deterministic branches of each
resolver: the pre-resolved (``_UNSET``) pass-through, the ``--no-*`` /
``--accept-*`` flag logic, and the non-TTY skip — all without a real
LTspice or a live LLM.
"""

from __future__ import annotations

import types

from emc_assistant.llm import DeterministicAssistant, OpenAiAssistant
from emc_assistant.service import resolve
from emc_assistant.service.options import CommandOptions
from emc_assistant.testbench.composer import TestbenchWiring


def _wiring_context(lisn: str = "dual") -> dict:
    """A user_context with an explicit ``lisn_mode`` so resolve_wiring
    never falls through to the LISN-mode agent."""
    return {
        "testbench_wiring": {
            "external_supply_v": 48.0,
            "dut_supply_net": "VBUS",
            "dut_return_net": "0",
            "lisn_mode": lisn,
            "user_source_to_strip": "V1",
        }
    }


# ---- llm_enabled -----------------------------------------------------------


def test_llm_enabled_default_is_false():
    assert resolve.llm_enabled(CommandOptions()) is False


def test_llm_enabled_true_for_openai():
    assert resolve.llm_enabled(CommandOptions(llm="openai")) is True


def test_llm_enabled_true_when_a_stub_is_injected():
    assert resolve.llm_enabled(CommandOptions(stub_assistant=object())) is True


# ---- make_assistant --------------------------------------------------------


def test_make_assistant_default_is_deterministic(tmp_path):
    layout = types.SimpleNamespace(results_dir=tmp_path)
    assistant, log = resolve.make_assistant(
        CommandOptions(), layout=layout, run_id="r1"
    )
    assert isinstance(assistant, DeterministicAssistant)
    assert log is None


def test_make_assistant_returns_the_injected_stub(tmp_path):
    layout = types.SimpleNamespace(results_dir=tmp_path)
    stub = object()
    assistant, log = resolve.make_assistant(
        CommandOptions(stub_assistant=stub), layout=layout, run_id="r1"
    )
    assert assistant is stub
    assert log is None


def test_make_assistant_openai_returns_a_privacy_log_path(tmp_path):
    layout = types.SimpleNamespace(results_dir=tmp_path)
    assistant, log = resolve.make_assistant(
        CommandOptions(llm="openai"), layout=layout, run_id="run-abc"
    )
    assert isinstance(assistant, OpenAiAssistant)
    assert log.endswith("run-abc.jsonl")


# ---- resolve_simulation_settings -------------------------------------------


def test_resolve_simulation_settings_defaults_for_empty_context():
    assert resolve.resolve_simulation_settings({}) is not None


def test_resolve_simulation_settings_returns_none_on_invalid_input():
    bad = {"simulation": {"stop_time": "not-a-spice-number"}}
    assert resolve.resolve_simulation_settings(bad) is None


# ---- resolve_wiring --------------------------------------------------------


def test_resolve_wiring_no_context_returns_none():
    wiring, strip = resolve.resolve_wiring(
        {}, CommandOptions(), layout=None, config=None
    )
    assert wiring is None
    assert strip == ()


def test_resolve_wiring_preset_passes_through():
    preset = TestbenchWiring(
        external_supply_v=12.0, dut_supply_net="X",
        dut_return_net="0", lisn_mode="dual",
    )
    opts = CommandOptions(resolved_wiring=preset, resolved_strip=("Vsrc",))
    wiring, strip = resolve.resolve_wiring({}, opts, layout=None, config=None)
    assert wiring is preset
    assert strip == ("Vsrc",)


def test_resolve_wiring_no_wiring_flag_skips_emission():
    opts = CommandOptions(no_wiring=True)
    wiring, strip = resolve.resolve_wiring(
        _wiring_context(), opts, layout=None, config=None
    )
    assert wiring is None
    assert strip == ()


def test_resolve_wiring_accept_flag_returns_the_proposed_wiring():
    opts = CommandOptions(accept_wiring=True)
    wiring, strip = resolve.resolve_wiring(
        _wiring_context(), opts, layout=None, config=None
    )
    assert wiring is not None
    assert wiring.external_supply_v == 48.0
    assert wiring.dut_supply_net == "VBUS"
    assert wiring.lisn_mode == "dual"
    assert strip == ("V1",)


def test_resolve_wiring_non_interactive_without_accept_skips():
    """pytest's stdin is not a TTY → no prompt, emission skipped."""
    wiring, strip = resolve.resolve_wiring(
        _wiring_context(), CommandOptions(), layout=None, config=None
    )
    assert wiring is None
    assert strip == ()


# ---- resolve_parasitics_injection ------------------------------------------


def test_resolve_injection_preset_passes_through():
    opts = CommandOptions(resolved_injection_plan=["INJ"])
    assert resolve.resolve_parasitics_injection(
        {}, opts, parasitics=[], user_fragment_path=None
    ) == ["INJ"]


def test_resolve_injection_no_parasitics_flag_returns_empty():
    opts = CommandOptions(no_parasitics=True)
    assert resolve.resolve_parasitics_injection(
        {}, opts, parasitics=[], user_fragment_path=None
    ) == []


def test_resolve_injection_not_accepted_returns_empty():
    assert resolve.resolve_parasitics_injection(
        {}, CommandOptions(), parasitics=[], user_fragment_path=None
    ) == []


# ---- resolve_shunt_plan ----------------------------------------------------


def test_resolve_shunt_preset_passes_through():
    opts = CommandOptions(resolved_shunt_plan=["S"])
    assert resolve.resolve_shunt_plan(
        {}, opts, user_fragment_path=None, injection_plan=[]
    ) == ["S"]


def test_resolve_shunt_not_accepted_returns_empty():
    assert resolve.resolve_shunt_plan(
        {}, CommandOptions(), user_fragment_path=None, injection_plan=[]
    ) == []


def test_resolve_shunt_skip_all_override_returns_empty():
    opts = CommandOptions(accept_parasitics=True)
    ctx = {"parasitics": {"skip_all": True}}
    assert resolve.resolve_shunt_plan(
        ctx, opts, user_fragment_path=None, injection_plan=[]
    ) == []


def test_resolve_shunt_accepted_but_no_fragment_returns_empty():
    opts = CommandOptions(accept_parasitics=True)
    assert resolve.resolve_shunt_plan(
        {}, opts, user_fragment_path=None, injection_plan=[]
    ) == []


# ---- resolve_series_parasitics ---------------------------------------------


def test_resolve_series_preset_passes_through():
    plan = [types.SimpleNamespace(net="N1"), types.SimpleNamespace(net="N2")]
    opts = CommandOptions(resolved_series_plan=plan)
    nets, returned = resolve.resolve_series_parasitics({}, opts, None)
    assert nets == ["N1", "N2"]
    assert returned == plan


def test_resolve_series_not_accepted_returns_empty():
    assert resolve.resolve_series_parasitics({}, CommandOptions(), None) == ([], [])


def test_resolve_series_skip_all_override_returns_empty():
    opts = CommandOptions(accept_parasitics=True)
    ctx = {"parasitics": {"skip_all": True}}
    assert resolve.resolve_series_parasitics(ctx, opts, None) == ([], [])


def test_resolve_series_accepted_but_no_fragment_returns_empty():
    opts = CommandOptions(accept_parasitics=True)
    assert resolve.resolve_series_parasitics({}, opts, None) == ([], [])


# ---- filter_negligible -----------------------------------------------------


def test_filter_negligible_empty_entries():
    kept, dropped = resolve.filter_negligible(
        [], "shunt", options=CommandOptions(),
        layout=None, config=None, user_context={},
    )
    assert kept == []
    assert dropped == []


def test_filter_negligible_keeps_everything_when_llm_disabled():
    """Default (deterministic) run never drops a parasitic — fail-safe."""
    entries = ["a", "b", "c"]
    kept, dropped = resolve.filter_negligible(
        entries, "series", options=CommandOptions(),
        layout=None, config=None, user_context={},
    )
    assert kept == entries
    assert dropped == []


# ---- resolve_signals -------------------------------------------------------


def test_resolve_signals_preset_passes_through():
    opts = CommandOptions(resolved_signals=["sig"])
    assert resolve.resolve_signals(
        {}, opts, layout=None, project_root_path=None
    ) == ["sig"]


def test_resolve_signals_no_signals_flag_returns_empty():
    opts = CommandOptions(no_signals=True)
    assert resolve.resolve_signals(
        {}, opts, layout=None, project_root_path=None
    ) == []


# ---- prepare_user_fragment -------------------------------------------------


def test_prepare_user_fragment_none_netlist_returns_none(tmp_path):
    layout = types.SimpleNamespace(generated_dir=tmp_path / "generated")
    assert resolve.prepare_user_fragment(layout, None) is None


def test_prepare_user_fragment_missing_file_returns_none(tmp_path):
    layout = types.SimpleNamespace(generated_dir=tmp_path / "generated")
    assert resolve.prepare_user_fragment(layout, tmp_path / "nope.cir") is None


def test_prepare_user_fragment_writes_the_fragment(tmp_path):
    netlist = tmp_path / "circuit.cir"
    netlist.write_text(
        "* test circuit\nV1 in 0 DC 12\nR1 in out 10\nC1 out 0 1u\n.end\n",
        encoding="utf-8",
    )
    layout = types.SimpleNamespace(generated_dir=tmp_path / "generated")
    fragment = resolve.prepare_user_fragment(layout, netlist)
    assert fragment is not None
    assert fragment.is_file()
    assert fragment.name == "user_circuit_fragment.cir"
