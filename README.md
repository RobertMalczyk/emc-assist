# EMC/LTspice Assistant

A local MVP tool for **conducted-EMI pre-compliance analysis** of power
converters on LTspice projects. It imports an LTspice schematic, builds an
EMC testbench around it (LISN + cable + PCB parasitics), runs LTspice
locally, parses the `.raw` / `.log` output, and produces a pre-compliance
report with ranked, evidence-cited mitigation recommendations.

**Website:** [openemc.dev/emc-assist](https://openemc.dev/emc-assist) — part of
the [Open EMC](https://openemc.dev) project.

## Headline product decisions

- LTspice runs **locally on the user's machine**; the product never hosts
  LTspice on a server and never bundles it.
- The tool generates a testbench, adds parasitic models, runs a local
  simulation, and analyses the `.raw` / `.log` artefacts.
- First use case: **conducted EMI in DC/DC power converters**.
- The product never promises EMC compliance. Every analysis is labelled
  **pre-compliance / risk reduction / engineering aid** — results are
  engineering hypotheses that require verification.
- Layout import, radiated EMI, KiCad/Altium integration, and corporate /
  on-premise deployment are explicit future milestones (`docs/11_roadmap.md`).

## The pipeline

A deterministic core, with an opt-in LLM layer on top:

```text
schematic/netlist → context → parasitics → testbench → LTspice runner
                  → result parser → recommendations → report
```

Calculations, parsing, cost limits, and simulation results stay
deterministic. LLMs (opt-in, `--llm openai`) help with interpretation and
prose; every claim cites a rule ID or is tagged `engineering_estimate`.

## Running it locally

Requirements: Python 3.11+, optionally a local LTspice installation.

```powershell
# install (dev) and run the tests
python -m pip install -e .[dev]
python -m pytest

# validate the example project
emc-assistant project validate examples/case_001_buck_conducted_emi

# one-shot pipeline (parasitics → testbench → variants → simulate → report)
emc-assistant pipeline run examples/case_001_buck_conducted_emi --mode dry-run

# generate the report (Markdown + HTML)
emc-assistant report generate examples/case_001_buck_conducted_emi --html
```

Individual stages (`testbench compose`, `variants compose|run`,
`simulate run`, `raw inspect|export-csv`, `recommendations
list|accept|reject`, `knowledge index|search`) are also available — see
`emc-assistant --help`.

If the package is not installed, run via `PYTHONPATH`:

```powershell
$env:PYTHONPATH = "src"
python -m emc_assistant.cli report generate examples/case_001_buck_conducted_emi
```

## First local-run (real LTspice in batch mode)

Until you point the tool at a working LTspice install, the pipeline runs in
`dry-run` mode and the **Measurements** + **Ranking** report sections stay
empty. To get real numbers:

1. **Install LTspice** locally (free download from Analog Devices).
2. **Point the tool at the executable** — via the `LTSPICE_PATH`
   environment variable, or `ltspice.executable_path` in the project's
   `project.yaml`.
3. **Run in local-run mode** with a ranking metric:

   ```powershell
   $env:LTSPICE_PATH = "C:\Program Files\ADI\LTspice\LTspice.exe"
   emc-assistant pipeline run examples/case_001_buck_conducted_emi `
       --mode local-run --rank-metric v_meas_peak
   ```

   LTspice is invoked once per corner variant; each run writes its own
   `.raw` / `.log`, which the runner parses to fill `metrics{}`.
4. If LTspice fails (convergence, missing model, license), the runner
   classifies the failure in `simulation_run.json.errors[]` with a tag and
   a hint, and the pipeline still produces the report.

## Code layout

```text
src/emc_assistant/
  cli.py            # the emc-assistant CLI
  project/          # .emcproj model + project.yaml validation
  netlist/          # .cir parser, fragment preprocessor, topology, signals
  parasitics/       # first-order parasitic calculators + per-net estimation
  testbench/        # LISN / cable / composer / variants / sim settings / .asc
  ltspice/          # local LTspice adapter (dry-run + local-run)
  results/          # .log + .raw parsers, metrics, spectrum, ranking
  recommendations/  # JSON recommendation engine + accept/reject decisions
  knowledge/        # embedded knowledge base (chunker, embedder, vector index)
  llm/              # LLM provider seam (OpenAI / deterministic / stub) + budget
  agents/           # 12 specialist agents + orchestrator + diagnostic synthesiser
  reports/          # Markdown + HTML report renderers
  schemas.py        # JSON-schema validation
tests/              # pytest
docs/               # product, architecture, roadmap, decision log, UI design
```

## Documentation

`docs/` holds the product brief, architecture, agent contracts, security /
privacy / licensing, the decision log, the milestone roadmap
(`11_roadmap.md`), and the M3 UI design material (`ui_design_brief.md`,
`ui_backend_contract.md`, `design_prompts.md`). `CLAUDE.md` is the
working-instruction file for development with Claude Code.

## Privacy

Your schematic is treated as confidential. The deterministic pipeline runs
entirely on your machine. Nothing is sent to the cloud by default; the LLM
layer is **opt-in** (`--llm openai`), and even then only redacted,
structured payloads leave the machine — never the raw schematic or netlist.

## License

Licensed under the **Apache License, Version 2.0** — see [`LICENSE`](LICENSE)
and [`NOTICE`](NOTICE). This tool does not bundle, host, or modify LTspice,
and does not redistribute any vendor or standards-body document content.

> **Disclaimer.** This tool performs EMC *pre-compliance* analysis only. It
> does not certify compliance with any standard. Every recommendation is an
> engineering hypothesis requiring verification by simulation and/or
> measurement.

## Credit & attribution

This project is open so it can grow. If you use the concepts, code, diagrams,
or terminology from it, please credit Robert Malczyk and link back to the
original repository at <https://github.com/RobertMalczyk/emc-assist>.
