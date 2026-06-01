# Design prompts

Ready-to-paste prompts for Claude design sessions. Two prompts:
the **app UI** and the **promo website**. Each is self-contained; for the
UI prompt, also paste `docs/design/ui_design_brief.md` alongside it.

---

## 1. App UI design prompt

> Usage: paste the prompt below into a fresh Claude session, together with
> the full contents of `docs/design/ui_design_brief.md` (required — the functional
> source of truth). Optionally also paste `docs/design/ui_integration.md` so the
> markup follows the wiring contract, and `docs/design/ui_backend_contract.md` so
> the mockups show realistic data. If you already have a draft UI, paste
> that too and ask Claude to revise it against the brief.

```
You are a senior product designer for technical / engineering software
(think EDA tools, oscilloscope software, lab instrumentation UIs).

Design the desktop UI for the "EMC/LTspice Assistant" — a local, private
desktop tool that helps a hardware engineer do conducted-EMI
pre-compliance analysis of DC/DC converters: import an LTspice schematic,
build an EMC testbench around it, run LTspice locally, and review ranked
mitigation recommendations.

The complete functional brief is in the attached `ui_design_brief.md` —
treat it as the source of truth for screens, workflow, principles and
constraints. Read it fully before designing.

Deliverables:
1. A design language: colour system (dark and light themes), typography,
   spacing, and component style. Aesthetic = dense, data-first, calm,
   credible — an instrument, not a consumer app. Confidence and severity
   must be first-class visual signals.
2. The **app shell** — the persistent main-menu navigation rail with its
   three tiers (Workspace · Analysis workflow · `COMING SOON`). It must
   show the two future destinations ("Live Lab Assistant", "Engineer
   Training") as **visible-but-disabled** entries: design that greyed
   "coming soon" state precisely (dimmed, status pill, tooltip) and make it
   clearly distinct from a sequentially-gated workflow stage.
3. High-fidelity, self-contained HTML/CSS mockups (as artifacts) for at
   least these screens: Projects, Import & context, Parasitic selection
   (the priority screen — design this one first and in the most depth),
   Run with the Simulation-settings panel, Results, and Findings &
   recommendations — plus the two **"coming soon" preview screens** the
   disabled future menu items open to.
4. Short interaction notes per screen: empty states, loading/progress,
   error states, what "stale / needs re-run" looks like, and the two
   disabled states (future feature vs not-yet-reached stage).

Hard constraints (from the brief — do not violate):
- Local-only and private; a persistent, visible privacy indicator.
- Pre-compliance, never certification — language and badges must carry
  "engineering hypothesis, verify"; never imply "will pass EMC".
- Show min/typ/max ranges and confidence, never lone "certain" numbers;
  wide uncertainty must look uncertain.
- The pipeline is linear but revisitable.
- Future features are shown honestly: visible in the menu, clearly
  disabled, opening a preview screen — never faked, never hidden.
- The mockup HTML *becomes* the shipped app: produce clean, semantic
  markup with stable hooks (`id`, `data-action`, `data-field`,
  `data-bind`, `data-screen`) and no business logic or network calls in
  the page — the wiring is added later. See `docs/design/ui_integration.md`.

The two future capabilities are part of the UI from day one as the
`COMING SOON` menu tier — design their disabled menu state and their
preview screens (see the brief's "App shell" and "Future destinations"
sections). Do not design live functionality for them. Separately, keep the
Results spectrum plot able to take a second (measured) trace and every
estimate-override interaction an explicit, capturable edit, so the real
features can later slot in without a redesign.

Ask me clarifying questions before committing to a direction if anything
in the brief is ambiguous.
```

---

## 2. Promo website design prompt (V2)

> V2 supersedes the original promo prompt. The change from V1: the
> product *vision* — real-time EMC-lab support and a model that learns
> from engineers' lab corrections — is elevated from a small footer
> section to a prominent, forward-looking differentiator that the whole
> page builds toward.
>
> Usage: paste the prompt below into a fresh Claude session.

```
You are a senior web designer and copywriter for technical B2B products.

Design a single-page marketing website for "EMC Assistant" — a local,
AI-assisted EMC conducted-emissions pre-compliance tool for
power-electronics hardware engineers. Today the product lets an engineer
catch conducted-EMI problems at the simulation stage — before the EMC
lab — by importing an LTspice schematic, auto-building a CISPR-style
testbench with realistic PCB parasitics, running LTspice locally, and
getting ranked, evidence-cited mitigation recommendations from a panel
of specialist analysis agents.

But the story this page tells is bigger than the tool of today. The
product has a clear trajectory, and V2 of this site makes that
trajectory a central, motivating thread — not a footnote.

Audience: hardware, EMC and power-electronics engineers. They are
technical, time-pressed, skeptical of marketing hype, and they care
about rigour and about keeping their designs confidential.

Tone: credible, precise, calm, quietly confident. Engineering-grade, not
startup-hype. The product never claims a circuit "will pass EMC" — the
site must not either. Use honest language: "pre-compliance", "reduce EMI
risk", "catch problems earlier", "engineering hypotheses you verify".

Deliverable: a responsive single-page site as a self-contained HTML/CSS
artifact (dark, technical aesthetic; schematic / spectrum-plot visual
motifs welcome). Include the copy.

Sections, in order:

1. Hero — a sharp headline + one-line subhead + primary CTA. The
   headline sells what ships today (find conducted-EMI problems before
   the lab), but the subhead should hint at the larger arc: this is the
   first step toward an assistant that works with you from schematic to
   the EMC bench itself.

2. The problem — EMI failures discovered at the compliance test are
   expensive: board respins, schedule slips, re-test fees. The deeper
   problem: simulation and the lab are disconnected — the engineer's
   hard-won lab knowledge never flows back into the model.

3. How it works (today) — the pipeline in 4 steps: import schematic →
   auto-built EMC testbench (LISN + cable + PCB parasitics) → local
   LTspice run → ranked recommendations with cited sources. Keep this
   tight; it is the proof that the foundation is real.

4. Key features (today) — per-net parasitic modelling, 12 specialist
   analysis agents, a synthesised diagnostic verdict, corner sweeps,
   Markdown + HTML reports, runs entirely on the engineer's machine.

5. Where this is going — THE CENTREPIECE SECTION. Give it real weight,
   real layout, and ideally a diagram. Two future capabilities, told as
   a coherent vision, clearly framed as the roadmap (forward-looking,
   not available today):
   - **Real-time support at the EMC bench.** The tool runs alongside the
     engineer during an actual conducted-emissions measurement; live
     receiver data is overlaid on the simulated prediction, and the tool
     points to the parasitic / LISN / filter hypothesis behind a
     measured peak. Simulation and the lab, finally on one screen.
   - **A model that learns from the lab.** Every correction an engineer
     makes — to parasitics, LISN setup, filter values — is training
     signal. Across many engineers, the model's parasitic estimates get
     better from real measured outcomes. The tool compounds in value the
     more it is used.
   Make the reader feel the trajectory: today a pre-compliance simulator,
   tomorrow a bench companion, ultimately a continuously-learning EMC
   expert.

6. Trust & privacy — local-first; the schematic never leaves the
   machine; cloud AI is strictly opt-in. Tie this directly to the
   vision: the learning loop is privacy-preserving by design — only
   redacted, structured signal or on-device model updates are shared,
   never raw schematics, and contributing is always opt-in. Privacy is
   what makes the collective-learning vision trustworthy; present the
   two together.

7. Final CTA — invite the engineer to start with the tool that exists
   today and be part of where it is going.

Hard constraints:
- No overclaiming. No "guaranteed compliance", no "pass EMC". Pre-
  compliance positioning only.
- The vision section must be unmistakably forward-looking — phrases like
  "on the roadmap", "where we're heading", "coming". Never imply the
  real-time-lab or learning features exist today.
- Every claim about the current product must be one it can honestly
  support.
- Credible, technical visual language — this sells to engineers.

Ask me clarifying questions (product name, CTA target, pricing posture)
before finalising if needed.
```
