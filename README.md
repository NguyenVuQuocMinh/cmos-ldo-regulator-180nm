# CMOS Low-Dropout Regulator (0.18 µm): theory, hand design and ngspice verification

A 1.5 V, 50 mA PMOS low-dropout (LDO) regulator designed from a written specification. Every formula
used in the design is proved, every transistor is sized by hand, and the result is checked in ngspice.

![LDO schematic in Electric](figures/schematic_electric.png)

Schematic of the final design (v3) in the Electric VLSI editor, cell `ldo180{sch}` of
[`schematic/ldo180.jelib`](schematic/ldo180.jelib). Labels give W/L in µm (×300 = number of pass-device
fingers). Its netlist matches the simulated circuit device by device (see
[Schematic in Electric](#schematic-in-electric)). The PDFs use a redrawn version of the same circuit
([`figures/schematic.png`](figures/schematic.png)).

## Documents

| File | Content |
|---|---|
| [`doc/ldo_theory_proofs.pdf`](doc/ldo_theory_proofs.pdf) | **Part 1, theory (6 pages).** Proofs of the formulas: square law, triode and weak-inversion small-signal parameters; loop polarity; the static output equation (accuracy, load and line regulation from one equation); pass-device and headroom conditions; loop gain, poles and ESR zero; unity-gain frequency and phase margin; why the error-amplifier pole does not depend on its current; ESR window; PSRR (including its collapse near dropout); load-step response. |
| [`doc/ldo_hand_design.pdf`](doc/ldo_hand_design.pdf) | **Part 2, hand design (7 pages).** Parameter extraction from the BSIM3 model; step-by-step calculation of every W/L, bias current and resistor from the specification; simulation results; three design iterations; a hand-versus-simulation table with the reasons for each gap; VIN and temperature corners. |

## Specification and simulated results (final design, typical model, 27 °C)

| Quantity | Condition | Spec | Simulated |
|---|---|---|---|
| Output voltage | VIN 1.7–1.9 V, IL 0.1–50 mA | 1.5 V | 1.4954–1.5053 V |
| Dropout | IL = 50 mA, VOUT within 1 % | ≤ 200 mV | 141 mV |
| Phase margin | all loads, ESR 0–50 mΩ, VIN/T corners | ≥ 45° | 71.1° nominal, 60.0° worst |
| PSRR | 1 kHz, 50 mA, VIN = 1.8 V | ≥ 30 dB | 31.0 dB |
| Load regulation | 0.1 → 50 mA | ≤ 15 mV | 9.9 mV |
| Line regulation | 1.7 → 1.9 V | ≤ 35 mV/V | 29.9 mV/V (worst load) |
| Quiescent current | incl. divider | ≤ 100 µA | 84.7 µA |
| Load transient | 0.1 ↔ 50 mA, 1 µs edges | ≤ 50 mV | 9.9 mV |

Output capacitor: 2.2 µF ceramic. Margins that are thin are listed openly in Part 2, Section 4.4. PSRR is
29.8 dB at VIN = 1.9 V, 0 °C, light load (headroom limit of the error amplifier). Near dropout (VIN = 1.7 V,
85 °C) the PSRR falls to 15.6 dB because the pass device enters triode.

## Architecture

- **Pass device:** PMOS, 300 × 10 µm / 0.18 µm.
- **Error amplifier:** five-transistor OTA with a PMOS input pair (VREF = 0.6 V). The input pair uses
  L = 1 µm and the NMOS mirror uses L = 3 µm.
- **Buffer:** PMOS source follower (bulk tied to source) that drives the 7 pF pass-device gate.
- **Feedback:** resistive divider, 90 kΩ / 60 kΩ.
- **Bias and reference:** ideal 5 µA bias current; ideal VREF (no bandgap in this project).

## Schematic in Electric

The final circuit (v3) is drawn in the [Electric VLSI](https://www.staticfreesoft.com/) 9.08 schematic
editor as cell `ldo180{sch}`: nine 4-terminal MOSFETs with their W/L (and M = 300 for the pass device) as
attributes, the two divider resistors, and five pins (`vin`, `gnd`, `vout`, `vref`, `ibias`). The ideal
bias current, VREF, the output capacitor with its ESR and the load are test-bench parts, not part of the
chip. The cell is built with Electric's database API from `schematic/gen_schematic.py` (wire by wire, so it
can be regenerated), and can be opened and edited in Electric as usual.

Electric's own SPICE writer turns the drawing into [`schematic/ldo180_electric.spi`](schematic/ldo180_electric.spi).
`schematic/check_netlist.py` then checks that this is the circuit behind every result:

1. **Netlist comparison.** All 11 devices of Electric's netlist match the Python netlist used for the
   simulations (`scripts/ldo_netlist.py`, `sizes_v3.json`): terminals (including the bulk of the input pair
   tied to the tail and the bulk of the follower tied to its source), model, W, L, M and R.
2. **Re-simulation.** The same test benches run on Electric's netlist give the published v3 numbers:

| Quantity | Published (v3) | Electric netlist |
|---|---|---|
| Load regulation, 0.1 → 50 mA | 9.879 mV | 9.879 mV |
| Line regulation, 50 mA | 29.94 mV/V | 29.94 mV/V |
| PSRR at 1 kHz, 0.1 / 50 mA | 31.44 / 31.02 dB | 31.44 / 31.02 dB |
| Load-step dip | 9.891 mV | 9.891 mV |
| Phase margin, 0.1 / 1 / 10 / 50 mA | 89.9 / 88.7 / 80.4 / 71.1° | 89.9 / 88.7 / 80.4 / 71.1° |
| DC loop gain, 0.1 / 1 / 10 / 50 mA | 58.6 / 59.5 / 58.9 / 52.3 dB | 58.6 / 59.5 / 58.9 / 52.3 dB |

All differences are at most 1e-7 in the units shown (rounding). Two test-bench conventions apply to both flows: Electric writes
sizes in schematic units (µm) with `.opt scale=0.2U`, which the test bench replaces by `.option scale=1e-6`;
and the drain/source areas and perimeters (AD, AS, PD, PS), which are layout data and not part of a
schematic, are added with the same rule as in `ldo_netlist.py` (0.5 µm of diffusion on each side).

## How the design evolved

| Version | Change | Result |
|---|---|---|
| v1 | L = 1 µm in the error amplifier | stable (PM 81°), but PSRR 28.8 dB and line regulation 39 mV/V miss the spec |
| v2 | L = 2 µm for all four EA devices | meets the spec at nominal, but PM drops to 44° at a corner with ESR = 0, and PSRR to 22 dB at VIN = 1.9 V |
| v3 | only the mirror lengthened (3 µm); buffer V_SG set from a headroom window | meets all specs at nominal, PM about 60° or more at all corners |

The hand calculation overestimated the error-amplifier gain (164 against 99 simulated). The square-law
g_m/I_D is 20 V⁻¹, but the simulated value is 16.6 V⁻¹, and the effective λ is higher at the real
operating points. With the simulated g_m and g_ds put back into the same formulas, the loop gain, the
unity-gain frequency and the load regulation agree with simulation to within about 1 dB, 7 % and 0.5 mV.

## Repository layout

```
doc/        ldo_theory_proofs.pdf, ldo_hand_design.pdf and their sources (*.tex.in, schematic.tex)
scripts/    Python flow: device characterisation, hand design, simulations, document rendering
            + all results as JSON (params, hand, sizes_v1..v3, sim_*_v1..v3)
figures/    plots used in the documents
netlists/   final circuit (v3) with operating-point, loop-gain, PSRR, line, load and load-step test benches
schematic/  Electric schematic (ldo180.jelib), its generator, Electric's SPICE netlist and the
            netlist / re-simulation check (check_netlist.py, check_netlist.json)
sim/        working folder for ngspice runs (place the model file here)
```

## Reproducing

Tools: ngspice-46 (batch mode), Python 3 with numpy, scipy and matplotlib, and
[Tectonic](https://tectonic-typesetting.github.io/) for the PDFs.

The 0.18 µm BSIM3v3.1 model file used (`cmos180.lib`, 1.8 V devices, t_ox = 4.1 nm, from university
coursework) is **not redistributed**. Put a BSIM3 model file defining `.model NMOS` and `.model PMOS` at
`sim/cmos180.lib` (and next to the netlists if you run those directly). Set the environment variable
`NGSPICE` to `ngspice_con` if it is not at the default Windows path.

```
cd scripts
python char_devices.py                      # square-law parameters, gm/ID plot
python design.py                            # hand design -> sizes_v1/v2/v3.json, hand.json
# for N in 1 2 3:  LDO_SIZES=sizes_vN.json  LDO_VER=vN
python sim_op.py && python sim_all.py && python sim_extra.py
python render.py path/to/tectonic           # fill numbers into both documents and build the PDFs
```

Every number in the two PDFs is filled in by `render.py` from the JSON results; none is typed by hand.

Schematic (needs Java and the Electric 9.08 jar; set `ELECTRIC_JAR` if it is not at
`C:\Electric\electricBinaryFull-9.08.jar`):

```
cd schematic
python gen_schematic.py                     # builds ldo180.jelib and writes ldo180_electric.spi
python check_netlist.py                     # device-by-device comparison + re-simulation
```

## Limitations

The model is typical only: no process corners and no Monte Carlo mismatch analysis. VREF and the bias
current are ideal. The work is at schematic level, with no layout parasitics or bond-wire inductance.
Start-up, current limit, noise and soft-start are not covered.
