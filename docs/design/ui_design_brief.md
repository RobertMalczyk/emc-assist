# EMC/LTspice Assistant — UI design brief

> Self-contained brief for a UI/UX design session. The reader needs no prior
> knowledge of the project. It describes the desktop UI for **M3**. The MVP
> workflow ships now; two further capabilities (a real-time EMC-lab assistant
> and an engineer-trained learning model) are **shown in the UI from day one
> as visible-but-disabled "coming soon" destinations** — see
> "App shell, navigation & future features" below.

## Product

A **local desktop tool for conducted-EMI pre-compliance analysis of DC/DC
converters**. A hardware engineer imports an LTspice schematic; the tool
builds an EMC testbench around it (LISN + cable + PCB parasitics), runs
LTspice locally, and produces a pre-compliance report with ranked
mitigation recommendations from 12 specialist analysis agents plus a
synthesised diagnostic narrative.

Today it is a working Python CLI/pipeline behind a service layer. **This UI
is a local desktop front-end over that existing pipeline** — it adds a
visual workflow, not new analysis logic.

## User

A practising hardware/EMC engineer preparing for a formal EMC test.
Comfortable with SPICE, parasitics, grounding, EMI concepts — but wants to
avoid hand-editing netlists. Works on confidential designs.

## Non-negotiable principles (these must shape the whole UI)

- **Local-only & private.** The schematic is confidential. Nothing about
  the circuit leaves the machine unless the user explicitly opts into a
  cloud LLM. Show the privacy state at all times (a clear
  "local / cloud LLM off" indicator).
- **Pre-compliance, never certification.** Every output is an *engineering
  hypothesis requiring verification* — never "this will pass EMC."
  Language, badges, and a persistent disclaimer must carry that.
- **Ranges, not false precision.** Parasitics and recommendations are
  min/typ/max bands with a confidence level. Show bands and confidence,
  never a lone "certain" number.
- **The tool assists; the engineer decides.** Every agent proposal is
  reviewable / acceptable / rejectable.
- **Honest about what exists.** Capabilities not yet shipped are shown as
  clearly disabled and labelled "coming soon" — never faked, never hidden.

## App shell, navigation & future features

The app has a **persistent main menu** (a left navigation rail) that is the
spine of the UI. It lists *every* destination the product will ever have —
including ones not built yet — so the engineer always sees the full
trajectory of the tool. The rail has three tiers, top to bottom:

**Tier 1 — Workspace (active)**
- **Projects** — list / create / open local `.emcproj` projects.

**Tier 2 — Analysis workflow (active, per open project)**
The MVP pipeline, one entry per stage: *Import & context · Parasitic
selection · Testbench · Run · Results · Findings & recommendations ·
Report*. These are **sequentially gated** — a stage you have not reached yet
is shown disabled with a subtle progress lock, and unlocks as the pipeline
advances. This "not yet reachable" disabled state is visually distinct from
the "future feature" disabled state in Tier 3 (see below).

**Tier 3 — Coming soon (visible, disabled, future)**
Under a clearly labelled `COMING SOON` / `ROADMAP` divider, two entries are
**always visible from the main menu** but **disabled (greyed out)**:
- **Live Lab Assistant** — real-time support at the EMC test bench.
- **Engineer Training** — the engineer-trained, continually-improving model.

**Bottom of the rail (active)**
- **Settings** and the persistent **privacy indicator**.

### How a disabled future feature must look and behave

This is a core part of the design — get it right:

- **Always present.** The two Tier-3 entries appear in the main menu from
  the very first launch. They are part of the product's identity, not
  hidden behind a flag.
- **Unmistakably disabled, intentionally so.** Dimmed label + icon, reduced
  contrast, and a small status pill (`SOON` / `PLANNED`) or a clock/lock
  glyph. It must read as *deliberately not-yet-here*, never as a bug, an
  error, or a broken link.
- **Grouped and divided.** The `COMING SOON` divider separates them from the
  active workflow so the tiers never blur together.
- **Tooltip on hover** — e.g. *"Planned — not available in this version."*
- **Clickable into a preview, not into a dead end.** Selecting a disabled
  entry opens a read-only **preview screen** (see "Future destinations"
  below) that explains the capability and its roadmap status. It never
  opens a fake or empty version of the real feature.
- **One enable path.** Each future entry is governed by a single feature
  gate. When the capability ships, the *same* menu item un-greys, drops the
  `SOON` pill, and routes to the real screen instead of the preview. Design
  the enabled and disabled states of each entry as one coherent component
  with an on/off state — not two separate things.

## Workflow (the active MVP pipeline)

A left-to-right pipeline; the UI should make progress through it obvious:

Import schematic → Collect circuit context → **Review & select
parasitics** → Review assembled testbench → Run LTspice locally → Inspect
results → Review findings & recommendations → Export report.

The pipeline is linear but **revisitable** — the engineer loops back
(changes a parasitic, re-runs). Make "what is stale / needs re-run" obvious.

## Screens (active — the MVP)

### 1. Projects

List / create / open projects (each is a local `.emcproj` folder). Per
project show a pipeline-stage status (imported · parasitics set ·
simulated · report ready).

### 2. Import & context

Drop an `.asc`/`.cir` file; a form for circuit context: input voltage,
load current, switching frequency, cable length, PCB stack-up (layers,
copper weight, dielectric height, trace length/width), testbench wiring
(supply net, return net, single/dual LISN), and signals to track (e.g.
`Vout`). Fields auto-fill from the schematic where possible; the user
confirms.

### 3. Parasitic selection — priority screen

The user explicitly wants to "mark which parasitics to add." A net-by-net
table beside a block-diagram of the circuit. For **every net**: name, role
(return / power-rail / switching-node / signal — colour-coded), estimated
R/L/C as min/typ/max bands, parasitic type (series R+L+C splice for clean
2-element nets vs shunt-C for the rest), and an **include toggle**. The
user can: accept the estimate, override a value, skip a net, or run an
optional "AI: suggest which are negligible" action that pre-deselects
insignificant ones (with reasons). A "report-only" mode keeps estimates in
the report but out of the simulation. Selecting a net highlights it on the
diagram.

Every value the engineer overrides here is, in the future, a **learning
event** (see "Engineer Training" below). Design the estimate→override
interaction as an explicit, capturable "estimated value → corrected value"
edit — not a silent field change — so the future learning loop can be
added without reworking this screen.

### 4. Testbench review

The assembled testbench shown as a block diagram (test source → LISN →
cable → injected parasitics → DUT → DM/CM probes). Visual verification that
wiring is correct; option to open the generated LTspice `.asc`.

### 5. Run

Trigger LTspice locally (dry-run preview or full local-run), live progress
for the corner-variant sweep. Surface LTspice warnings (convergence,
missing models) without failing silently. This screen also carries the
**Simulation settings** panel — see the dedicated section below.

### 6. Results

Opens with the **diagnostic narrative** (one synthesised verdict, in
hypothesis language, with a confidence value). Then: key metrics,
before/after comparison, the corner-variant ranking table, and an FFT
spectrum plot with the conducted-EMI band (150 kHz – 30 MHz) marked.

The spectrum plot also overlays the **compliance limit line** of the
selected standard (default: EN 55022 Class B — see "Compliance limit
lines" below), and the results surface the **margin** (reading vs limit,
in dB) for the peak / quasi-peak / average detectors. The margin is a
*pre-compliance estimate*, never a pass/fail verdict.

**EMI detector — three modes.** The peak / quasi-peak / average readings
come from EMC-Assist's CISPR-like detector. The default Results view is
**Mode 1** (`time_domain_diagnostic`) — a fast band overview computed for
every run. The engineer can drill in: **Mode 2**
(`receiver_like_single_frequency`) gives a receiver-bandwidth-filtered
reading at a chosen frequency, e.g. a switching harmonic; **Mode 3**
(`receiver_like_sweep`) scans the conducted band like an EMI-receiver
sweep. The detector mode must be shown with every reading. See
`docs/concepts/quasi_peak_detector_concept.md`.

Design the spectrum plot so a **second, measured spectrum can later overlay
the simulated one** (see "Live Lab Assistant" below) — the plot should not
assume a single trace, and the limit line is itself an overlay layer.

### 7. Findings & recommendations

The specialist agents' findings grouped by area; each recommendation
card shows problem · evidence · proposed change · value range ·
assumptions · limitations · confidence · severity · cited knowledge
sources. Each card is **accept / reject** (decision persists). Severity and
confidence drive visual weight.

### 8. Report & export

Render the full Markdown/HTML report; export. Pre-compliance disclaimer
prominent.

### Settings

LTspice executable path, LLM provider on/off + budget cap, privacy
toggles. Also the project-default simulation/solver settings, and the
**compliance standard** selector (see "Compliance limit lines" below).

## Future destinations (Tier-3 menu items — design the *preview* screens now)

Both are **disabled** in the main menu today. Clicking either opens a
read-only **preview screen**: a calm, credible "here is where the tool is
going" page — capability summary, a representative (clearly-labelled-mockup)
visual, the roadmap status, and the privacy posture. No live functionality;
no fake data presented as real. When the feature ships, the menu item
un-greys and routes here to the *real* screen instead of the preview.

### Live Lab Assistant *(future — preview only)*

Today the tool is an offline pre-compliance pass. The future capability runs
**alongside the engineer at the EMC test bench during an actual
conducted-emissions measurement**. Live (or pasted) measurement data from
the receiver/analyser is correlated against the tool's simulated
prediction; the UI highlights where measured and simulated spectra diverge
and surfaces which parasitic / LISN / filter hypothesis most likely explains
the gap — a live "what is causing this peak" assistant during the test
session.

Preview-screen content: what it does, the measured-vs-simulated overlay
concept (a labelled mockup of the Results spectrum with two traces), and a
note that it requires a connected/importable measurement source. Because
the real version reuses the **Results** screen's plot and the
**Findings** panel, those two MVP screens must already be built to accept a
measured overlay and to react to live data.

### Engineer Training *(future — preview only)*

The per-net parasitic values are rule-of-thumb estimates. In the lab the
engineer corrects them — adjusts parasitics, changes the LISN setup, tweaks
filter values — until the simulation matches measured reality. **Those
corrections are training signal.** A model learns the mapping from
circuit/layout features to realistic parasitic values from the accumulated
corrections of many engineers, so the tool's estimates improve over time
from real lab outcomes.

Preview-screen content: how the engineer's own overrides become training
signal, how the shared model improves with use, the strictly-opt-in nature
of contributing, and — prominently — the privacy posture below. Because the
real version consumes the override interactions on the **Parasitic
selection** screen (and LISN-mode / filter edits), those edits must already
be modelled as explicit, capturable "estimate → corrected value" events.

**Privacy is load-bearing for Engineer Training.** The schematic is
confidential; the learning loop must never ship raw schematics or netlists.
The honest design is federated / on-device learning (only model deltas
leave the machine) or sharing only redacted, structured feature→value pairs
(net role, geometry class, estimated vs corrected R/L/C — no identifying
netlist), reusing the redaction discipline the LLM layer already enforces.
Contributing to the shared model is strictly opt-in, per engineer or per
organisation. The preview screen must make this privacy posture explicit
and the (future) opt-in obvious.

## Visual / UX guidance

- Engineering-tool aesthetic: dense but legible, data-first, calm. Think
  oscilloscope software or a good EDA tool, not a consumer app.
- Confidence and severity are first-class visual signals (badges, colour).
  Wide uncertainty bands should *look* uncertain.
- The pipeline is linear but revisitable — make "what is stale / needs
  re-run" obvious.
- **Two distinct disabled states, two distinct looks:** a *sequentially
  gated* workflow stage (Tier 2 — not reached yet, will unlock with
  progress) vs a *future feature* (Tier 3 — greyed, `SOON` pill, opens a
  preview). They must not be confusable.
- Dark and light themes; the schematic/diagram and FFT plots are the
  visual centrepieces.

## Simulation / solver settings

The user must be able to see and change the **solver setup** — integration
time, timestep, tolerances, integration method. A buck converter and a
hot-swap inrush event need very different settings, and the timestep choice
directly limits what the conducted-EMI FFT can show.

**Where it lives.** An expandable **"Simulation settings" panel on the Run
screen**. The same settings are editable as project defaults from Settings.
Collapsed by default showing a one-line summary (e.g. *"Transient: 0–5 ms,
max step 100 ns · method trap"*); expands to the full form.

**Controls — transient analysis:**

- **Stop time** (total integration time) — the dominant setting.
- **Maximum timestep** — solver resolution ceiling.
- **Data-recording start time** — skip the startup transient.
- **Startup** toggle — ramp sources from zero.

**Controls — solver options:**

- **Integration method** — trapezoidal (default) / Gear / modified trap.
- **Tolerances** — reltol, abstol, vntol (advanced, collapsed sub-section,
  with a per-group "restore defaults").
- **Convergence aids** — gmin, optional cshunt (advanced).
- **Corner sweep** — on/off toggle for the min/typ/max parasitic sweep.

Each field shows its current value, the default, valid range, and units.

**Live feedback (this panel is not just a form):**

- As the user changes **maximum timestep**, show the implied **FFT Nyquist
  frequency** and whether it covers the conducted-EMI band
  (150 kHz – 30 MHz). If the timestep is too coarse to reach 30 MHz, warn
  inline — *before* the run, not after.
- Show an estimated **simulation cost** hint (stop time ÷ timestep → rough
  point count) and warn when a setting is likely to produce a multi-GB
  result file or a very long run.
- Mark settings **changed from default**, and flag when a change makes
  prior results stale (needs re-run).

**Defaults & guardrails:**

- Defaults are DC/DC-tuned and topology-aware (a switching converter vs a
  hot-swap inrush get different stop-time defaults).
- Never present a setting combination as "correct" — these are engineering
  choices; show guidance, not guarantees.
- Reject invalid input inline (negative time, timestep larger than stop
  time).

## Compliance limit lines

The tool compares the detector readings against a **compliance limit
line** so the engineer sees a *margin*, not just a number. The limit line
is shown on the Results spectrum plot and the margin (reading − limit, in
dB) appears in the results and the report.

**Default standard — EN 55022 Class B** (conducted emission, mains
terminal disturbance voltage, 150 kHz – 30 MHz). The limit values:

| Frequency band | Quasi-peak | Average |
|---|---|---|
| 0.15 – 0.50 MHz | 66 → 56 dBµV (decreasing log-linearly with frequency) | 56 → 46 dBµV (log-linear) |
| 0.50 – 5 MHz | 56 dBµV | 46 dBµV |
| 5 – 30 MHz | 60 dBµV | 50 dBµV |

EN 55022 Class B is the default because the MVP targets DC/DC converters
in residential / ITE-class equipment. (EN 55022 was superseded by
EN 55032; the conducted limits above are unchanged in EN 55032.)

**The standard is selectable — the norm can be changed.** EN 55022
Class B is only the default; the design must let the user pick the
applicable standard (Class A, EN 55032, CISPR 25, and others added
later). Structure the limit line as **data, not hard-coded logic**: a
named standard → a piecewise (frequency, dBµV) limit curve per detector
(QP / average). Selecting a different standard re-draws the limit line
and re-computes the margin; nothing else changes. The selector lives in
Settings (project default) and is overridable per project.

**Honest framing (load-bearing):**

- A reading inside the limit is **not** proof of compliance, and a
  reading above it is **not** proof of failure — these are STFT-based
  pre-compliance estimates from a simulation (see the EMI-detector
  notes). Show a *margin*, never a green/red "PASS / FAIL" verdict.
- The engineer is responsible for selecting the standard, class, and
  edition that actually apply to their product. The tool ships the
  EN 55022 Class B values as a convenience default and must say so.
- Limit values are reference data; the UI must show the standard name +
  class next to every margin so the source is never ambiguous.

## Tech constraints

- Desktop app, local-only, wrapping a Python backend (the existing
  service layer / pipeline). No web service.
- Must run on Windows (primary). LTspice is installed separately by the
  user — the app calls it, never bundles it.
- The two Tier-3 features and a full schematic editor, layout import,
  radiated-EMI analysis, and automated certification are **out of scope
  for the MVP build**. The Tier-3 features are still *present in the UI* as
  disabled menu entries with preview screens (per above); the others are
  simply not in the UI yet. Design the MVP so all of these can be added
  later without a rewrite.
