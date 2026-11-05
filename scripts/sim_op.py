"""Operating point at VIN = 1.8 V for IL = 0.1 mA and 50 mA (and dropout corner).

Prints every transistor's ID, VGS, VDS, VDSAT, gm, gds and the node voltages,
and writes sim_op.json.  Saturation check: |VDS| > |VDSAT|.
"""
import json
import pathlib
from spice import run
from ldo_netlist import core

ROOT = pathlib.Path(__file__).resolve().parent.parent
import os
VER = os.environ.get("LDO_VER", "v2")
DEVS = ["mbias", "m5", "m1", "m2", "m3", "m4", "mbs", "mb", "mp"]
NODES = ["vout", "fb", "ea", "g", "tail", "d1", "pb"]
PAR = ["id", "vgs", "vds", "vdsat", "vth", "gm", "gds"]


def op(vin, il, tag):
    prints = []
    for d in DEVS:
        for p in PAR:
            prints.append(f"print @{d}[{p}]")
    for n in NODES:
        prints.append(f"print v({n})")
    prints.append("print i(vin)")
    net = f"""* LDO op point {tag}
{core()}
vin vin 0 {vin}
il vout 0 {il}
.options gmin=1e-15
.control
op
{chr(10).join(prints)}
.endc
.end
"""
    log = run(net, f"op_{tag}_{VER}")
    res = {}
    for line in log.splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            k = k.strip()
            try:
                res[k] = float(v.split()[0])
            except (ValueError, IndexError):
                pass
    return res


def report(res, tag):
    print(f"\n==== {tag} ====")
    for n in NODES:
        print(f"  v({n}) = {res.get(f'v({n})', float('nan')):.4f} V")
    print(f"  I(VIN) = {-res.get('i(vin)', float('nan'))*1e3:.4f} mA")
    print(f"  {'dev':6s} {'ID(uA)':>10s} {'VGS':>7s} {'VDS':>7s} {'VDSAT':>7s} "
          f"{'VTH':>7s} {'gm(mS)':>9s} {'gds(uS)':>9s} sat?")
    for d in DEVS:
        g = lambda p: res.get(f"@{d}[{p}]", float("nan"))
        sat = abs(g("vds")) > abs(g("vdsat"))
        print(f"  {d:6s} {g('id')*1e6:10.3f} {g('vgs'):7.3f} {g('vds'):7.3f} "
              f"{g('vdsat'):7.3f} {g('vth'):7.3f} {g('gm')*1e3:9.4f} "
              f"{g('gds')*1e6:9.3f} {'yes' if sat else 'NO'}")


def main():
    out = {}
    for vin, il, tag in [(1.8, 0.1e-3, "light"), (1.8, 50e-3, "heavy"),
                         (1.7, 50e-3, "dropout"), (1.9, 0.1e-3, "vinmax_light")]:
        r = op(vin, il, tag)
        report(r, tag)
        out[tag] = r
    (ROOT / "scripts" / f"sim_op_{VER}.json").write_text(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
