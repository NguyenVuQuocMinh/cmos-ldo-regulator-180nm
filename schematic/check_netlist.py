"""Check that the Electric schematic is the circuit that was simulated.

1. Netlist comparison: every device of Electric's netlist (ldo180_electric.spi,
   written by Electric from ldo180{sch}) against the Python netlist used for all
   results (scripts/ldo_netlist.py with sizes_v3.json): terminals, model, W, L,
   M, R. Drain and source may be swapped (symmetric devices).
2. Re-simulation with Electric's netlist: operating points, load and line
   regulation, PSRR, load step and loop gain, compared with the published v3
   numbers (scripts/sim_results_v3.json).

Test-bench conventions (both flows):
  * Electric writes sizes in schematic units (um) with ".opt scale=0.2U"
    (lambda of its default layout technology); that line is replaced by
    ".option scale=1e-6".
  * AD/AS/PD/PS are layout data, not part of a schematic. They are added with
    the same rule as ldo_netlist.mos(): 0.5 um of diffusion on each side,
    AD = AS = 0.5 W, PD = PS = 2 W + 1 (um, before scaling).
  * Loop gain: the fb wire at the gate of M1 is opened (renamed fbi) and the
    same L-C break as in the Python flow is inserted.
Writes schematic/check_netlist.json.
"""
import json
import os
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / "scripts"))
os.environ["LDO_SIZES"] = "sizes_v3.json"
from spice import run, read           # noqa: E402
import ldo_netlist                    # noqa: E402

SPI = ROOT / "ldo180_electric.spi"
REF = json.loads((ROOT.parent / "scripts" / "sim_results_v3.json").read_text())
NODEMAP = {"0": "gnd", "pb": "ibias", "fbi": "fb"}     # Python node -> Electric net


def val(x):
    x = x.strip().lower()
    mult = {"t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3, "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
    m = re.fullmatch(r"([-+0-9.e]+)(meg|[tgkmunpf])?", x)
    return float(m.group(1)) * (mult[m.group(2)] if m.group(2) else 1.0)


def parse(lines, scale, strip=True):
    """device dict name -> (kind, nodes, params) from SPICE lines; Electric adds
    the element letter in front of the node name (Mm1, Rr1), so strip it there"""
    devs = {}
    for ln in lines:
        t = ln.split()
        if not t or t[0][0].lower() not in "mr":
            continue
        name = (t[0][1:] if strip else t[0]).lower()
        if t[0][0].lower() == "m":
            d, g, s, b, model = t[1:6]
            p = {k.lower(): val(v) for k, v in (kv.split("=") for kv in t[6:])}
            p.setdefault("m", 1.0)
            devs[name] = ("m", (d, g, s, b), model.upper(),
                          dict(w=p["w"] * scale, l=p["l"] * scale, m=p["m"]))
        else:
            devs[name] = ("r", (t[1], t[2]), None, dict(r=val(t[3])))
    return devs


def compare():
    el_lines = SPI.read_text().splitlines()
    sub = el_lines[next(i for i, l in enumerate(el_lines) if l.upper().startswith(".SUBCKT")):]
    E = parse(sub, 1e-6)                                   # Electric sizes are in um
    ref_lines = [l for l in ldo_netlist.core().splitlines()
                 if l and l[0].lower() in "mr" and not l.lower().startswith("rshort")
                 and not l.lower().startswith("resr")]
    R = parse(ref_lines, 1.0, strip=False)
    R = {k: (kind, tuple(NODEMAP.get(n, n) for n in nodes), mdl, p) for k, (kind, nodes, mdl, p) in R.items()}
    rows, ok = [], True
    for name in sorted(set(E) | set(R)):
        if name not in E or name not in R:
            rows.append((name, "missing in " + ("Electric" if name not in E else "Python")))
            ok = False
            continue
        ek, en, em, ep = E[name]
        rk, rn, rm, rp = R[name]
        same_nodes = en == rn or (ek == "m" and (en[2], en[1], en[0], en[3]) == rn) \
            or (ek == "r" and en[::-1] == rn)
        same_par = all(abs(ep[k] - rp[k]) <= 1e-9 * max(1.0, abs(rp[k])) for k in rp)
        same = same_nodes and same_par and em == rm
        ok &= same
        rows.append((name, "match" if same else f"DIFF electric={en} {em} {ep} python={rn} {rm} {rp}"))
    return ok, rows


def electric_core(loop_break=False, esr=0.01, cl=2.2e-6):
    """test bench around Electric's subcircuit (same external parts as ldo_netlist.core)"""
    txt = SPI.read_text().replace(".opt scale=0.2U", ".option scale=1e-6")
    out = []
    for ln in txt.splitlines():
        t = ln.split()
        if t and t[0][0] == "M":
            w = val([kv for kv in t[6:] if kv.upper().startswith("W=")][0][2:])
            ln += f" AD={0.5 * w:g} AS={0.5 * w:g} PD={2 * w + 1:g} PS={2 * w + 1:g}"
            if loop_break and t[0] == "Mm1":
                ln = ln.replace(" fb ", " fbi ", 1)
        if loop_break and ln.upper().startswith(".SUBCKT"):
            ln += " fbi fb"
        if ln.strip().upper() == ".END":
            continue
        out.append(ln)
    S = ldo_netlist.S
    pins = "gnd ibias vin vout vref" + (" fbi fb" if loop_break else "")
    tb = ["\n".join(out), ".include cmos180.lib",
          f"x1 0 pb vin vout vref {'fbi fb' if loop_break else ''} ldo180",
          f"iref pb 0 {S['IREF']}", f"vref vref 0 {S['VREF']}",
          f"cl vout nesr {cl}", f"resr nesr 0 {esr}"]
    if loop_break:
        tb += ["lbrk fb fbi 1e9", "cbrk fbi vt 1e3", "vt vt 0 dc 0 ac 1"]
    return "\n".join(tb)


def simulate():
    import numpy as np
    res = {}
    # load regulation
    net = f"""* electric netlist: load regulation
{electric_core()}
vin vin 0 1.8
il vout 0 0.1m
.control
dc il 0.1m 50m 0.1m
wrdata el_loadreg.txt v(vout)
.endc
.end
"""
    run(net, "el_loadreg")
    d = read("el_loadreg.txt", 1)
    res["loadreg"] = dict(v_light=float(d[0, 1]), v_heavy=float(d[-1, 1]), dV=float(d[0, 1] - d[-1, 1]))
    # line regulation at 50 mA
    net = f"""* electric netlist: line
{electric_core()}
vin vin 0 1.8
il vout 0 50m
.control
dc vin 1.4 2.0 0.002
wrdata el_line.txt v(vout)
.endc
.end
"""
    run(net, "el_line")
    d = read("el_line.txt", 1)
    vin, vo = d[:, 0], d[:, 1]
    res["line_50mA_slope"] = float((np.interp(1.9, vin, vo) - np.interp(1.7, vin, vo)) / 0.2)
    # PSRR at 1 kHz
    res["psrr_1kHz"] = {}
    for il in (0.1e-3, 50e-3):
        tag = f"el_psrr_{il*1e3:g}"
        net = f"""* electric netlist: psrr
{electric_core()}
vin vin 0 dc 1.8 ac 1
il vout 0 {il}
.control
ac dec 50 1 1e8
let p = -db(v(vout))
wrdata {tag}.txt p
.endc
.end
"""
        run(net, tag)
        d = read(f"{tag}.txt", 1)
        res["psrr_1kHz"][f"{il*1e3:g}mA"] = float(np.interp(3, np.log10(d[:, 0]), d[:, 1]))
    # load step
    net = f"""* electric netlist: load step
{electric_core()}
vin vin 0 1.8
il vout 0 pwl(0 0.1m 20u 0.1m 21u 50m 120u 50m 121u 0.1m 300u 0.1m)
.control
tran 5n 300u 0 20n
wrdata el_tran.txt v(vout)
.endc
.end
"""
    run(net, "el_tran")
    d = read("el_tran.txt", 1)
    t, vo = d[:, 0], d[:, 1]
    v0 = float(np.interp(19e-6, t, vo))
    res["tran_dip"] = float(v0 - vo[(t > 20e-6) & (t < 120e-6)].min())
    # loop gain
    res["loop"] = {}
    for il in (0.1e-3, 1e-3, 10e-3, 50e-3):
        tag = f"el_lg_{il*1e3:g}"
        net = f"""* electric netlist: loop gain
{electric_core(loop_break=True)}
vin vin 0 1.8
il vout 0 {il}
.control
ac dec 100 1 1e9
let T = -v(fb)/v(fbi)
let tm = db(T)
let tp = 180/pi*cph(T)
wrdata {tag}.txt tm tp
.endc
.end
"""
        run(net, tag)
        d = read(f"{tag}.txt", 2)
        f, mag, ph = d[:, 0], d[:, 1], d[:, 3]
        k = int(np.argmax(mag < 0))
        f0 = float(np.exp(np.interp(0, [mag[k], mag[k - 1]], [np.log(f[k]), np.log(f[k - 1])])))
        ph0 = float(np.interp(np.log(f0), [np.log(f[k - 1]), np.log(f[k])], [ph[k - 1], ph[k]]))
        res["loop"][f"{il*1e3:g}mA"] = dict(T0_dB=float(mag[0]), UGF=f0, PM=180 + ph0)
    return res


def main():
    ok, rows = compare()
    print("netlist comparison:", "ALL MATCH" if ok else "MISMATCH")
    for name, msg in rows:
        print(f"  {name:<6} {msg}")
    res = simulate()
    ref = dict(
        loadreg_dV=REF["loadreg"]["dV"], v_light=REF["loadreg"]["v_light"], v_heavy=REF["loadreg"]["v_heavy"],
        line_50mA_slope=REF["linereg"]["50mA"]["slope"],
        psrr_1kHz_0p1mA=REF["psrr"]["0.1mA"]["1kHz"], psrr_1kHz_50mA=REF["psrr"]["50mA"]["1kHz"],
        tran_dip=REF["tran"]["dip_from_initial"],
        **{f"PM_{k}": v["PM"] for k, v in REF["loop"].items()},
        **{f"T0_{k}": v["T0_dB"] for k, v in REF["loop"].items()})
    got = dict(
        loadreg_dV=res["loadreg"]["dV"], v_light=res["loadreg"]["v_light"], v_heavy=res["loadreg"]["v_heavy"],
        line_50mA_slope=res["line_50mA_slope"],
        psrr_1kHz_0p1mA=res["psrr_1kHz"]["0.1mA"], psrr_1kHz_50mA=res["psrr_1kHz"]["50mA"],
        tran_dip=res["tran_dip"],
        **{f"PM_{k}": v["PM"] for k, v in res["loop"].items()},
        **{f"T0_{k}": v["T0_dB"] for k, v in res["loop"].items()})
    print(f"\n{'quantity':<18}{'published v3':>16}{'Electric netlist':>18}{'difference':>14}")
    for k in ref:
        print(f"{k:<18}{ref[k]:>16.6g}{got[k]:>18.6g}{got[k] - ref[k]:>14.3g}")
    (ROOT / "check_netlist.json").write_text(json.dumps(
        dict(netlist_match=ok, rows=rows, published=ref, electric=got), indent=1))


if __name__ == "__main__":
    main()
