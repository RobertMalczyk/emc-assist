# Product brief — EMC/LTspice Assistant

## Problem

Electronics engineers often use LTspice to analyze power supplies, filters, and converters, but for EMC they lack a simple workflow that combines:

- PCB parasitic models,
- conducted EMI,
- LISN,
- cables,
- CM/DM,
- filter selection,
- result interpretation,
- pre-compliance report.

Without trace, via, capacitor, cable, and plane parasitics, simulations often look too ideal and fail to surface problems that show up later in the lab.

## Value proposition

A local LTspice assistant that:

- imports a schematic or netlist,
- asks contextual questions,
- proposes realistic PCB parasitics,
- generates a conducted-EMI testbench,
- runs LTspice locally,
- analyzes the results,
- proposes filtering / decoupling changes,
- produces a pre-compliance report.

## First user

- hardware engineer,
- DC/DC converter designer,
- EMC consultant,
- a small electronics company,
- someone preparing a project for EMC testing.

## MVP

- conducted EMI,
- DC/DC power supplies,
- local LTspice,
- local runner,
- parasitic models,
- LISN testbench,
- report.

## Out of MVP scope

- radiated EMI,
- layout extraction,
- KiCad / Altium,
- corporate / on-premise,
- payments,
- full schematic editing.

## One-sentence positioning

A pre-compliance EMC assistant for LTspice that helps model PCB parasitics, generate testbenches, simulate EMI filters, and propose fixes before lab testing.
