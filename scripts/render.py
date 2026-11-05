"""Fill doc/ldo_theory_proofs.tex.in (Part 1) and doc/ldo_hand_design.tex.in
(Part 2) with numbers from the JSON results and build both PDFs.

Placeholders in the template:  <<python-expression|format>>  (format optional).
Every number in the note therefore comes from params.json, hand.json,
sim_*.json; nothing is typed by hand.
Usage:  python render.py [path\\to\\tectonic.exe]
"""
import json
import math
import pathlib
import re
import shutil
import subprocess
import sys
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
SC = ROOT / "scripts"
DOC = ROOT / "doc"


def J(name):
    return json.loads((SC / name).read_text())


P = J("params.json")
HJ = J("hand.json")
SP, H = HJ["spec"], HJ["common"]
V1, V2, V3 = HJ["v1"], HJ["v2"], HJ["v3"]
S1, S2, S3 = (J(f"sim_results_v{i}.json") for i in (1, 2, 3))
O1, O2, O3 = (J(f"sim_op_v{i}.json") for i in (1, 2, 3))
X2, X3 = J("sim_extra_v2.json"), J("sim_extra_v3.json")
Z1, Z2, Z3 = (J(f"sizes_v{i}.json") for i in (1, 2, 3))


def op(O, case, dev, par):
    return O[case][f"@{dev}[{par}]"]


def derived(O, Hv, Z):
    """Small-signal numbers read from a simulated operating point."""
    d = {}
    for case in ("light", "heavy"):
        gm1 = op(O, case, "m1", "gm")
        a_ea = gm1 / (op(O, case, "m2", "gds") + op(O, case, "m4", "gds"))
        gmb = op(O, case, "mb", "gm")
        a_b = gmb / (gmb + op(O, case, "mb", "gds") + op(O, case, "mbs", "gds"))
        G = H["beta"] * a_ea * a_b
        gmp = op(O, case, "mp", "gm")
        gdsp = op(O, case, "mp", "gds")
        vin = 1.8
        vsgp = abs(op(O, case, "mp", "vgs"))  # ngspice prints PMOS VGS as a magnitude
        vsgb = abs(op(O, case, "mb", "vgs"))
        vgs3 = op(O, case, "m3", "vgs")
        eps = vin - vsgp - vsgb - vgs3
        vout_pred = SP["VREF"] / H["beta"] + eps / (H["beta"] * a_ea)
        d[case] = dict(gm1=gm1, gm_over_id1=gm1 / op(O, case, "m1", "id"),
                       lam2=op(O, case, "m2", "gds") / abs(op(O, case, "m2", "id")),
                       lam4=op(O, case, "m4", "gds") / op(O, case, "m4", "id"),
                       A_ea=a_ea, A_ea_dB=20 * math.log10(a_ea), A_b=a_b, G=G,
                       G_dB=20 * math.log10(G), gmp=gmp, gdsp=gdsp,
                       vsgp=vsgp, vsgb=vsgb, vgs3=vgs3, eps=eps,
                       vout_pred=vout_pred, vout_sim=O[case]["v(vout)"],
                       vea=O[case]["v(ea)"], vg=O[case]["v(g)"],
                       fu_pred=G * gmp / (2 * math.pi * SP["CL"]))
    # dropout corner: PSR factor (1 + gds/gm) of the pass device
    gm_do, gds_do = op(O, "dropout", "mp", "gm"), op(O, "dropout", "mp", "gds")
    d["dropout"] = dict(gmp=gm_do, gdsp=gds_do, ratio=gds_do / gm_do)
    d["heavy"]["ratio"] = d["heavy"]["gdsp"] / d["heavy"]["gmp"]
    return d


D1, D2, D3 = derived(O1, V1, Z1), derived(O2, V2, Z2), derived(O3, V3, Z3)


def corner_stats(X):
    ps = X["psrr"]
    nom = [p for p in ps if p["vin"] >= 1.8 - 1e-9]
    low = [p for p in ps if p["vin"] < 1.8 - 1e-9]
    worst_nom = min(nom, key=lambda p: p["psrr"])
    worst_low = min(low, key=lambda p: p["psrr"])
    pm_all = [r["PM"] for r in X["loop"]]
    pm_esr0 = [r["PM"] for r in X["esr0"]]
    worst_esr0 = min(X["esr0"], key=lambda r: r["PM"])
    vouts = [r["vout"] for r in X["loop"]]
    return dict(psrr_nom_min=worst_nom["psrr"], psrr_nom_min_at=worst_nom,
                psrr_low_min=worst_low["psrr"], psrr_low_min_at=worst_low,
                pm_min=min(pm_all), pm_esr0_min=min(pm_esr0), pm_esr0_at=worst_esr0,
                vout_min=min(vouts), vout_max=max(vouts))


C2, C3 = corner_stats(X2), corner_stats(X3)


def tau_fit():
    """Recovery time constant after the load release (v3 run is the last one)."""
    d = np.loadtxt(ROOT / "sim" / "tran.txt")
    t, v = d[:, 0], d[:, 1]
    v_end = v[-1]
    m = (t > 135e-6) & (t < 230e-6)
    y = np.abs(v_end - v[m])
    k = y > 1e-6
    slope = np.polyfit(t[m][k], np.log(y[k]), 1)[0]
    return -1 / slope


TAU = tau_fit()
FU_LIGHT = S3["loop"]["0.1mA"]["UGF"]

CTX = dict(math=math, np=np, P=P, SP=SP, H=H, V1=V1, V2=V2, V3=V3,
           S1=S1, S2=S2, S3=S3, O1=O1, O2=O2, O3=O3, X2=X2, X3=X3,
           D1=D1, D2=D2, D3=D3, C2=C2, C3=C3, Z1=Z1, Z2=Z2, Z3=Z3,
           TAU=TAU, FU_LIGHT=FU_LIGHT,
           db=lambda x: 20 * math.log10(x), pi=math.pi)

PAT = re.compile(r"<<(.+?)>>", re.S)


def sub(m):
    body = m.group(1)
    if "|" in body:
        expr, fmt = body.rsplit("|", 1)
    else:
        expr, fmt = body, ""
    val = eval(expr, {}, CTX)
    s = format(val, fmt)
    return s.replace("-", "$-$") if (isinstance(val, (int, float)) and s.startswith("-")) else s


NOTES = ["ldo_theory_proofs", "ldo_hand_design"]   # Part 2 reads Part 1's .aux (xr)


def main():
    for name in NOTES:
        src = (DOC / f"{name}.tex.in").read_text(encoding="utf-8")
        (DOC / f"{name}.tex").write_text(PAT.sub(sub, src), encoding="utf-8")
    # figures next to the documents
    fd = DOC / "figures"
    fd.mkdir(exist_ok=True)
    for f in (ROOT / "figures").glob("*.png"):
        shutil.copy(f, fd / f.name)
    if len(sys.argv) > 1:
        for name in NOTES:
            # -k keeps the .aux file that the cross-references of Part 2 need
            res = subprocess.run([sys.argv[1], "-k", f"{name}.tex"], cwd=DOC,
                                 capture_output=True, text=True)
            log = res.stdout + res.stderr
            bad = [l for l in log.splitlines() if l.startswith("!") or "error:" in l
                   or ("undefined" in l and "Rerun" not in l)]
            print(f"[{name}] rc={res.returncode}", *bad[-12:], sep="\n  ")


if __name__ == "__main__":
    main()
