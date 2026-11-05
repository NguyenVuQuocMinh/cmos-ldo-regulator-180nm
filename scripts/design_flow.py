"""Hand design of the LDO following the system-level LDO design procedure of
G. A. Rincon-Mora:
  [T] G. A. Rincon-Mora, "Current Efficient, Low Voltage, Low Drop-out
      Regulators", Ph.D. dissertation, Georgia Institute of Technology, 1996,
      Chapter II (System design considerations), Sec. 6.1.
  [J] G. A. Rincon-Mora and P. E. Allen, "A Low-Voltage, Low Quiescent
      Current, Low Drop-Out Regulator", IEEE JSSC 33(1), pp. 36-44, 1998.
Formulas are used in the form proved in Part 1 (ldo_theory_proofs).

Steps
  1  topology                      [T 6.1, Table 6.1; T Fig. 2.7; J Sec. IV]
  2  feedback network              [T 2.1]
  3  pass device: dropout and saturation        [J (12)-(14); T 2.3]
  4  open-loop gain from regulation and PSRR    [T (2.9)]
  5  transient budget -> response time          [T (2.10)-(2.12)]
  6  gain stage: CMR around VREF, output swing, gain, pole   [T 2.4; J Sec. IV]
  7  buffer: pole P3 above the UGF, slew current             [J (3); T 2.4, (2.12)]
  8  quiescent current and current efficiency                [J (1)]
Steps 6-7 are run twice. Pass A uses square-law parameters only. Pass B
replaces gm/ID and lambda by the values read at the simulated operating point
of the previous design (v3), the usual second pass of a hand design.
Writes hand_flow.json and sizes_v4.json.
"""
import json
import math
import pathlib
import numpy as np

ROOT = pathlib.Path(__file__).resolve().parent.parent
SC = ROOT / "scripts"
P = json.loads((SC / "params.json").read_text())
HAND = json.loads((SC / "hand.json").read_text())
SPEC = HAND["spec"]
C = HAND["common"]               # pass-device numbers that do not depend on the flow
OP3 = json.loads((SC / "sim_op_v3.json").read_text())
Z3 = json.loads((SC / "sizes_v3.json").read_text())

PM_TARGET = 60.0                 # deg at full load with ESR -> 0 (spec 45 deg + 15 deg for corners)
GAIN_MARGIN = 2.0                # hand G must exceed the requirement by 6 dB (Pass A, see step 6)
VOV1, VOV4 = 0.10, 0.15          # input-pair and mirror overdrives, as in v1-v3
I_D1 = 20e-6                     # EA current per side (free by Part 1, Prop. pea)
IREF, WBIAS = 5e-6, 5e-6


def rd(x, n=4):
    return float(f"{x:.{n}g}")


def pm_of(fu, pb, pea, z=float("inf")):
    """Part 1, Prop. pm (single dominant pole, two non-dominant poles, ESR zero)."""
    return 90 - math.degrees(math.atan(fu / pb)) - math.degrees(math.atan(fu / pea)) \
        + (math.degrees(math.atan(fu / z)) if z != float("inf") else 0.0)


def main():
    s = SPEC
    F = {}
    p18, p05, p1 = P["p_L0.18"], P["p_L0.50"], P["p_L1.00"]

    # ---- step 2: feedback network [T 2.1]
    I_R = 10e-6
    beta = s["VREF"] / s["VOUT"]
    R2, R1 = s["VREF"] / I_R, (s["VOUT"] - s["VREF"]) / I_R
    F["s2"] = dict(I_R=I_R, beta=beta, R1=R1, R2=R2)

    # ---- step 3: pass device [J (12)-(14), Part 1 Prop. pass]
    # (a) dropout: the gate can be pulled down to V_G,min = V_OV4 + V_SG,B
    vsgb_est = P["p_L0.50"]["VTH"] + 0.22                 # buffer VSG estimate, checked in step 7
    vg_min = VOV4 + vsgb_est
    vsg_avail = s["VIN_MIN"] - vg_min
    vov_avail = vsg_avail - p18["VTH"]
    wl_do = s["IL_MAX"] / (p18["KP"] * s["VDO"] * (vov_avail - s["VDO"] / 2))
    # (b) saturation at VIN_NOM (needed for the loop gain and the PSRR, Part 1 Cor. dropout_psrr)
    wl_sat = 2 * s["IL_MAX"] / (p18["KP"] * (s["VIN_NOM"] - s["VOUT"] - 0.01) ** 2)
    wl_need = max(wl_do, wl_sat)
    Wf, LP = 10e-6, 0.18e-6
    MP = math.ceil(wl_need * LP / Wf / 10) * 10
    WL = MP * Wf / LP
    vov_do = s["IL_MAX"] / (p18["KP"] * WL * s["VDO"]) + s["VDO"] / 2
    ron = 1 / (p18["KP"] * WL * vov_avail)                # J (13) with the available drive
    F["s3"] = dict(vg_min=vg_min, vsg_avail=vsg_avail, vov_avail=vov_avail, wl_do=wl_do,
                   wl_sat=wl_sat, binding="saturation" if wl_sat >= wl_do else "dropout",
                   MP=MP, WL=WL, W=MP * Wf, vov_do=vov_do, vsg_do=p18["VTH"] + vov_do,
                   ron=ron, vdo_at_avail=ron * s["IL_MAX"], Cpar=C["Cg"],
                   gm_p_max=C["gm_p_max"], vsg_max=C["vsg_max_load"],
                   vsg_min=C["vsg_min_load"], dVSG=C["dVSG"], gm_p_min=C["gm_p_min"])
    assert MP == C["MP"], "pass device differs from the earlier design"

    # ---- step 4: required open-loop gain [T (2.9), Part 1 Cor. static, Prop. psrr]
    G_req = dict(psrr=10 ** (s["PSRR_MIN_DB"] / 20), load=C["dVSG"] / s["LOADREG_MAX"],
                 line=1 / s["LINEREG_MAX"])
    G_min = max(G_req.values())
    F["s4"] = dict(G_req=G_req, G_min=G_min, binding=max(G_req, key=G_req.get))

    # ---- step 5: transient budget [T (2.10)-(2.12), Part 1 Prop. budget]
    dI = s["IL_MAX"] - s["IL_MIN"]
    dv_esr = dI * s["ESR"]
    dt1_max = s["CL"] * (s["TRAN_MAX"] - dv_esr) / dI
    F["s5"] = dict(dI=dI, dv_esr=dv_esr, dt1_max=dt1_max)

    # ---- steps 6-7, two passes
    def stage(passname, gmid1, lam2, lam4, gmid_b, gm_p):
        R = {}
        # 6a common-mode range of the PMOS pair around VREF (Allen-type limits)
        vth1 = p1["VTH"]
        vsg1 = vth1 + VOV1
        vic_max = s["VIN_MIN"] - 0.15 - vsg1               # tail M5 at VSD,sat = 0.15 V
        vic_min = (P["n_L3.00"]["VTH"] + VOV4) - vth1      # VGS3 - |VTH1|
        R.update(vic_min=vic_min, vic_max=vic_max, cmr_ok=vic_min < s["VREF"] < vic_max)
        # 6b output swing needed by the buffer = window of Part 1 Prop. window
        R.update(vsgb_lo=C["vsgb_lo"], vsgb_hi=C["vsgb_hi"], vsgb=round(C["vsgb_mid"], 2))
        vov_b = R["vsgb"] - p05["VTH"]
        # 6c gain: A_ea = (gm/ID)_1 / (lambda_2 + lambda_4)   (Part 1 Lemma ota)
        A_ea = gmid1 / (lam2 + lam4)
        # buffer gain with the bulk tied to the source (Part 1 Lemma sf)
        lam_b, lam_bs = p05["lam"], p1["lam"]
        A_b = gmid_b / (gmid_b + lam_b + lam_bs)
        G = beta * A_ea * A_b
        # 6d EA pole: C_EA from the v3 sizing (Part 1 Prop. pea: independent of I_D1)
        C_ea = HAND["v3"]["C_ea"]
        p_ea = (lam2 + lam4) * I_D1 / (2 * math.pi * C_ea)
        fu = G * gm_p / (2 * math.pi * s["CL"])           # Part 1 Prop. fu
        R.update(gmid1=gmid1, lam2=lam2, lam4=lam4, A_ea=A_ea, A_b=A_b, G=G,
                 G_margin=G / G_min, C_ea=C_ea, p_ea=p_ea, fu=fu, vov_b=vov_b, gmid_b=gmid_b,
                 phi_ea=math.degrees(math.atan(fu / p_ea)),
                 loadreg=C["dVSG"] / G, linereg=1 / G, psrr_dc_dB=20 * math.log10(G))
        # 7a buffer pole P3 = p_B so that PM >= PM_TARGET at full load, ESR -> 0
        room = 90 - PM_TARGET - math.degrees(math.atan(fu / p_ea))
        R["room_deg"] = room
        if room <= 0:
            R.update(feasible=False)
            return R
        pb_min = fu / math.tan(math.radians(room))
        gout_min = 2 * math.pi * C["Cg"] * pb_min           # Part 1 Lemma sf: p_B = g_out/(2 pi C_G)
        gmb_min = gout_min * A_b                           # g_out = g_mB / A_b
        I_pole = gmb_min / gmid_b
        # 7b slew current: gate must move by dVSG within the budget left by the loop
        tau = 1 / (2 * math.pi * fu)
        t_sr_max = dt1_max - tau
        I_slew = C["Cg"] * C["dVSG"] / t_sr_max
        I_B = 5e-6 * math.ceil(max(I_pole, I_slew) / 5e-6)   # whole multiples of IREF
        gmb = gmid_b * I_B
        p_b = gmb / A_b / (2 * math.pi * C["Cg"])
        t_sr = C["Cg"] * C["dVSG"] / I_B
        R.update(feasible=True, pb_min=pb_min, gmb_min=gmb_min, I_pole=I_pole, tau=tau,
                 t_sr_max=t_sr_max, I_slew=I_slew, I_B=I_B, gmb=gmb, p_b=p_b, t_sr=t_sr,
                 PM_esr0=pm_of(fu, p_b, p_ea),
                 PM_esr=pm_of(fu, p_b, p_ea, 1 / (2 * math.pi * s["ESR"] * s["CL"])),
                 # transient estimates: [T (2.10)-(2.12)] with 1/BW, and Part 1 with tau
                 dv_tr_thesis=dI * (1 / fu + t_sr) / s["CL"] + dv_esr,
                 dv_tr_tau=dI * (tau + t_sr) / s["CL"] + dv_esr)
        return R

    # 6c' channel lengths of the gain stage (Pass A, square law). By Part 1 Prop. pea,
    # A_ea * p_EA is fixed for a given L12 and falls as L12 grows, so take the shortest
    # L12 and then the shortest L34 whose gain meets G_min with the 6 dB margin.
    A_b_A = (2 / 0.22) / (2 / 0.22 + p05["lam"] + p1["lam"])
    cands = []
    for L12 in (1, 2, 3):
        for L34 in (1, 2, 3):
            lam_p, lam_n = P[f"p_L{L12:.2f}"]["lam"], P[f"n_L{L34:.2f}"]["lam"]
            A = (2 / VOV1) / (lam_p + lam_n)
            G = beta * A * A_b_A
            cands.append(dict(L12=L12, L34=L34, A_ea=A, G=G, margin=G / G_min,
                              ok=G >= GAIN_MARGIN * G_min))
    chosen = next(c for c in sorted(cands, key=lambda c: (c["L12"], c["L34"])) if c["ok"])
    F["s6_lengths"] = dict(candidates=cands, chosen=chosen)
    assert (chosen["L12"], chosen["L34"]) == (round(Z3["L12"] * 1e6), round(Z3["L34"] * 1e6))

    # Pass A: square law. gm/ID = 2/VOV; lambda from the L-sweep characterisation.
    pA = stage("A", 2 / VOV1, P["p_L1.00"]["lam"], P["n_L3.00"]["lam"],
               2 / 0.22, C["gm_p_max"])
    # Pass B: small-signal parameters read at the simulated v3 operating point (full load)
    o = OP3["heavy"]
    gmid1 = o["@m1[gm]"] / abs(o["@m1[id]"])
    lam2 = o["@m2[gds]"] / abs(o["@m2[id]"])
    lam4 = o["@m4[gds]"] / abs(o["@m4[id]"])
    gmid_b = o["@mb[gm]"] / abs(o["@mb[id]"])
    gm_p = o["@mp[gm]"]
    pB = stage("B", gmid1, lam2, lam4, gmid_b, gm_p)
    F["passA"], F["passB"] = pA, pB

    # ---- final sizes (v4): v3 with the buffer current of Pass B
    I_B = pB["I_B"]
    vov_b = pB["vov_b"]
    LB = Z3["LB"]
    WB = math.ceil(2 * I_B * LB / (p05["KP"] * vov_b ** 2) * 1e6) * 1e-6
    sizes = dict(Z3)
    sizes.update(WBS=rd(WBIAS * I_B / IREF), WB=rd(WB))
    F["sizes_v4"] = sizes
    # ---- step 8: quiescent current and current efficiency [J (1)]
    Iq = IREF + 2 * I_D1 + I_B + I_R
    F["s8"] = dict(Iq=Iq, Iq_v3=IREF + 2 * I_D1 + 30e-6 + I_R,
                   eff_min=s["IL_MIN"] / (s["IL_MIN"] + Iq), eff_max=s["IL_MAX"] / (s["IL_MAX"] + Iq))
    (SC / "sizes_v4.json").write_text(json.dumps(sizes, indent=2))
    (SC / "hand_flow.json").write_text(json.dumps(F, indent=2, default=float))
    for k in ("s2", "s3", "s4", "s5", "passA", "passB", "s8"):
        print(f"---- {k}")
        for a, b in F[k].items():
            print(f"  {a:14s} {b}")
    print("sizes_v4:", json.dumps(sizes))
    print("changed vs v3:", {k: (Z3[k], sizes[k]) for k in sizes if sizes[k] != Z3[k]})


if __name__ == "__main__":
    main()
