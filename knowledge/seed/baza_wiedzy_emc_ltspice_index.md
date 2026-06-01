# EMC / LTspice knowledge base for agents
Created: 2026-05-13

## Goal

Index of publicly available materials for building agents that assist with pre-compliance EMC, especially for conducted issues, LTspice, filters, stack-up, decoupling, high-speed interfaces, AC/DC, and PCB manufacturing requirements.

## Guardrails

- Treat results as **pre-compliance / risk reduction**, not as a guarantee of passing EMC tests.
- CISPR / IEC / IPC standards are typically paid; the agent must not copy limit tables from unlicensed sources.
- Vendor materials are publicly available but still covered by copyright and terms of use.
- For RAG, the best practice is to index short summaries, metadata, own notes and links — not full document copies.

## Recommended first agent

**LTspice Conducted EMI Assistant**: LISN generator + CM/DM + parasitic models + filter sweep + pre-compliance report.

## Sources by area

### AC/DC EMI filters
- **SRC-022 — Calculation, Design and LTspice Simulation of AC Line Filters** (Würth Elektronik, Webinar slides PDF, priority 5).  
  URL: https://www.we-online.com/files/pdf1/final_calculation-design--lt-spice-simulation-of-ac-line-filters.pdf  
  Usage: Core for AC/DC conducted EMI and LISN-equivalent CM/DM line-filter modeling.

### AC/DC power
- **SRC-050 — AC-DC Universal Input 45 W Power Supply Using CoolSET SiP ICE184ZCM** (Infineon, Application note PDF, priority 4).  
  URL: https://www.infineon.com/assets/row/public/documents/24/42/infineon-ac-dc-universal-input-45w-power-supply-using-coolset-sip-ice184zcm-applicationnotes-en.pdf  
  Usage: Use for AC/DC SMPS reference-board layout, EMI measurements and transformer/filter context.
- **SRC-051 — Optimizing CoolMOS CE Based Power Supplies to Meet EMI Requirements** (Infineon, Application note PDF, priority 4).  
  URL: https://www.infineon.com/assets/row/public/documents/24/42/infineon-applicationnote-optimizing-coolmosce-based-power-supplies-for-emi-applicationnotes-en.pdf  
  Usage: Use for AC/DC MOSFET switching-speed, transformer and EMI-filter tradeoffs.

### Automotive power EMC
- **SRC-007 — Layout Guidelines Maximize Automotive Power-Supply Performance and Minimize Emissions** (Analog Devices, Design note, priority 4).  
  URL: https://www.analog.com/en/resources/design-notes/layout-guidelines-maximize-automotive-powersupply-performance-and-minimize-emissions.html  
  Usage: Use for automotive-oriented heuristics: main-supply filters, ferrites/inductors, FM-band emissions.

### CAN
- **SRC-039 — Common-Mode Chokes in CAN Networks** (Texas Instruments, Application report PDF, priority 4).  
  URL: https://www.ti.com/lit/pdf/slla271  
  Usage: Use for caveats around CMCs in CAN networks and unexpected transients.

### Component libraries
- **SRC-057 — Ferrite Beads SPICE Data** (Murata, Model library page, priority 4).  
  URL: https://www.murata.com/en-eu/tool/data/spicedata/netlist-ferritebead  
  Usage: Use as a source for vendor ferrite bead netlists when building LTspice model importers.
- **SRC-058 — Murata LTspice Library** (Murata, Model library page, priority 4).  
  URL: https://www.murata.com/en-global/tool/data/library/ltspice  
  Usage: Use for capacitors, inductors and ferrites in simulations; validate model scope and limits.
- **SRC-059 — TDK SPICE Libraries** (TDK Electronics, Model library page, priority 4).  
  URL: https://www.tdk-electronics.tdk.com/en/3467182/design-support/design-tools/spice-libraries  
  Usage: Use as external model source for passive components; map part families and impedance behavior.
- **SRC-060 — Laird SPICE Model Documentation** (Laird Performance Materials, Model documentation, priority 3).  
  URL: https://www.laird.com/resources/reference-documents/spice-model-documentation  
  Usage: Use as model-source option for chip beads, including bias-sensitive behavior if applicable.

### Component selection tools
- **SRC-019 — REDEXPERT Design Tool** (Würth Elektronik, Online design tool, priority 5).  
  URL: https://www.we-online.com/en/support/design-tools/redexpert  
  Usage: Use as external tool reference for component selection, impedance curves and EMI filter design workflows.

### Conducted EMI
- **SRC-003 — A Practical Method for Separating Common-Mode and Differential-Mode Emissions in Conducted Emissions Testing** (Analog Devices, Article, priority 5).  
  URL: https://www.analog.com/en/resources/analog-dialogue/articles/separating-common-mode-and-differential-mode-emissions-in-conducted-emissions-testing.html  
  Usage: Teach agent to classify noise as CM or DM and select filter topology accordingly.
- **SRC-004 — Speed Up the Design of EMI Filters for Switch-Mode Power Supplies** (Analog Devices, Article, priority 5).  
  URL: https://www.analog.com/en/resources/analog-dialogue/articles/speed-up-the-design-of-emi-filters-for-switch-mode-power-supplies.html  
  Usage: Use for filter-design reasoning and explaining why conducted EMI filter iteration is costly.
- **SRC-005 — Mitigating EMI for a CISPR 22-Compliant Power Solution** (Analog Devices, Article, priority 4).  
  URL: https://www.analog.com/en/resources/technical-articles/mitigating-emi-for-a-cispr-22compliant-power-solution.html  
  Usage: Good case material for selecting low-EMI components, filters, layout and shielding as a combined solution.
- **SRC-021 — Efficient EMI Filtering of Common and Differential Mode Noise** (Würth Elektronik, Webinar slides PDF, priority 5).  
  URL: https://www.we-online.com/files/pdf1/emc_cmanddm_mode_2025-1.pdf  
  Usage: Use for filter selection decision trees: CMC vs differential inductor vs capacitors.

### DC/DC EMI mitigation
- **SRC-045 — EMI Mitigation Techniques Using the TPSM33620-Q1** (Texas Instruments, Application note PDF, priority 4).  
  URL: https://www.ti.com/lit/pdf/sdaa041  
  Usage: Use for modern automotive buck module EMI mitigation examples and validation patterns.

### DC/DC converters
- **SRC-023 — DC/DC Boost Converter EMI Seminar** (Würth Elektronik, Webinar slides PDF, priority 5).  
  URL: https://www.we-online.com/files/pdf1/dcdc-boost-demo-2025.pdf  
  Usage: Use for DCDC boost-specific patterns, damping, Schottky recovery, bead placement and measurement correlation.
- **SRC-024 — ANP044: Impact of Layout, Components and Filters on EMC of Modern DC/DC Switching Controllers** (Würth Elektronik, Application note PDF, priority 5).  
  URL: https://www.we-online.com/components/media/o109026v410%20ANP044d_Impact%20of%20the%20layout%2C%20components%2C%20and%20filters%20on%20the%20EMC%20of%20modern%20DCDC%20switching%20controllers.pdf  
  Usage: Use for causality rules: MLCC + filter inductance resonance, layout parasitics, LC damping and input filter stability.
- **SRC-031 — An Engineer's Guide to Low EMI in DC/DC Regulators** (Texas Instruments, E-book PDF, priority 5).  
  URL: https://www.ti.com/lit/eb/slyy208/slyy208.pdf  
  Usage: Use for converter architecture/layout/loop-area heuristics and low-EMI regulator design.
- **SRC-032 — Fundamentals of EMI Requirements for an Isolated DC/DC Converter** (Texas Instruments, White paper PDF, priority 4).  
  URL: https://www.ti.com/lit/wp/slyy202/slyy202.pdf  
  Usage: Use for standard-oriented EMI requirements and isolated converter noise causes/mitigation.

### DC/DC layout
- **SRC-044 — AN-1229 SIMPLE SWITCHER PCB Layout Guidelines** (Texas Instruments, Application report PDF, priority 4).  
  URL: https://www.ti.com/lit/pdf/snva054  
  Usage: Use for simple switcher layout rules and loop minimization.

### Decoupling
- **SRC-010 — MT-101: Decoupling Techniques** (Analog Devices, Tutorial PDF, priority 5).  
  URL: https://www.analog.com/media/en/training-seminars/tutorials/MT-101.pdf  
  Usage: Core source for decoupling-capacitor selection, placement and ground-plane connection rules.

### Decoupling / filtering
- **SRC-025 — ANP098: Effect of Layout, Vias and Design on Blocking Capacitor Performance** (Würth Elektronik, Application note PDF, priority 5).  
  URL: https://www.we-online.com/components/media/o695199v410%20ANP098a%20EN.pdf  
  Usage: Use for decoupling-capacitor placement, via count and loop inductance behavior.

### EMC basics
- **SRC-026 — EMC Design Tips 2025** (Würth Elektronik, Slides PDF, priority 4).  
  URL: https://www.we-online.com/files/pdf1/emc-design-tips-2025_en.pdf  
  Usage: Use for general EMC reasoning: source-path-victim, capacitive/inductive coupling, trace proximity and isolation.

### Ethernet
- **SRC-042 — Reducing Radiated Emissions in Ethernet 10/100 LAN Applications** (Texas Instruments, Application report PDF, priority 4).  
  URL: https://www.ti.com/lit/pdf/snla107  
  Usage: Use later for radiated expansion and chassis/ground/cable interface rules.

### Ethernet / SPE
- **SRC-040 — EMC/EMI Compliant Design for Single Pair Ethernet** (Texas Instruments, Application note PDF, priority 5).  
  URL: https://www.ti.com/lit/pdf/snla434  
  Usage: Use for SPE/PoDL EMC schematic and layout practices, power and clocking focus.

### Ethernet stack-up
- **SRC-055 — AP32368 PCB Design Guidelines for Gbit-Ethernet Interface** (Infineon, Web documentation, priority 4).  
  URL: https://documentation.infineon.com/aurixtc3xx/docs/nof1710999169938  
  Usage: Use for Gbit Ethernet stack-up and impedance-controlled routing checklist.

### General EMC workflow
- **SRC-020 — Practical EMC Design Considerations** (Würth Elektronik, Webinar slides PDF, priority 5).  
  URL: https://www.we-online.com/files/pdf1/wuerth-elektronik_digital-days-2022_practical-emc-design-coniderations-v1.pdf  
  Usage: Excellent source for rule-of-thumb + practical example pipeline: filter architecture, selection, simulation and layout review.

### High-speed comms
- **SRC-016 — Public GMSL2 Hardware Design and Validation Guide** (Analog Devices, User guide PDF, priority 3).  
  URL: https://www.analog.com/media/en/technical-documentation/user-guides/public-gmsl2-hardware-design-and-validation-guide.pdf  
  Usage: Use for high-speed channel heuristics, TDR, rise-time bandwidth rule and PCB parasitic interpretation.
- **SRC-017 — Public GMSL3 Hardware Design and Validation Guide** (Analog Devices, User guide PDF, priority 3).  
  URL: https://www.analog.com/media/en/technical-documentation/user-guides/public-gmsl3-hardware-design-and-validation-guide.pdf  
  Usage: Use for advanced high-speed differential routing and validation patterns.

### High-speed interfaces
- **SRC-035 — High-Speed Interface Layout Guidelines** (Texas Instruments, Application report PDF, priority 5).  
  URL: https://www.ti.com/lit/pdf/spraar7  
  Usage: Use for practical high-speed interface checklists: ESD/EMI parts near connectors, reference planes, voids.
- **SRC-036 — High-Speed Layout Guidelines for Signal Conditioners and USB Hubs** (Texas Instruments, Application report PDF, priority 5).  
  URL: https://www.ti.com/lit/pdf/slla414  
  Usage: Use for latest TI high-speed layout best practices for USB and signal-conditioning designs.

### High-speed layout
- **SRC-034 — High-Speed Layout Guidelines** (Texas Instruments, Application report PDF, priority 5).  
  URL: https://www.ti.com/lit/pdf/scaa082  
  Usage: Use for high-speed timing/routing and return-path guidelines.

### High-speed stack-up
- **SRC-054 — AP32488 PCB and High Speed Serial Interface Design Guidelines** (Infineon, Web documentation, priority 4).  
  URL: https://documentation.infineon.com/aurixtc3xx/docs/ccf1710923485867  
  Usage: Use for high-speed stack-up, impedance-controlled routing and termination rules.

### Industrial Ethernet
- **SRC-041 — Optimizing EMC Performance in Industrial Ethernet Applications** (Texas Instruments, Application report PDF, priority 4).  
  URL: https://www.ti.com/lit/an/snla466/snla466.pdf  
  Usage: Use for Ethernet CMC/transformer/filter decisions and industrial EMC countermeasures.

### LTspice / workflow EMC
- **SRC-001 — How to Get the Best Results Using LTspice for EMC Simulation - Part 1** (Analog Devices, Article + LTspice approach, priority 5).  
  URL: https://www.analog.com/en/resources/technical-articles/how-to-get-the-best-results-using-ltspice-part-1.html  
  Usage: Core reference for generating LTspice LISN testbenches, plotting CM/DM noise and pre-compliance limit lines.
- **SRC-002 — Using LTspice for EMC and Signal Integrity - Part 2** (Analog Devices, Article + models, priority 5).  
  URL: https://www.analog.com/en/resources/technical-articles/how-to-get-the-best-results-using-ltspice-for-emc-simulation-part-2.html  
  Usage: Use for agent workflows around wired interfaces, cable/interconnect effects and SPICE-compatible channel models.

### LTspice libraries
- **SRC-018 — LTspice Component Libraries** (Würth Elektronik, Library page, priority 5).  
  URL: https://www.we-online.com/en/support/design-tools/libraries/ltspice  
  Usage: Core source for LTspice-compatible models of ferrites, common-mode chokes, filter chokes, line filters and capacitors.

### LVDS / high-speed
- **SRC-046 — LVDS Application and Data Handbook** (Texas Instruments, Handbook PDF, priority 3).  
  URL: https://www.ti.com/lit/ug/slld009/slld009.pdf  
  Usage: Use for transmission-line model thresholds and LVDS common-mode filtering caveats.
- **SRC-047 — LVDS Owner's Manual Design Guide** (Texas Instruments, Design guide PDF, priority 3).  
  URL: https://www.ti.com/lit/ug/snla187/snla187.pdf  
  Usage: Use for microstrip/stripline structures and practical differential routing basics.

### Mixed-signal layout
- **SRC-011 — Basic Linear Design, Chapter 12: Printed Circuit Board Design Issues** (Analog Devices, Handbook chapter PDF, priority 4).  
  URL: https://www.analog.com/media/en/training-seminars/design-handbooks/Basic-Linear-Design/Chapter12.pdf  
  Usage: Use for mixed-signal PCB rules, grounding tradeoffs, converter decoupling and layout caveats.
- **SRC-014 — What Are the Basic Guidelines for Layout Design of Mixed-Signal PCBs?** (Analog Devices, Article, priority 4).  
  URL: https://www.analog.com/en/resources/analog-dialogue/articles/what-are-the-basic-guidelines-for-layout-design-of-mixed-signal-pcbs.html  
  Usage: Use for agent schematic/layout review checklists for mixed analog-digital boards.

### Motor drivers
- **SRC-043 — Best Practices for Board Layout of Motor Drivers** (Texas Instruments, Application report PDF, priority 3).  
  URL: https://www.ti.com/lit/an/slva959b/slva959b.pdf  
  Usage: Use for high-current switching loop and via/return-path best practices for motor-drive designs.

### PCB EMC basics
- **SRC-056 — AN5240 Layout Recommendations for ST25R Devices** (STMicroelectronics, Application note PDF, priority 3).  
  URL: https://www.st.com/resource/en/application_note/an5240-layout-recommendations-for-the-design-of-boards-with-the-st25r391616b-1717b-18-19b-and-2020b-devices-stmicroelectronics.pdf  
  Usage: Use for general return-current rules: do not route over gaps, use solid return plane, mixed-signal partitioning.

### PCB EMC debugging
- **SRC-029 — How do I solve EMI on PCB level?** (Würth Elektronik, Webinar slides PDF, priority 4).  
  URL: https://www.we-online.com/files/pdf1/webinar_emi-problem-on-pcb-level_20.11.2018.pdf  
  Usage: Use for schematic/layout debugging checklist: short traces, coupling avoidance, routing and return paths.

### PCB EMC robustness
- **SRC-049 — Basic Design Consideration and Layout Recommendations for EMC Robustness** (Infineon, Application note PDF, priority 3).  
  URL: https://www.infineon.com/assets/row/public/documents/24/42/infineon-basic-design-consideration-and-layout-recommendations-for-emc-robustness-applicationnotes-en.pdf  
  Usage: Use for checklist-style EMC robustness review around connector/sensor interfaces.

### PCB EMC / ESD
- **SRC-048 — EMC and System-ESD Design Guidelines for Board Layout** (Infineon, Application note PDF, priority 5).  
  URL: https://www.infineon.com/assets/row/public/documents/30/42/infineon-ap2402635-general-pcb-applicationnotes-en.pdf  
  Usage: Core source for board-level EMC: routing high-speed, stack-up, power domains and ESD placement.

### PCB layout EMC
- **SRC-033 — PCB Design Guidelines for Reduced EMI** (Texas Instruments, Application report PDF, priority 5).  
  URL: https://www.ti.com/lit/pdf/szza009  
  Usage: Use as general rule-of-thumb source for PCB emissions: loop area, return current, decoupling, planes.

### PCB manufacturing
- **SRC-061 — PCB Design Guidelines** (Eurocircuits, Technical guidelines, priority 5).  
  URL: https://www.eurocircuits.com/technical-guidelines/pcb-design-guidelines/  
  Usage: Core source for PCB DFM constraints: clearances, drill sizes, annular rings, manufacturable features.
- **SRC-062 — Gerber X2plus** (Eurocircuits, Technical guideline, priority 4).  
  URL: https://www.eurocircuits.com/technical-guidelines/gerber-format/gerber-x2plus/  
  Usage: Use for explaining manufacturable data export and metadata useful to fabricators.
- **SRC-063 — PCB Front-End Data Preparation** (Eurocircuits, Technical article, priority 4).  
  URL: https://www.eurocircuits.com/frontend-data-preparation/  
  Usage: Use to teach agents what fabricators do with Gerbers/CAD data before production.
- **SRC-064 — During Production** (Eurocircuits, Technical guideline, priority 4).  
  URL: https://www.eurocircuits.com/technical-guidelines/quality/during-production/  
  Usage: Use for production requirements: netlist electrical test, soldermask checks, registration and quality controls.
- **SRC-065 — Via Filling** (Eurocircuits, Technical guideline, priority 3).  
  URL: https://www.eurocircuits.com/technical-guidelines/pcb-design-guidelines/via-filling/  
  Usage: Use for via-in-pad, sealed via and manufacturability decisions.
- **SRC-066 — Understanding Annular Rings** (Eurocircuits, Technical article, priority 4).  
  URL: https://www.eurocircuits.com/tips-tricks/understanding-annular-rings/  
  Usage: Use for DFM checks around drill diameter, finished hole size and annular ring calculations.
- **SRC-067 — PCB Manufacturing & Assembly Capabilities** (JLCPCB, Capabilities page, priority 4).  
  URL: https://jlcpcb.com/capabilities/pcb-capabilities  
  Usage: Use to parameterize manufacturability checks by actual fabricator capabilities.
- **SRC-068 — User Guide to the JLCPCB Impedance Calculator** (JLCPCB, Help article, priority 4).  
  URL: https://jlcpcb.com/help/article/user-guide-to-the-jlcpcb-impedance-calculator  
  Usage: Use for controlled-impedance workflow: target Z, stack-up inputs and routing geometry.
- **SRC-069 — PCB Design Rules and Guidelines: Best Practices Guide** (JLCPCB, Blog guide, priority 3).  
  URL: https://jlcpcb.com/blog/pcb-design-rules-best-practices  
  Usage: Use as general DFM/DFA checklist; verify against actual fab capabilities before final advice.
- **SRC-070 — DFM Rules** (Sierra Circuits / ProtoExpress, Knowledge-base article, priority 3).  
  URL: https://www.protoexpress.com/kb/dfm-rules/  
  Usage: Use as secondary source for DFM categories: trace width, drill, edge clearance, blind/buried vias.

### Parasitic modeling
- **SRC-013 — An Improved and Simple Cable Simulation Model** (Analog Devices, Article, priority 5).  
  URL: https://www.analog.com/en/resources/technical-articles/an-improved-and-simple-cable-simulation-model.html  
  Usage: Core source for modeling cables with skin effect and dielectric loss in SPICE-like tools.

### Passive components
- **SRC-027 — ANP074: Introduction to RF Inductors** (Würth Elektronik, Application note PDF, priority 4).  
  URL: https://www.we-online.com/components/media/o756030v410%20ANP074%20EN_Introduction%20to%20RF%20Inductors.pdf  
  Usage: Use for selecting inductors/beads around SRF and parasitic capacitance limits.
- **SRC-028 — ANP146: WE-CMDC Common Mode Chokes** (Würth Elektronik, Application note PDF, priority 4).  
  URL: https://www.we-online.com/components/media/o868432v410%20ANP146a_WE-CMDC_EN.pdf  
  Usage: Use for understanding CMC behavior, leakage inductance and practical filtering caveats.

### Power layout
- **SRC-012 — Practical Power Solutions, Section 4: Hardware Design Techniques** (Analog Devices, Handbook section PDF, priority 4).  
  URL: https://www.analog.com/media/en/training-seminars/design-handbooks/Practical-Power-Solutions/Section4.pdf  
  Usage: Use for practical parasitic effects: trace resistance, capacitance and power-supply grounding/layout.

### Power-supply EMI
- **SRC-030 — Introduction to EMI in Power Supply Designs** (Texas Instruments, PDF / presentation, priority 5).  
  URL: https://www.ti.com/lit/pdf/slyp757  
  Usage: Use for basic taxonomy: source-path-receptor, conducted vs radiated, typical ranges and mitigation categories.

### RF / mixed-signal layout
- **SRC-015 — PCB Layout Guidelines for RF & Mixed-Signal** (Analog Devices, Article, priority 4).  
  URL: https://www.analog.com/en/resources/technical-articles/pcbs-layout-guidelines-for-rf--mixedsignal.html  
  Usage: Use for parasitic inductance and bypass capacitor orientation / ground-via placement rules.

### RS-485
- **SRC-038 — The RS-485 Design Guide** (Texas Instruments, Application report PDF, priority 4).  
  URL: https://www.ti.com/lit/pdf/slla272  
  Usage: Use for RS-485 topology, termination, grounding/protection and robust network design.

### Radiated EMI / stack-up
- **SRC-008 — AN-1109: Recommendations for Control of Radiated Emissions with isoPower Devices** (Analog Devices, Application note, priority 5).  
  URL: https://www.analog.com/en/resources/app-notes/an-1109.html  
  Usage: Use later for radiated expansion: board layout, stack-up, stitching capacitance, edge guarding.

### Schematics / rule of thumb
- **SRC-006 — Proper Layout and Component Selection Controls EMI** (Analog Devices, Article, priority 4).  
  URL: https://www.analog.com/en/resources/technical-articles/proper-layout-and-component-selection-controls-emi.html  
  Usage: Use for rules about input impedance, inductors and bypassing in switchers; useful caution against brute-force capacitance.

### Stack-up / PDN
- **SRC-009 — AN-0971: Recommendations for Control of Radiated Emissions with isoPower Devices** (Analog Devices, Application note, priority 5).  
  URL: https://www.analog.com/en/resources/app-notes/an-0971.html  
  Usage: Use for PDN / stack-up heuristics around close plane spacing and interplane capacitance.

### USB
- **SRC-037 — AM335x and AM43xx USB Layout Guidelines** (Texas Instruments, Application report PDF, priority 4).  
  URL: https://www.ti.com/lit/an/sprabt8a/sprabt8a.pdf  
  Usage: Use for USB DP/DM rules: ESD placement, optional CMC placement, via capacitance.

### USB / hardware checklist
- **SRC-052 — EZ-USB FX2G3 Hardware Design Guidelines and Schematic Checklist** (Infineon, Application note PDF, priority 3).  
  URL: https://www.infineon.com/assets/row/public/documents/24/42/infineon-ez-usb-tm-fx2g3-hardware-design-guidelines-and-schematic-checklist-applicationnotes-en.pdf  
  Usage: Use for USB hardware design checklist including layout and reference-plane items.

### USB-C power
- **SRC-053 — EZ-PD PMG1 MCU Hardware Design Guidelines and Checklist** (Infineon, Application note PDF, priority 3).  
  URL: https://www.infineon.com/assets/row/public/documents/24/42/infineon-an232565-ez-pd-pmg1-mcu-hardware-design-guidelines-and-checklist-applicationnotes-en.pdf  
  Usage: Use for USB-C/PD power-port hardware checklist, protection and PCB layout context.

## Practical rules

- **R-001 — Schematic / general EMC**: For every EMC problem identify the source, the coupling path, and the victim / receiver.  
  Sources: SRC-026; SRC-030  
  Agent action: The agent should first ask about or infer the noise source, path, and receptor.
- **R-002 — Conducted EMI**: Separate disturbances into differential-mode and common-mode before selecting a filter.  
  Sources: SRC-001; SRC-003; SRC-021; SRC-022  
  Agent action: The agent should propose a CM / DM measurement or simulation or test filter variants separately.
- **R-003 — LTspice / testbench**: For conducted-EMI pre-compliance, generate a LISN, cables with parasitics, a 50 Ω measurement point, and separate CM / DM outputs.  
  Sources: SRC-001; SRC-022  
  Agent action: The agent should generate a ready LTspice testbench, not just describe the filter.
- **R-004 — DC/DC layout**: Minimize the hot loop — the input capacitor, switch, diode / MOSFET, and the return must be physically close.  
  Sources: SRC-031; SRC-044; SRC-023; SRC-024  
  Agent action: The agent should mark the hot loop on the schematic / netlist and generate a PCB checklist.
- **R-005 — DC/DC input filter**: Check the input-filter resonance with MLCC and wiring; add damping when peaking appears.  
  Sources: SRC-006; SRC-023; SRC-024  
  Agent action: The agent should perform an ESR / damping sweep and warn about a high Q.
- **R-006 — Decoupling capacitors**: HF caps must have a very short loop to the supply pin and the reference plane; capacitance value alone is not enough.  
  Sources: SRC-010; SRC-015; SRC-025  
  Agent action: The agent should evaluate placement, via count, and cap orientation.
- **R-007 — MLCC**: Account for DC bias, ESR/ESL, and SRF; nominal capacitance from the BOM is not the in-circuit capacitance.  
  Sources: SRC-018; SRC-024; SRC-025; SRC-058  
  Agent action: The agent should prefer frequency-dependent models or at least an RLC series model.
- **R-008 — Stack-up**: Route high-speed signals over a continuous reference plane; do not cross gaps in the reference.  
  Sources: SRC-034; SRC-035; SRC-048; SRC-056  
  Agent action: The agent should check the reference of every critical trace and via crossings.
- **R-009 — Stack-up / PDN**: Close power-ground plane spacing improves HF bypassing through interplane capacitance.  
  Sources: SRC-008; SRC-009; SRC-054  
  Agent action: The agent should suggest a stack-up with a close PWR / GND pair for high-speed / noisy circuits.
- **R-010 — Cables and traces**: Treat long cables and traces as transmission lines when the propagation time becomes significant relative to the rise time.  
  Sources: SRC-013; SRC-046; SRC-047; SRC-016  
  Agent action: The agent should choose the model: lumped RLC, RLGC sections, or a transmission line.
- **R-011 — High-speed interfaces**: Place ESD / EMI protection as close to the connector as possible, before a long unprotected trace.  
  Sources: SRC-035; SRC-037; SRC-052  
  Agent action: The agent should flag long unprotected segments between the connector and ESD.
- **R-012 — USB**: Treat a common-mode choke on USB as an EMI option but check SI degradation; ESD is usually closer to the connector than the CMC.  
  Sources: SRC-037; SRC-035; SRC-052  
  Agent action: The agent should recommend a footprint with a bypass option or A / B variants, not a mandatory CMC.
- **R-013 — CAN / RS-485**: Termination, split termination, TVS, and CMC must be matched to topology, speed, and EMC requirements; a CMC is not a free filter.  
  Sources: SRC-038; SRC-039; SRC-046  
  Agent action: The agent should distinguish EMC, immunity, and signal integrity.
- **R-014 — Ethernet / SPE**: For Ethernet pay attention to magnetics / CMC, chassis bonding, PHY supply, and clocks.  
  Sources: SRC-040; SRC-041; SRC-042; SRC-055  
  Agent action: The agent should analyze the interface as a system: PHY, magnetics, cable, chassis.
- **R-015 — AC/DC**: In line filters, analyze L / N / PE paths separately, CM / DM currents, and the safety of X / Y capacitors.  
  Sources: SRC-022; SRC-050; SRC-051  
  Agent action: The agent should apply safety warnings and not suggest uncertified Y / X components.
- **R-016 — AC/DC flyback**: Minimize the primary switching loop, control the snubber / clamp, and the primary-to-secondary transformer capacitance.  
  Sources: SRC-050; SRC-051; SRC-020  
  Agent action: The agent should propose a snubber sweep and transformer / parasitics analysis.
- **R-017 — Radiated later**: Start radiated EMI work by reducing the source and current loops; treat shielding as a system-level measure, not a first patch.  
  Sources: SRC-008; SRC-026; SRC-042  
  Agent action: The agent should avoid promising certification without mechanical data, cables, and measurements.
- **R-018 — DFM**: Check every PCB rule against the actual fabricator: minimum trace / clearance, drills, annular ring, via fill, soldermask.  
  Sources: SRC-061; SRC-067; SRC-066; SRC-070  
  Agent action: The agent should ask about the fab house or assume a manufacturing profile.
- **R-019 — Controlled impedance**: Do not design impedance from trace widths alone without a stack-up and dielectric from the fabricator.  
  Sources: SRC-068; SRC-054; SRC-055  
  Agent action: The agent should generate a recommendation with assumptions and require stack-up confirmation.
- **R-020 — Agent safety / credibility**: Do not promise EMC compliance; describe the result as pre-compliance / risk reduction and always recommend a validation measurement.  
  Sources: SRC-001; SRC-030; SRC-048  
  Agent action: The agent should add a disclaimer in reports and recommendations.
