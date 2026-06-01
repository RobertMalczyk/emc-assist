# MVP scope

## MVP goal

A deliverable local CLI workflow for the first use case:

> conducted EMI in a DC/DC power supply simulated in LTspice.

## Must be in the MVP

- project as a `.emcproj` directory,
- project configuration in `project.yaml`,
- import of an input `.cir` netlist,
- handling of an `.asc` file as a reference input without full graphical parsing,
- loading rules from `knowledge/seed/*.jsonl`,
- first-order parasitic calculators,
- generation of SPICE fragments:
  - trace R/L/C,
  - via L/C,
  - capacitor ESR/ESL,
  - cable model,
  - LISN,
- local LTspice adapter with a manually configurable path,
- LTspice batch run when LTspice is available,
- handling of the case when LTspice is not installed,
- `.log` parser,
- structure ready for a `.raw` parser, even if the first version is only a stub,
- JSON recommendations,
- Markdown report,
- unit tests.

## Not required in the MVP

- a full `.asc` schematic parser,
- graphical display of changes on the schematic,
- automatic `.asc` editing,
- desktop UI,
- payments,
- user server,
- layout import,
- radiated EMI,
- quasi-peak compliant with an EMI receiver,
- official standard limits,
- integration with paid standards.

## Minimum MVP demonstration

1. The user creates a project.
2. The user points at a netlist or schematic.
3. The user supplies a stack-up / cable, or uses defaults.
4. The tool proposes min/typ/max parasitics.
5. The tool generates a LISN testbench.
6. The tool produces a netlist for simulation.
7. The tool attempts to run LTspice locally.
8. The tool produces a report even when LTspice is not available — with information about what would be run.
9. The tool produces recommendations in JSON.

## MVP success criterion

- An engineer can build their first conducted-EMI testbench for a simple DC/DC in under 30 minutes and see a list of sensible parasitics and recommendations.
