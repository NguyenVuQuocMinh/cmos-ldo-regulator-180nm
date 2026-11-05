"""Extract square-law parameters (VTH, KP' = mu*Cox, lambda) from cmos180.lib.

Method (written up in the theory note, Sec. 2):
  * ID-VGS in saturation (|VDS| = 0.9 V), W = 10 um.  sqrt(ID) is linear in VGS
    for a square-law device; fit sqrt(ID) over |VOV| ~ 0.1-0.3 V -> slope and
    intercept give KP' and VTH.
  * ID-VDS at |VOV| = 0.2 V: lambda = (dID/dVDS) / ID taken at |VDS| = 0.6-1.2 V.
Results go to figures/ and to params.json for the hand calculation.
"""
import json
import pathlib
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from spice import run, read, SIM

ROOT = pathlib.Path(__file__).resolve().parent.parent
W = 10e-6
LS = [0.18e-6, 0.5e-6, 1.0e-6, 2.0e-6, 3.0e-6]


def idvg(kind, L):
    if kind == "n":
        net = f"""* nmos id-vg
.include cmos180.lib
vd d 0 0.9
vg g 0 0
m1 d g 0 0 NMOS W={W} L={L} AD={W*0.5e-6} AS={W*0.5e-6} PD={2*W+1e-6} PS={2*W+1e-6}
.control
dc vg 0 1.8 0.005
wrdata idvg_n.txt -i(vd)
.endc
.end
"""
    else:
        net = f"""* pmos id-vg (source = bulk = 1.8 V)
.include cmos180.lib
vs s 0 1.8
vd d 0 0.9
vg g 0 1.8
m1 d g s s PMOS W={W} L={L} AD={W*0.5e-6} AS={W*0.5e-6} PD={2*W+1e-6} PS={2*W+1e-6}
.control
dc vg 1.8 0 -0.005
wrdata idvg_p.txt i(vd)
.endc
.end
"""
    run(net, f"idvg_{kind}")
    d = read(f"idvg_{kind}.txt", 1)
    vg = d[:, 0]
    i = np.abs(d[:, 1])
    vgs = vg if kind == "n" else 1.8 - vg
    return vgs, i


def idvd(kind, L, vgs):
    if kind == "n":
        net = f"""* nmos id-vd
.include cmos180.lib
vd d 0 0
vg g 0 {vgs}
m1 d g 0 0 NMOS W={W} L={L} AD={W*0.5e-6} AS={W*0.5e-6} PD={2*W+1e-6} PS={2*W+1e-6}
.control
dc vd 0 1.8 0.005
wrdata idvd_n.txt -i(vd)
.endc
.end
"""
    else:
        net = f"""* pmos id-vd
.include cmos180.lib
vs s 0 1.8
vd d 0 1.8
vg g 0 {1.8 - vgs}
m1 d g s s PMOS W={W} L={L} AD={W*0.5e-6} AS={W*0.5e-6} PD={2*W+1e-6} PS={2*W+1e-6}
.control
dc vd 1.8 0 -0.005
wrdata idvd_p.txt i(vd)
.endc
.end
"""
    run(net, f"idvd_{kind}")
    d = read(f"idvd_{kind}.txt", 1)
    vds = d[:, 0] if kind == "n" else 1.8 - d[:, 0]
    return vds, np.abs(d[:, 1])


def fit_square_law(vgs, i, L):
    """Fit sqrt(ID) = sqrt(KP W / 2L) (VGS - VTH) on the strong-inversion range.

    First pass: rough VTH from the max-gm extrapolation; then fit on
    VOV in [0.1, 0.3] V.
    """
    s = np.sqrt(i)
    ds = np.gradient(s, vgs)
    k = np.argmax(ds)
    vth0 = vgs[k] - s[k] / ds[k]
    for _ in range(3):
        m = (vgs > vth0 + 0.10) & (vgs < vth0 + 0.30)
        a, b = np.polyfit(vgs[m], s[m], 1)
        vth0 = -b / a
    kp = 2 * L / W * a ** 2
    return vth0, kp


def main():
    out = {}
    fig, ax = plt.subplots(1, 2, figsize=(9, 3.4))
    for kind in ("n", "p"):
        for L in LS:
            vgs, i = idvg(kind, L)
            vth, kp = fit_square_law(vgs, i, L)
            vds, idd = idvd(kind, L, vth + 0.2)
            m = (vds > 0.6) & (vds < 1.2)
            slope = np.polyfit(vds[m], idd[m], 1)[0]
            i_mid = np.interp(0.9, vds, idd)
            lam = slope / i_mid
            # gm/ID at a few inversion levels (W = 10 um) for reference
            gm = np.gradient(i, vgs)
            key = f"{kind}_L{L*1e6:.2f}"
            out[key] = dict(VTH=round(float(vth), 4), KP=float(kp),
                            lam=float(lam), L=L)
            print(f"{key}: VTH={vth:.3f} V  KP'={kp*1e6:.1f} uA/V^2  "
                  f"lambda={lam:.3f} 1/V  (ID at VOV=0.2: {i_mid*1e6:.1f} uA)")
            if L in (0.18e-6, 1.0e-6):
                idx = 0 if kind == "n" else 1
                ax[idx].plot(i / W, gm / np.maximum(i, 1e-15),
                             label=f"L = {L*1e6:.2f} um")
    for idx, t in enumerate(("NMOS", "PMOS")):
        ax[idx].set_xscale("log")
        ax[idx].set_xlim(1e-3, 1e2)
        ax[idx].set_ylim(0, 30)
        ax[idx].set_xlabel("I_D / W  (A/m)")
        ax[idx].set_ylabel("g_m / I_D  (1/V)")
        ax[idx].set_title(t + ", |V_DS| = 0.9 V")
        ax[idx].grid(alpha=0.3)
        ax[idx].legend()
    fig.tight_layout()
    fig.savefig(ROOT / "figures" / "gm_over_id.png", dpi=200)
    (ROOT / "scripts" / "params.json").write_text(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
