# Knowledge base: PCB parasitics for LTspice / EMC

Goal: propose R/L/C values for traces, polygons, vias, cables, and capacitors when no full field extraction is available.

## Usage rules for agents

- **G001 No exactness without geometry** — If stack-up, trace length/width, return plane, via geometry or cable type are unknown, output ranges and sensitivity sweeps, not exact values.
- **G002 Use production stack-up** — For controlled impedance and parasitics, use the fabricator's finished stack-up, dielectric thickness, Er/Df and copper data; generic FR-4 is only for early estimates.
- **G003 Prefer vendor models** — For MLCCs, ferrites, inductors, CM chokes and EMI filters, use vendor impedance/SPICE/S-parameter models when possible; rules of thumb are fallbacks.
- **G004 Do not certify EMC** — The tool supports pre-compliance and risk reduction. It must not state that a design will pass CISPR/IEC/EN tests.
- **G005 Separate safety from EMC** — For AC/DC and mains, creepage/clearance/safety are separate compliance requirements and must be checked against legal standards.
- **G006 Escalate above lumped validity** — At high frequencies or long structures, switch from lumped RLC to transmission-line, S-parameter or field-solver models.
- **G007 Always include uncertainty** — Every proposed parasitic value should include min/typ/max or confidence. Default uncertainty at least ±2× for guessed layout parasitics.
- **G008 Model return path explicitly** — Inductance is loop inductance, not just trace inductance. Always identify the return current path.
- **G009 Use sensitivity sweeps** — For EMI, a single guessed parasitic value is insufficient. Generate .step sweeps and report which assumptions dominate results.
- **G010 Use measurements to calibrate** — When waveform ringing or EMI scan data exists, fit parasitic values and update the default model.

## Key quick values

- 1 oz Cu: ~0.49 mΩ/square at 20°C.
- 50Ω line over plane: ~0.25–0.35 nH/mm and ~0.10–0.14 pF/mm.
- Trace without close return plane: often ~0.6–1.2 nH/mm; use isolated-conductor formula only as a rough upper-bound.
- Via through 1.6 mm PCB: ~0.8–1.5 nH; via capacitance often ~0.1–0.6 pF.
- Plane capacitance: C[pF] = 0.008854·εr·A_mm²/d_mm.
- Plane pair inductance: L[nH] ≈ 1.257·d_mm·length/width.
- Belden 8760 example cable: 0.59 µH/m and 89.2 pF/m.
- Resonance: f_MHz ≈ 5033/sqrt(L_nH·C_pF).

## Source index

- **S001** — PCB Design Guidelines For Reduced EMI (Texas Instruments): https://www.ti.com/lit/pdf/szza009
- **S002** — How to Get the Best Results Using LTspice for EMC Simulation — Part 1 (Analog Devices): https://www.analog.com/en/resources/technical-articles/how-to-get-the-best-results-using-ltspice-part-1.html
- **S003** — EMC Design Tips 2025 (Würth Elektronik): https://www.we-online.com/files/pdf1/emc-design-tips-2025_en.pdf
- **S004** — Saturn PCB Toolkit (Saturn PCB Design): https://saturnpcb.com/saturn-pcb-toolkit/
- **S005** — Microstrip Transmission Line Calculator Using IPC-2141 Equation (Chemandy Electronics): https://chemandy.com/calculators/microstrip-transmission-line-calculator-ipc2141.htm
- **S006** — PCB Impedance Calculator (Sierra Circuits / ProtoExpress): https://www.protoexpress.com/tools/pcb-impedance-calculator/
- **S007** — Section 5 High Speed PCB Layout Techniques (Texas Instruments): https://www.ti.com/lit/ml/slyp173/slyp173.pdf
- **S008** — Decoupling Capacitors (Texas Instruments): https://www.ti.com/content/dam/videos/external-videos/de-de/9/3816841626001/6313253251112.mp4/subassets/notes-decoupling_capacitors.pdf
- **S009** — AN-136: PCB Layout Considerations for Non-Isolated Switching Power Supplies (Analog Devices): https://www.analog.com/en/resources/app-notes/an-136.html
- **S010** — Belden 8760 Multi-Pair Cable (Belden): https://www.belden.com/products/cable/electronic-wire-cable/multi-pair-cable/8760
- **S011** — AN-905: Transmission Line RAPIDESIGNER Operation and Applications Guide (Texas Instruments / National Semiconductor): https://www.ti.com/lit/pdf/snla035
- **S012** — EMI/EMC — EMC Inductors and Filters (Würth Elektronik / IEEE.li mirror): https://www.ieee.li/pdf/viewgraphs/emc_inductors_and_filters.pdf
- **S013** — MT-101: Decoupling Techniques (Analog Devices): https://www.analog.com/media/en/training-seminars/tutorials/MT-101.pdf
- **S014** — General hardware design / BGA PCB design / BGA decoupling (Texas Instruments): https://www.ti.com/lit/pdf/sprabv2
- **S015** — Methods of using low-ESL capacitors (Murata): https://article.murata.com/en-global/article/methods-of-using-low-esl-capacitors
- **S016** — Noise Rejection Mechanism of 3-Terminal Capacitor (Murata): https://www.murata.com/products/capacitor/ceramiccapacitor/library/solution/3-terminal-capacitor
- **S017** — Conducted emissions in DC-DC converters — simulation versus measurement (Rohde & Schwarz): https://www.rohde-schwarz.com/nl/applications/conducted-emissions-in-dc-dc-converters-simulation-versus-measurement_56279-1125376.html
- **S018** — AN-991: Line Driving and System Design (Texas Instruments / National Semiconductor): https://www.ti.com/lit/pdf/snla043
- **S019** — AN-808: Long Transmission Lines and Data Signal Quality (Texas Instruments / National Semiconductor): https://www.ti.com/lit/pdf/snla028
- **S020** — Fundamentals of Electromagnetic Compliance (Coilcraft): https://www.coilcraft.com/en-us/resources/application-notes/fundamentals-of-electromagnetic-compliance/
- **S021** — Taming Parasitics in Buck Converters Using a Snubber (Analog Devices): https://www.analog.com/en/resources/technical-articles/the-unseen-ring.html
- **S022** — PCB layout guidelines to optimize power supply performance (Texas Instruments): https://www.ti.com/lit/ml/slyp762/slyp762.pdf
- **S023** — Layout Considerations for LMG5200 GaN Power Stage (Texas Instruments): https://www.ti.com/lit/pdf/snva729
- **S024** — Embedded Microstrip Impedance Calculator (Clemson CVEL): https://cecas.clemson.edu/cvel/emc/calculators/PCB-TL_Calculator/embedded.html
- **S025** — Rectangular capacitor with edge effect calculator (Chemandy Electronics): https://chemandy.com/calculators/rectangular-capacitor-calculator.htm
- **S026** — Flat Wire Inductor Calculator (Chemandy Electronics): https://chemandy.com/calculators/flat-wire-inductor-calculator.htm
- **S027** — PCB Trace Impedance Calculator IPC-2141 (DigiKey): https://www.digikey.com/en/resources/conversion-calculators/conversion-calculator-pcb-trace-impedance
- **S028** — PCB Trace Inductance Calculation: How Wide is Too Wide? (Altium): https://resources.altium.com/p/pcb-trace-inductance-and-width-how-wide-too-wide
- **S029** — Design for EMC 2026 (Würth Elektronik): https://www.we-online.com/files/pdf1/03.-design-for-emc-2026.pdf
- **S030** — AN-202: An IC Amplifier User's Guide to Decoupling, Grounding, and Making Things Go Right (Analog Devices): https://www.analog.com/media/en/technical-documentation/application-notes/AN-202.pdf
