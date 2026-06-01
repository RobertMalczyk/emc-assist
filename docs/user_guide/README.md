# User guide

End-user / operator documentation for the EMC/LTspice Assistant. Both guides use **`examples/case_003_DCDC_eval`** (an Analog Devices LTC7800 synchronous buck, 12 V → 3.3 V) as the running example, with real artifact values.

| Guide | For | Covers |
|---|---|---|
| [`backend.md`](backend.md) | Anyone running the tool | Install, configuration (LTspice / settings / OpenAI key / privacy), the `.emcproj` layout, the six-stage pipeline, the CLI command reference, a worked case_003 run, reading the outputs, and troubleshooting. |
| [`frontend.md`](frontend.md) | Desktop-app users | The pywebview shell screen by screen (Projects → Report + Settings), each with a real-data case_003 mockup + the actions it exposes, the stale-data banners, privacy/local-first behaviour, and an honest wired-vs-deferred status. |

**Read order:** start with `backend.md` (the engine), then `frontend.md` (the viewer over it).

**Status caveat:** the M3 desktop shell is a thin, disposable viewer scheduled for a from-the-studs rebuild (M11). `frontend.md` is honest about which affordances are placeholders; the authoritative per-flow status is in [`../qa/QA_FLOWS.md`](../qa/QA_FLOWS.md) and the DOM contract in [`../../ui/HOOKS.md`](../../ui/HOOKS.md).

> Pre-compliance only — every output is an engineering hypothesis requiring lab verification, never a guarantee of EMC compliance.
