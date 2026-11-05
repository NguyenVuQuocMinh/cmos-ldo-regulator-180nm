"""Draw the 0.18 um LDO (final design v3) as an Electric schematic and export
Electric's own SPICE netlist of it.

Cell ldo180{sch} in library schematic/ldo180.jelib: nine 4-terminal MOSFETs and
the two divider resistors. The ideal bias current, VREF, the output capacitor
with its ESR and the load are not part of the chip; they are added by the test
bench (check_netlist.py). Exports: vin, gnd, vout, vref, ibias (= node pb, the
external bias current is pulled out of it).

Symbol orientations (Electric 4-port transistor, port offsets from the centre):
  PL  pmos, gate left,  source up : g(-1,0) s(2,2)  d(2,-2)  b(2,1)
  PR  pmos, gate right, source up : g(1,0)  s(-2,2) d(-2,-2) b(-2,1)
  NL  nmos, gate left,  drain up  : g(-1,0) d(2,2)  s(2,-2)  b(2,-1)
  NR  nmos, gate right, drain up  : g(1,0)  d(-2,2) s(-2,-2) b(-2,-1)
  RV  resistor, vertical          : a(0,-2) b(0,2)
"""
import json
import os
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent
ELECTRIC = os.environ.get("ELECTRIC_JAR", r"C:\Electric\electricBinaryFull-9.08.jar")
S = json.loads((ROOT.parent / "scripts" / "sizes_v3.json").read_text())

ORIENT = {  # code: (angle, flipX, flipY, port offsets)
    "PL": (900, 0, 1, {"g": (-1, 0), "s": (2, 2), "d": (2, -2), "b": (2, 1)}),
    "PR": (2700, 0, 0, {"g": (1, 0), "s": (-2, 2), "d": (-2, -2), "b": (-2, 1)}),
    "NL": (900, 0, 0, {"g": (-1, 0), "d": (2, 2), "s": (2, -2), "b": (2, -1)}),
    "NR": (900, 1, 0, {"g": (1, 0), "d": (-2, 2), "s": (-2, -2), "b": (-2, -1)}),
    "RV": (900, 0, 0, {"a": (0, -2), "b": (0, 2)}),
}


class Sch:
    def __init__(self):
        self.cmd = []
        self.ports = {}       # (dev, port) -> (x, y)
        self.pins = {}        # (x, y) -> pin id
        self.n = 0

    def c(self, s):
        self.cmd.append(s)

    def dev(self, name, kind, orient, x, y, W=None, L=None, M=None, R=None):
        ang, fx, fy, offs = ORIENT[orient]
        proto = "sch:Resistor" if kind == "res" else "sch:4-Port-Transistor"
        self.c(f"N {name} {proto} {x} {y} 0 0 {ang} {fx} {fy}")
        if kind == "res":
            self.c(f"DV {name} SCHEM_resistance {R}")
        else:
            self.c(f"FN {name} {kind}4")
            self.c(f"DV {name} ATTR_width {W * 1e6:g} num")
            self.c(f"DV {name} ATTR_length {L * 1e6:g} num")
            if M:
                self.c(f"DV {name} ATTR_M {M} num")
            self.c(f"VAR {name} SIM_spice_model {'PMOS' if kind == 'pmos' else 'NMOS'}")
        for p, (dx, dy) in offs.items():
            self.ports[(name, p)] = (x + dx, y + dy)

    def pin(self, x, y):
        if (x, y) not in self.pins:
            self.n += 1
            pid = f"w{self.n}"
            self.c(f"N {pid} sch:Wire_Pin {x} {y} 0 0")
            self.pins[(x, y)] = pid
        return self.pins[(x, y)]

    def end(self, e):
        """endpoint: ('dev', 'port') tuple of strings, or an (x, y) point -> (id, port, x, y)"""
        if isinstance(e[0], str):
            x, y = self.ports[e]
            return e[0], e[1], x, y
        return self.pin(*e), "-", e[0], e[1]

    def wire(self, *pts, name=None):
        ends = [self.end(p) for p in pts]
        for k in range(len(ends) - 1):
            a, b = ends[k], ends[k + 1]
            assert a[2] == b[2] or a[3] == b[3], f"diagonal wire {a} -> {b}"
            nm = f" {name}" if (name and k == 0) else ""
            self.c(f"A sch:wire 0 {a[0]} {a[1]} {a[2]} {a[3]} {b[0]} {b[1]} {b[2]} {b[3]}{nm}")

    def export(self, name, xy, kind):
        self.c(f"E {name} {self.pin(*xy)} - {kind}")


def build():
    s = Sch()
    lib = (ROOT / "ldo180.jelib").as_posix()
    s.c(f"LIB {lib} ldo180")
    s.c("CELL ldo180 sch")
    # devices -------------------------------------------------------------
    s.dev("mbias", "pmos", "PR", 0, 20, S["Wbias"], S["Lbias"])
    s.dev("m5", "pmos", "PL", 10, 20, S["W5"], S["L5"])
    s.dev("mbs", "pmos", "PL", 34, 20, S["WBS"], S["LBS"])
    s.dev("mp", "pmos", "PL", 50, 20, S["WPf"], S["LP"], M=S["MP"])
    s.dev("m1", "pmos", "PL", 10, 10, S["W12"], S["L12"])
    s.dev("m2", "pmos", "PR", 22, 10, S["W12"], S["L12"])
    s.dev("m3", "nmos", "NR", 14, 0, S["W34"], S["L34"])
    s.dev("m4", "nmos", "NL", 18, 0, S["W34"], S["L34"])
    s.dev("mb", "pmos", "PL", 34, 6, S["WB"], S["LB"])
    s.dev("r1", "res", "RV", 52, 6, R=f"{S['R1'] / 1e3:g}k")
    s.dev("r2", "res", "RV", 52, -6, R=f"{S['R2'] / 1e3:g}k")
    # supply rails ----------------------------------------------------------
    s.wire((-6, 30), (-2, 30), (12, 30), (36, 30), (52, 30), name="vin")
    for d in ("mbias", "m5", "mbs", "mp"):
        x = s.ports[(d, "s")][0]
        s.wire((d, "s"), (x, 30))
        s.wire((d, "b"), (d, "s"))                      # bulk = source = vin
    s.wire((8, -30), (12, -30), (20, -30), (36, -30), (52, -30), name="gnd")
    for d in ("m3", "m4"):
        x = s.ports[(d, "s")][0]
        s.wire((d, "s"), (x, -30))
        s.wire((d, "b"), (d, "s"))                      # bulk = source = gnd
    s.wire(("mb", "d"), (36, -30))
    s.wire(("r2", "a"), (52, -30))
    # bias: pb ---------------------------------------------------------------
    s.wire(("mbias", "g"), (4, 20), ("m5", "g"), name="pb")
    s.wire(("mbias", "d"), (-2, 16), (4, 16), (4, 20))   # diode connection
    s.wire((-2, 16), (-2, 13))                           # ibias pin
    s.wire((4, 20), (4, 26), (30, 26), (30, 20), ("mbs", "g"))
    # error amplifier ----------------------------------------------------------
    s.wire(("m5", "d"), (12, 14), (20, 14), name="tail")
    s.wire(("m1", "s"), (12, 14))
    s.wire(("m2", "s"), (20, 14))
    s.wire(("m1", "b"), ("m1", "s"))                    # input-pair bulk = tail
    s.wire(("m2", "b"), ("m2", "s"))
    s.wire(("m1", "d"), (12, 5), ("m3", "d"), name="d1")
    s.wire((12, 5), (16, 5), (16, 0))
    s.wire(("m3", "g"), (16, 0), ("m4", "g"))
    s.wire(("m2", "d"), (20, 6), ("m4", "d"), name="ea")
    s.wire((20, 6), ("mb", "g"))
    # buffer and pass device -----------------------------------------------------
    s.wire(("mbs", "d"), (36, 13), ("mb", "s"), name="g")
    s.wire(("mb", "b"), ("mb", "s"))                    # follower bulk = its source
    s.wire((36, 13), (46, 13), (46, 20), ("mp", "g"))
    # output and divider -----------------------------------------------------------
    s.wire(("mp", "d"), (52, 12), ("r1", "b"), name="vout")
    s.wire((52, 12), (58, 12))
    s.wire(("r1", "a"), (52, -1), ("r2", "b"))
    s.wire((52, -1), (56, -1), name="fb")               # net label at the divider
    s.wire(("m1", "g"), (5, 10), name="fb")             # same label at the OTA input
    s.wire(("m2", "g"), (26, 10))
    # exports ------------------------------------------------------------------------
    s.export("vin", (-6, 30), "pwr")
    s.export("gnd", (8, -30), "gnd")
    s.export("vout", (58, 12), "out")
    s.export("vref", (26, 10), "in")
    s.export("ibias", (-2, 13), "bidir")
    s.c("SAVE")
    s.c(f"SPICE ldo180{{sch}} {(ROOT / 'ldo180_electric.spi').as_posix()}")
    return s


def run(cmd, tag):
    cmdf = ROOT / f"{tag}.cmd"
    cmdf.write_text("\n".join(cmd) + "\n")
    res = subprocess.run(["java", f"-Dldo.cmd={cmdf}", "-jar", ELECTRIC, "-batch", "-s",
                          str(ROOT / "electric_runtime.bsh")],
                         cwd=str(ROOT), capture_output=True, text=True, timeout=600)
    out = res.stdout + res.stderr
    (ROOT / f"{tag}.log").write_text(out)
    return out


if __name__ == "__main__":
    s = build()
    out = run(s.cmd, "gen_schematic")
    print("\n".join(l for l in out.splitlines()
                    if l.startswith(("ERR", "RUNTIME")) or "rror" in l or "WARN" in l or "written" in l))
