# Prompt — AC/DC Agent (parked)

**Status: parked.** The MVP focuses on conducted EMI for DC/DC converters. AC/DC topologies (PFC, flyback, LLC), X/Y caps, line-frequency CM chokes and the associated safety guardrails are out of scope for M2.9.

When AC/DC support is unfrozen, rewrite this stub with a concrete I/O contract analogous to `dcdc_agent.md`, and add an entry to `src/emc_assistant/agents/__init__.py` / the orchestrator's agent registry.

Until then, the orchestrator does not load this agent.
