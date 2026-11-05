"""Robustness checks of the final design (v2): phase margin, DC gain and VOUT
at VIN = 1.7 / 1.8 / 1.9 V and T = 0 / 27 / 85 C, for IL = 0.1 mA and 50 mA.
(Typical-model only: the model file has no process corners.)"""
import json
import pathlib
import numpy as np
from spice import run, read
from ldo_netlist import core

ROOT = pathlib.Path(__file__).resolve().parent.parent
import os
import ldo_netlist
VER = os.environ.get("LDO_VER", "v3")


def check(vin, temp, il):
    tag = f"rob_{vin}_{temp}_{il*1e3:g}"
    net = f"""* robustness {tag}
{core(loop_break=True)}
vin vin 0 {vin}
il vout 0 {il}
.temp {temp}
.control
op
print v(vout)
ac dec 100 1 1e9
let T = -v(fb)/v(fbi)
let tm = db(T)
let tp = 180/pi*cph(T)
wrdata {tag}.txt tm tp
.endc
.end
"""
    log = run(net, tag)
    vout = float([l for l in log.splitlines() if l.strip().startswith("v(vout)")][0].split("=")[1])
    d = read(f"{tag}.txt", 2)
    f, mag, ph = d[:, 0], d[:, 1], d[:, 3]
    k = np.argmax(mag < 0)
    f0 = np.exp(np.interp(0, [mag[k], mag[k - 1]], [np.log(f[k]), np.log(f[k - 1])]))
    ph0 = np.interp(np.log(f0), [np.log(f[k - 1]), np.log(f[k])], [ph[k - 1], ph[k]])
    return dict(vout=vout, T0_dB=float(mag[0]), UGF=float(f0), PM=float(180 + ph0))


def psrr_1k(vin, temp, il):
    tag = f"pc_{vin}_{temp}_{il*1e3:g}"
    net = f"""* psrr corner {tag}
{core()}
vin vin 0 dc {vin} ac 1
il vout 0 {il}
.temp {temp}
.control
ac dec 20 100 1e4
let p = -db(v(vout))
wrdata {tag}.txt p
.endc
.end
"""
    run(net, tag)
    d = read(f"{tag}.txt", 1)
    return float(np.interp(3, np.log10(d[:, 0]), d[:, 1]))


def main():
    out = []
    for il in (0.1e-3, 50e-3):
        for vin in (1.7, 1.8, 1.9):
            for temp in (0, 27, 85):
                r = check(vin, temp, il)
                r.update(vin=vin, temp=temp, il=il)
                out.append(r)
                print(f"IL={il*1e3:5g} mA VIN={vin} T={temp:3d} C: VOUT={r['vout']:.4f} "
                      f"T0={r['T0_dB']:.1f} dB UGF={r['UGF']/1e3:.0f} kHz PM={r['PM']:.1f}")
    # PSRR at 1 kHz over VIN x T x IL (ESR nominal)
    ps = []
    for il in (0.1e-3, 50e-3):
        for vin in (1.7, 1.8, 1.9):
            for temp in (0, 27, 85):
                ps.append(dict(vin=vin, temp=temp, il=il, psrr=psrr_1k(vin, temp, il)))
                print(f"PSRR 1 kHz IL={il*1e3:5g} mA VIN={vin} T={temp:3d} C: {ps[-1]['psrr']:.1f} dB")
    # phase margin with ESR = 0 at 50 mA over VIN x T
    esr0 = []
    keep = ldo_netlist.S["ESR"]
    ldo_netlist.S["ESR"] = 1e-6
    for vin in (1.7, 1.8, 1.9):
        for temp in (0, 27, 85):
            r = check(vin, temp, 50e-3)
            esr0.append(dict(vin=vin, temp=temp, PM=r["PM"], UGF=r["UGF"]))
            print(f"ESR=0, 50 mA, VIN={vin} T={temp:3d} C: PM={r['PM']:.1f}")
    ldo_netlist.S["ESR"] = keep
    (ROOT / "scripts" / f"sim_extra_{VER}.json").write_text(
        json.dumps(dict(loop=out, psrr=ps, esr0=esr0), indent=1))


if __name__ == "__main__":
    main()
