# Prompt — Analog Agent (parked)

**Status: parked.** The MVP focuses on conducted EMI for DC/DC converters. Pure-analog circuits (high-impedance front-ends, instrumentation amps, audio paths) are out of scope for M2.9.

When pure-analog support is unfrozen, rewrite this stub with a concrete I/O contract analogous to `mixed_signal_agent.md`, and add an entry to `src/emc_assistant/agents/__init__.py` / the orchestrator's agent registry.

Until then, the orchestrator does not load this agent.
