# Logging mechanism — design (pre-M3)

> **Status: backend seam implemented** (steps 1–4 below). The CLI's 179
> `print()` calls now route through stdlib `logging` via
> `src/emc_assistant/logging_setup.py`; step 5 (the UI handler) ships with
> the M3 UI. The goal was to replace the codebase's ad-hoc `print()`
> output with a structured logging seam that serves both the CLI (today)
> and the M3 desktop UI (which must *capture* operational output, not have
> it printed past it to stdout).

## Why now — before M3

The UI calls the backend's `cmd_*` functions **in-process** (see
`docs/design/ui_backend_contract.md` §5). Those functions currently emit all
progress, warnings and errors via `print()` — **179 `print()` calls**, 178
of them in `cli.py`. A UI cannot cleanly consume `print()`: it would have
to redirect `sys.stdout`, parse free text, and guess severity. The Run
screen needs to *stream* progress, the findings/errors need to be
*surfaced by severity*, and a run's log should be *persistable*. That
requires a real logging seam, and it should exist before the UI is wired —
so the UI is built against it, not retrofitted.

## Current state

- All operational output is `print()`. No use of stdlib `logging`.
- De-facto "components" already exist as string prefixes: `[parasitics]`,
  `[lisn]`, `[wiring]`, `[signals]`, `[pipeline]`, `[simulation]`,
  `[agents]`, `[retrieval]`, `[knowledge index]` …
- A de-facto severity exists: `[warn]` prefixes.
- Separate and **out of scope here**: `results/llm/<run-id>.jsonl` — the
  LLM *privacy log* (redacted payload audit). That stays as-is; see
  "Privacy boundary" below.

## Design overview

Build on the **standard library `logging`** — no new dependency, standard
levels and handlers, and the custom-handler hook the UI needs.

- **One logger tree** rooted at `emc_assistant`. A helper
  `get_logger(component)` returns `logging.getLogger(f"emc_assistant.{component}")`,
  where `component` is one of the existing tags (`parasitics`, `lisn`,
  `pipeline`, …). The component is therefore the logger name — no `extra=`
  plumbing needed.
- **Levels**: `DEBUG` (verbose internals — e.g. per-net detail, per-call
  cost), `INFO` (the progress lines users see today), `WARNING` (LTspice
  convergence warnings, LLM fallbacks, "no layout — low confidence"
  caveats), `ERROR` (failures that abort a stage).
- A small module `src/emc_assistant/logging_setup.py` owns configuration:
  `configure_logging(level, log_file=None, ui_handler=None)` installs the
  handlers; it is idempotent and called once at CLI entry / UI startup.

## The three sinks

1. **Console handler** — human-readable, formats each record as
   `[component] message` (optionally `WARNING: …` / `ERROR: …`). This
   **preserves today's CLI output** verbatim, so the migration is
   behaviour-preserving. Default level `INFO`.
2. **UI handler** *(the M3-critical sink)* — a custom `logging.Handler`
   the UI installs via `configure_logging(ui_handler=…)`. Each emitted
   `LogRecord` is pushed to a thread-safe queue / callback carrying
   `{timestamp, level, component, message}`. The UI's Run screen drains
   the queue and renders — colouring by level, filterable by component.
   This is why stdlib `logging` is the right base: the handler hook is
   exactly the capture mechanism the UI needs, with no stdout games.
3. **Per-run file handler** *(optional, recommended)* — when a pipeline /
   simulate run starts, attach a handler writing
   `results/log/<run-id>.jsonl` (one JSON object per record). A run's log
   then persists: the UI can show past-run logs, and the user can attach
   one to a bug report. Distinct from `results/llm/*.jsonl`.

## UI integration

```text
UI startup            → configure_logging(level=INFO, ui_handler=QueueHandler)
UI "Run" button       → spawn worker thread → cmd_pipeline_run(args)
                            backend emits log records ──┐
worker thread                                          │
UI thread  ← drains the queue, renders live  ←──────────┘
```

The UI never redirects stdout and never parses text. Long actions
(`pipeline run`, `simulate run`, `knowledge index`, any `--llm` call) run
off the UI thread; the queue is the only cross-thread channel.

## Privacy boundary (load-bearing)

Operational logging and the LLM privacy log are **different things** and
must stay separate:

- The **privacy log** (`results/llm/*.jsonl`) records exactly what was
  sent to the LLM, under the redaction rules — a security/audit artifact.
- **Operational logs** record progress, warnings, errors. They must
  **never** contain schematic / netlist content or full LLM payloads.
  Log net *counts* and *roles*, not net lists from a confidential design;
  log "LLM call: agent.parasitics, $0.002", not the prompt body.

This keeps logging consistent with the project's confidential-first
principle — an operational log is safe to surface in the UI and attach to
a report; raw circuit content is not.

## What stays as result artifacts (not logging)

Logging is the *operational stream*. Persisted analysis stays in result
JSON and is unchanged: `simulation_run.json.errors[]` (classified LTspice
failures), `results/diagnostic.json`, the findings, the audits. A failure
is both *logged* (ERROR, for the live stream) and *recorded* (in the
result JSON, for the report) — the two are not merged.

## CLI surface

- `--verbose` / `-v` → console handler at `DEBUG`.
- `--quiet` / `-q` → console handler at `WARNING`.
- `--log-file <path>` → also write a JSONL log there.

Defaults reproduce today's behaviour (`INFO` to the console).

## Migration plan

1. **DONE** — `logging_setup.py` adds `get_logger()` + `configure_logging()`;
   `main()` calls `configure_logging()` at CLI entry, with `--verbose/-v`,
   `--quiet/-q` and `--log-file` global flags.
2. **DONE** — all 179 `print()` calls are now `logger.info/warning/error()`
   (178 in `cli.py`, 1 in `parasitics_agent.py`). Behaviour-preserving: the
   console formatter is `%(message)s`, so CLI output is byte-identical; the
   `[component]` prefixes stay inside the message strings.
3. **DONE** — failures that abort a stage log at `ERROR`; LTspice/LLM
   fallbacks, topology-analysis fallbacks and the `[warn]`/`[skip]` lines
   log at `WARNING`; progress lines stay `INFO`.
4. **DONE** — `cmd_pipeline_run` / `cmd_simulate_run` attach a per-run
   `results/log/<run-id>.jsonl` handler (via the `_with_run_log` decorator).
5. The UI handler ships with the M3 UI itself.

The console handler resolves `sys.stdout` dynamically at emit time
(`_StdoutHandler`), so the migration kept all 455 tests — many of which
assert on `capsys` — passing unchanged.

## Recommendation

Adopt stdlib `logging` with the `emc_assistant.<component>` tree, the
three sinks, and the `get_logger()` / `configure_logging()` helpers.
Steps 1–4 (the backend seam + migration) are a focused milestone that
should land before M3; step 5 (the UI handler) is part of M3. The
migration is large in line count but low-risk — every change is a
`print(...)` → `logger.<level>(...)` swap behind a formatter that keeps
the CLI output identical.
