"""LDO netlist (ngspice) built from the sizes in sizes.json.

Topology (theory note, Sec. 3):
  error amplifier : PMOS-input five-transistor OTA (M1-M5), NMOS mirror load
  buffer          : PMOS source follower MB (bulk tied to source), current source MBS
  pass device     : PMOS MP (bulk = VIN)
  feedback        : R1 (VOUT->FB), R2 (FB->GND); VREF ideal
  bias            : ideal IREF into diode MBIAS, mirrored to the tail (M5) and MBS
  load            : CL with series ESR, ideal current sink IL
Node names: vin, vout, fb (divider tap), fbi (EA input; = fb unless the loop is
broken), ea (EA output), g (pass gate), tail, d1 (mirror diode), pb (PMOS bias).
"""
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
SIZES = os.environ.get("LDO_SIZES", "sizes.json")
S = json.loads((ROOT / "scripts" / SIZES).read_text())


def mos(name, d, g, s, b, model, W, L, m=1):
    # simple junction geometry: 0.5 um diffusion length each side of the gate
    ad = W * 0.5e-6
    pd = 2 * W + 1e-6
    return (f"{name} {d} {g} {s} {b} {model} W={W:.4g} L={L:.4g} M={m} "
            f"AD={ad:.4g} AS={ad:.4g} PD={pd:.4g} PS={pd:.4g}")


def core(loop_break=False, esr=None, cl=None):
    s = S
    esr = s["ESR"] if esr is None else esr
    cl = s["CL"] if cl is None else cl
    lines = [
        ".include cmos180.lib",
        # bias
        f"iref pb 0 {s['IREF']}",
        mos("mbias", "pb", "pb", "vin", "vin", "PMOS", s["Wbias"], s["Lbias"]),
        # error amplifier: M1 gate = feedback (diode side), M2 gate = VREF
        mos("m5", "tail", "pb", "vin", "vin", "PMOS", s["W5"], s["L5"]),
        mos("m1", "d1", "fbi", "tail", "tail", "PMOS", s["W12"], s["L12"]),
        mos("m2", "ea", "vref", "tail", "tail", "PMOS", s["W12"], s["L12"]),
        mos("m3", "d1", "d1", "0", "0", "NMOS", s["W34"], s["L34"]),
        mos("m4", "ea", "d1", "0", "0", "NMOS", s["W34"], s["L34"]),
        f"vref vref 0 {s['VREF']}",
        # buffer: PMOS source follower, output = pass gate g
        mos("mbs", "g", "pb", "vin", "vin", "PMOS", s["WBS"], s["LBS"]),
        mos("mb", "0", "ea", "g", "g", "PMOS", s["WB"], s["LB"]),
        # pass device (W given per finger, M fingers)
        mos("mp", "vout", "g", "vin", "vin", "PMOS", s["WPf"], s["LP"], s["MP"]),
        # feedback divider
        f"r1 vout fb {s['R1']}",
        f"r2 fb 0 {s['R2']}",
        # output capacitor with ESR
        f"cl vout nesr {cl}",
        f"resr nesr 0 {esr}",
    ]
    if loop_break:
        # DC path closes the loop; AC test signal enters at fbi only
        lines += ["lbrk fb fbi 1e9", "cbrk fbi vt 1e3", "vt vt 0 dc 0 ac 1"]
    else:
        lines += ["rshort fb fbi 1e-3"]
    return "\n".join(lines)


if __name__ == "__main__":
    print(core())
