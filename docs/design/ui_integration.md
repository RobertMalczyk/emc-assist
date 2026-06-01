# UI integration — design artifact → app shell → service layer

> How the HTML/CSS that the Claude **design** session produces becomes the
> running M3 desktop app. This is the handoff contract between three
> things: the **design artifacts**, the **app shell** (pywebview), and the
> **service layer** (`emc_assistant.service`). Read alongside
> `docs/design/ui_design_brief.md` (what to design) and
> `docs/design/ui_backend_contract.md` (what each screen reads / triggers).

## The three layers

```text
┌─ Design artifacts ──────────┐   static HTML + CSS (+ a thin app.js)
│  one file per screen,       │   — produced by the Claude design session,
│  semantic markup, no logic  │     hand-edited only for wiring hooks
└──────────────┬──────────────┘
               │  loaded by
┌──────────────▼──────────────┐   a pywebview (or Tauri) window renders the
│  App shell (pywebview)      │   HTML and exposes a Python bridge object
│  Python ⇄ JS bridge         │   to the page as window.pywebview.api
└──────────────┬──────────────┘
               │  calls
┌──────────────▼──────────────┐   plain functions: service.project.*,
│  Service layer              │   service.pipeline.*, … — already built
│  emc_assistant.service      │   (typed results, ServiceError, logging)
└─────────────────────────────┘
```

The design layer has **no logic and no I/O**. The shell is the only place
HTML meets Python. The service layer is unchanged — the UI is just a second
front-end over it, exactly like `cli.py`.

## The app shell (pywebview)

A small Python entry point (`src/emc_assistant/ui/app.py`, built during M3)
creates one window pointing at the design's HTML and attaches a bridge:

```python
import webview
from emc_assistant.ui.bridge import Api      # see below

window = webview.create_window(
    "EMC/LTspice Assistant",
    "src/emc_assistant/ui/index.html",        # the design artifact
    js_api=Api(),
)
webview.start()
```

- The design's HTML/CSS *is* the UI — pywebview renders it with the system
  webview. No browser, no web server, no network.
- One window; screens are panels swapped client-side (the design provides
  the markup for every screen; a thin router shows/hides them).

## The Python ⇄ JS bridge

`Api` is a thin class: **one method per service use case**, each wrapping a
`service.*` call. It does three jobs and nothing else — translate JS args
to service parameters, convert the typed result to plain JSON, and turn a
`ServiceError` into a structured error object.

```python
import dataclasses
from emc_assistant import service
from emc_assistant.service import CommandOptions, ServiceError

def _jsonable(obj):
    if dataclasses.is_dataclass(obj):
        return {k: _jsonable(v) for k, v in dataclasses.asdict(obj).items()}
    if isinstance(obj, (list, tuple)):
        return [_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _jsonable(v) for k, v in obj.items()}
    return str(obj) if obj.__class__.__module__ != "builtins" else obj

def _call(fn, *args, **kw):
    try:
        return {"ok": True, "data": _jsonable(fn(*args, **kw))}
    except ServiceError as exc:
        return {"ok": False, "error": {
            "message": exc.message, "exit_code": exc.exit_code,
            "details": exc.details}}

class Api:
    def project_status(self, project_root):
        return _call(service.project.get_project_status, project_root)

    def estimate_per_net(self, project_root):
        return _call(service.parasitics.estimate_per_net, project_root)

    def run_pipeline(self, project_root, options):
        return _call(service.pipeline.run_pipeline,
                     project_root, CommandOptions(**options))
    # … one method per UI action in docs/design/ui_backend_contract.md §3
```

From the page, every bridge method is an async call:

```js
const res = await window.pywebview.api.project_status(projectPath);
if (!res.ok) { showError(res.error); return; }
renderStatus(res.data);          // res.data is the JSON of the typed result
```

pywebview runs each `api.*` call on a worker thread, so a long action
(`run_pipeline`, `run_testbench`, `build_index`) does not freeze the window.

## Reading artifacts vs invoking actions

Per `ui_backend_contract.md`, every screen does two kinds of thing:

- **Read** — display backend JSON. A screen either calls a read-style
  bridge method (`project_status`, `estimate_per_net`, `inspect_raw`) or
  reads a JSON artifact file from the `.emcproj` folder. The page renders
  that JSON into the DOM; it never invents data.
- **Act** — a button calls one action bridge method (`compose_testbench`,
  `run_pipeline`, …). The matching `service.*` function writes the
  artifacts; the screen then re-reads them.

The only thing the page itself writes is `input/user_context.json` (the
context form) — and even that should go through a bridge `save_context`
method, not direct file I/O from JS.

## Progress & errors — the logging seam

Long actions stream progress through the logging seam
(`docs/design/logging_design.md`), not through return values:

- On startup the shell calls `configure_logging(ui_handler=…)` with a
  custom `logging.Handler`.
- That handler, for each record, pushes `{timestamp, level, component,
  message}` to the page — e.g. `window.evaluate_js("appLog(%s)" % json)`.
- The page's `appLog(record)` appends to the Run screen's live log and
  colours by `level`. Errors raised as `ServiceError` come back on the
  bridge call's `{ok:false,error}`; operational warnings/progress arrive
  via `appLog`.

## The contract the design must honor

So the design's HTML can be wired mechanically:

1. **Semantic, clean markup.** Real structural HTML — the mockup *is* the
   shipped DOM. One file (or fragment) per screen from the brief.
2. **Stable hooks.** Give every actionable element a stable hook the wiring
   JS can bind to: `id` for singletons, `data-action="run-pipeline"` for
   buttons, `data-field="input_voltage_v"` for form inputs,
   `data-screen="parasitics"` for screen panels, `data-bind="project_id"`
   for value slots. The implementer wires `app.js` against these — they
   must not churn between design revisions.
3. **No logic, no I/O in the design.** No `fetch`/XHR, no business rules,
   no fake data hard-coded as if real. Placeholder/empty/loading/error
   states are *designed* (per the brief) but contain no behaviour.
4. **The two disabled states are markup states**, not separate files: a
   future-feature menu item and a not-yet-reached workflow stage are the
   same component with a `data-state="coming-soon"` / `data-state="locked"`
   attribute the shell toggles.
5. **A thin `app.js` is the implementer's job**, not the designer's: it
   routes screens, calls `window.pywebview.api.*`, renders JSON into the
   `data-bind` slots, and handles `appLog`. The design may include a
   stub `app.js` for the mockup, but the real one is written during M3.

## Who builds what

| Layer | Produced by | Status |
|---|---|---|
| HTML/CSS per screen, design language | Claude **design** session | pending (design) |
| `app.js` wiring + screen router; real `index.html` | M3 implementation | pending (needs design) |
| `ui/bridge.py` `Api`, `ui/log_handler.py`, `ui/app.py` shell | M3 implementation | **done** |
| `emc_assistant.service.*`, logging seam | this repo | **done** |

The shell, the `Api` bridge and the logging-seam UI handler are built and
tested — `ui/index.html` is a placeholder that smoke-tests the plumbing.
What remains is the design session's HTML/CSS and the `app.js` that wires
the designed markup to the bridge.
