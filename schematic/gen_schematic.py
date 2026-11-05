"""Draw the 0.18 um LDO (final design v4) as an Electric schematic and export
Electric's own SPICE netlist of it.

Cell ldo180{sch} in library schematic/ldo180.jelib: nine 4-terminal MOSFETs and
the two divider resistors. The ideal bias current, VREF, the output capacitor
with its ESR and the load are not part of the chip; they are added by the test
bench (check_netlist.py). Exports: vin, gnd, vout, vref, ibias (= node pb, the
external bias current is pulled out of it).

Drawing conventions: W/L, M and R are attributes of the devices (used by the
SPICE writer) but not drawn; a text label beside each symbol shows the device
name and its size, on the side away from the gate. Net labels sit beside the
wire. Wire pins carry no names.

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
S = json.loads((ROOT.parent / "scripts" / "sizes_v4.json").read_text())

ORIENT = {  # code: (angle, flipX, flipY, port offsets, side of the label: +1 right, -1 left)
    "PL": (900, 0, 1, {"g": (-1, 0), "s": (2, 2), "d": (2, -2), "b": (2, 1)}, 1),
    "PR": (2700, 0, 0, {"g": (1, 0), "s": (-2, 2), "d": (-2, -2), "b": (-2, 1)}, -1),
    "NL": (900, 0, 0, {"g": (-1, 0), "d": (2, 2), "s": (2, -2), "b": (2, -1)}, 1),
    "NR": (900, 1, 0, {"g": (1, 0), "d": (-2, 2), "s": (-2, -2), "b": (-2, -1)}, -1),
    "RV": (900, 0, 0, {"a": (0, -2), "b": (0, 2)}, 1),
}
CHAR_W = 0.62        # approximate width of one character at relative size 1 (grid units)
LINE_H = 1.5         # line pitch of the device labels


def fmt(v):
    return f"{v:g}"


class Sch:
    def __init__(self):
        self.cmd = []
        self.ports = {}       # (dev, port) -> (x, y)
        self.pins = {}        # (x, y) -> pin id
        self.n = 0

    def c(self, s):
        self.cmd.append(s)

    def P(self, dev, port):
        return self.ports[(dev, port)]

    def dev(self, name, kind, orient, x, y, W=None, L=None, M=None, R=None, label=None):
        ang, fx, fy, offs, side = ORIENT[orient]
        proto = "sch:Resistor" if kind == "res" else "sch:4-Port-Transistor"
        self.c(f"N {name} {proto} {x} {y} 0 0 {ang} {fx} {fy}")
        self.c(f"HIDENAME {name}")
        if kind == "res":
            self.c(f"VAR {name} SCHEM_resistance {R}")
            lines = [label or name.upper(), R]
        else:
            self.c(f"FN {name} {kind}4")
            self.c(f"SZ {name} {fmt(W * 1e6)} {fmt(L * 1e6)}")
            if M:
                self.c(f"NV {name} ATTR_M {M}")
            self.c(f"VAR {name} SIM_spice_model {'PMOS' if kind == 'pmos' else 'NMOS'}")
            lines = [label or name.upper(), f"{fmt(W * 1e6)}/{fmt(L * 1e6)}"]
            if M:
                lines.append(f"x{M}")
        for p, (dx, dy) in offs.items():
            self.ports[(name, p)] = (x + dx, y + dy)
        # label beside the symbol, away from the gate: start 1.2 units past the
        # channel (or the resistor body), lines stacked around the device centre
        edge = x + side * (2.0 if kind != "res" else 1.0) + side * 1.2
        y0 = y + (len(lines) - 1) * LINE_H / 2
        for k, txt in enumerate(lines):
            half = len(txt) * CHAR_W / 2
            self.c(f"TXT {round(edge + side * half, 2)} {round(y0 - k * LINE_H, 2)} 1 {txt}")

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

    def wire(self, *pts, name=None, seg=0):
        """orthogonal polyline; `name` labels segment `seg`, drawn beside the wire
        (above a horizontal segment, right of a vertical one)"""
        ends = [self.end(p) for p in pts]
        for k in range(len(ends) - 1):
            a, b = ends[k], ends[k + 1]
            assert a[2] == b[2] or a[3] == b[3], f"diagonal wire {a} -> {b}"
            lab = ""
            if name and k == seg:
                off = (0, 1.2) if a[3] == b[3] else (0.6 + len(name) * CHAR_W / 2, 0)
                lab = f" {name} {off[0]} {off[1]}"
            self.c(f"A sch:wire 0 {a[0]} {a[1]} {a[2]} {a[3]} {b[0]} {b[1]} {b[2]} {b[3]}{lab}")

    def export(self, name, xy, kind):
        self.c(f"E {name} {self.pin(*xy)} - {kind}")


def build():
    s = Sch()
    P = s.P
    lib = (ROOT / "ldo180.jelib").as_posix()
    s.c(f"LIB {lib} ldo180")
    s.c("CELL ldo180 sch")
    VIN, GND = 70, -28          # gnd rail just below the lowest device (R2 ends at -22)
    # devices -------------------------------------------------------------
    s.dev("mbias", "pmos", "PR", 0, 46, S["Wbias"], S["Lbias"], label="MBIAS")
    s.dev("m5", "pmos", "PL", 24, 46, S["W5"], S["L5"])
    s.dev("mbs", "pmos", "PL", 80, 46, S["WBS"], S["LBS"], label="MBS")
    s.dev("mp", "pmos", "PL", 120, 46, S["WPf"], S["LP"], M=S["MP"], label="MP")
    s.dev("m1", "pmos", "PL", 24, 22, S["W12"], S["L12"])
    s.dev("m2", "pmos", "PR", 52, 22, S["W12"], S["L12"])
    s.dev("m3", "nmos", "NR", 28, -6, S["W34"], S["L34"])
    s.dev("m4", "nmos", "NL", 48, -6, S["W34"], S["L34"])
    s.dev("mb", "pmos", "PL", 80, 10, S["WB"], S["LB"], label="MB")
    s.dev("r1", "res", "RV", 122, 16, R=f"{S['R1'] / 1e3:g}k")
    s.dev("r2", "res", "RV", 122, -20, R=f"{S['R2'] / 1e3:g}k")
    xb = P("mbias", "s")[0]
    x5 = P("m5", "s")[0]
    xbs = P("mbs", "s")[0]
    xp = P("mp", "s")[0]
    x1 = P("m1", "d")[0]
    x2 = P("m2", "d")[0]
    # supply rails (named by the exports) ------------------------------------
    s.wire((xb - 14, VIN), (xb, VIN), (x5, VIN), (xbs, VIN), (xp, VIN))
    for d in ("mbias", "m5", "mbs", "mp"):
        s.wire((d, "s"), (P(d, "s")[0], VIN))
        s.wire((d, "b"), (d, "s"))                      # bulk = source = vin
    s.wire((x1 - 12, GND), (x1, GND), (x2, GND), (xbs, GND), (xp, GND))
    for d in ("m3", "m4"):
        s.wire((d, "s"), (P(d, "s")[0], GND))
        s.wire((d, "b"), (d, "s"))                      # bulk = source = gnd
    s.wire(("mb", "d"), (xbs, GND))
    s.wire(("r2", "a"), (xp, GND))
    # bias: pb ---------------------------------------------------------------
    xj = 10
    s.wire(("mbias", "g"), (xj, 46), ("m5", "g"), name="pb", seg=1)
    s.wire(("mbias", "d"), (xb, 36), (xj, 36), (xj, 46))     # diode connection
    s.wire((xb, 36), (xb, 28))                                # ibias pin
    s.wire((xj, 46), (xj, 60), (70, 60), (70, 46), ("mbs", "g"))
    # error amplifier ----------------------------------------------------------
    s.wire(("m5", "d"), (x5, 34), (x2, 34), name="tail", seg=1)
    s.wire(("m1", "s"), (x1, 34))
    s.wire(("m2", "s"), (x2, 34))
    s.wire(("m1", "b"), ("m1", "s"))                    # input-pair bulk = tail
    s.wire(("m2", "b"), ("m2", "s"))
    xg = 38
    s.wire(("m1", "d"), (x1, 8), ("m3", "d"), name="d1", seg=0)
    s.wire((x1, 8), (xg, 8), (xg, -6))
    s.wire(("m3", "g"), (xg, -6), ("m4", "g"))
    s.wire(("m2", "d"), (x2, 10), ("m4", "d"))
    s.wire((x2, 10), ("mb", "g"), name="ea")
    # buffer and pass device -----------------------------------------------------
    s.wire(("mbs", "d"), (xbs, 30), ("mb", "s"))
    s.wire(("mb", "b"), ("mb", "s"))                    # follower bulk = its source
    s.wire((xbs, 30), (110, 30), (110, 46), ("mp", "g"), name="g", seg=0)
    # output and divider -----------------------------------------------------------
    s.wire(("mp", "d"), (xp, 30), ("r1", "b"))
    s.wire((xp, 30), (xp + 14, 30))
    s.wire(("r1", "a"), (xp, -2), ("r2", "b"))
    s.wire((xp, -2), (xp + 10, -2), name="fb")          # net label at the divider
    s.wire(("m1", "g"), (P("m1", "g")[0] - 9, P("m1", "g")[1]), name="fb")   # same net at the OTA input
    s.wire(("m2", "g"), (P("m2", "g")[0] + 11, P("m2", "g")[1]))
    # exports ------------------------------------------------------------------------
    s.export("vin", (xb - 14, VIN), "pwr")
    s.export("gnd", (x1 - 12, GND), "gnd")
    s.export("vout", (xp + 14, 30), "out")
    s.export("vref", (P("m2", "g")[0] + 11, P("m2", "g")[1]), "in")
    s.export("ibias", (xb, 28), "bidir")
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
