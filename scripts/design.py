"""Hand design of the LDO from the specification (theory note, Sec. 4).

Every number printed here is the "hand" value quoted in the note.  Device
parameters come from params.json (char_devices.py); the only curve read
directly is the pass-device ID-VSG curve at light load, where the square law
does not apply (weak inversion).
Writes sizes.json (netlist sizes) and hand.json (predicted performance).
"""
import json
import math
import pathlib
import numpy as np
from char_devices import idvg

ROOT = pathlib.Path(__file__).resolve().parent.parent
P = json.loads((ROOT / "scripts" / "params.json").read_text())
EPS_OX = 3.9 * 8.854e-12
TOX = 4.1e-9
COX = EPS_OX / TOX                     # F/m^2
CGDO_N, CGDO_P = 7.83e-10, 6.54e-10    # F/m (model overlap caps)
CJ_N, CJ_P = 9.97e-4, 1.154e-3         # F/m^2 (zero-bias area junction caps)
CJSW_N, CJSW_P = 2.62e-10, 2.51e-10    # F/m

# ----------------------------------------------------------------- spec
SPEC = dict(
    VIN_NOM=1.8, VIN_MIN=1.7, VIN_MAX=1.9,
    VOUT=1.5, VREF=0.6,
    IL_MIN=0.1e-3, IL_MAX=50e-3,
    VDO=0.2,                 # dropout at IL_MAX
    CL=2.2e-6, ESR=10e-3, ESR_MAX=50e-3,
    IQ_MAX=100e-6,
    PM_MIN=45.0,
    PSRR_MIN_DB=30.0,        # at 1 kHz, IL_MAX
    LOADREG_MAX=15e-3,       # |dVOUT| for IL_MIN -> IL_MAX
    LINEREG_MAX=35e-3,       # V/V over VIN_MIN..VIN_MAX
    TRAN_MAX=50e-3,          # |dVOUT| for a 0.1 <-> 50 mA step, 1 us edges
)


def rd(x, n=4):
    return float(f"{x:.{n}g}")


def main():
    s = SPEC
    H = {}                                   # hand results
    n18, p18 = P["n_L0.18"], P["p_L0.18"]
    p05, p1, n1 = P["p_L0.50"], P["p_L1.00"], P["n_L1.00"]

    # ---- step 1: feedback divider (Sec. 4.1)
    beta = s["VREF"] / s["VOUT"]
    I_div = 10e-6
    R2 = s["VREF"] / I_div
    R1 = (s["VOUT"] - s["VREF"]) / I_div
    H.update(beta=beta, R1=R1, R2=R2, I_div=I_div)

    # ---- step 2: pass device (Sec. 4.2)
    # (a) saturation at VIN_NOM, IL_MAX:  VOV <= VSD = VIN_NOM - VOUT (10 mV margin)
    vsd_nom = s["VIN_NOM"] - s["VOUT"]
    vov_p = vsd_nom - 0.01
    WL_p = 2 * s["IL_MAX"] / (p18["KP"] * vov_p ** 2)
    LP = 0.18e-6
    Wf = 10e-6
    MP = math.ceil(WL_p * LP / Wf / 10) * 10          # round up to 10 fingers
    WP = MP * Wf
    WL_p = WP / LP
    vov_p = math.sqrt(2 * s["IL_MAX"] / (p18["KP"] * WL_p))
    vsg_max_load = p18["VTH"] + vov_p
    gm_p_max = 2 * s["IL_MAX"] / vov_p
    # (b) dropout check: VSD = VDO, triode, solve for VOV
    #     IL = KP W/L (VOV VSD - VSD^2/2)  ->  VOV = IL/(KP W/L VSD) + VSD/2
    vov_do = s["IL_MAX"] / (p18["KP"] * WL_p * s["VDO"]) + s["VDO"] / 2
    vsg_do = p18["VTH"] + vov_do
    # (c) light-load VSG read from the simulated ID-VSG curve of one 10-um finger
    vgs_c, id_c = idvg("p", LP)
    i_f = s["IL_MIN"] / MP
    vsg_min_load = float(np.interp(np.log(i_f), np.log(id_c[id_c > 0]),
                                   vgs_c[id_c > 0]))
    # weak-inversion gm at light load from the same curve: gm = dID/dVSG
    gm_c = np.gradient(id_c, vgs_c)
    gm_p_min = float(np.interp(vsg_min_load, vgs_c, gm_c)) * MP
    dVSG = vsg_max_load - vsg_min_load
    # gate capacitance (saturation): 2/3 W L Cox + 2 overlaps
    Cg = (2 / 3) * WP * LP * COX + 2 * CGDO_P * WP
    H.update(WP=WP, MP=MP, WL_p=WL_p, vov_p=vov_p, vsg_max_load=vsg_max_load,
             gm_p_max=gm_p_max, vov_do=vov_do, vsg_do=vsg_do,
             vsg_min_load=vsg_min_load, gm_p_min=gm_p_min, dVSG=dVSG, Cg=Cg)

    # ---- step 3: required loop gain G = beta * A_ea * A_b (Sec. 4.3)
    G_psrr = 10 ** (s["PSRR_MIN_DB"] / 20)
    G_load = dVSG / s["LOADREG_MAX"]
    G_line = 1 / s["LINEREG_MAX"]
    G_req = max(G_psrr, G_load, G_line)
    H.update(G_psrr=G_psrr, G_load=G_load, G_line=G_line, G_req=G_req)

    # ---- steps 4-8 for one error-amplifier channel length (v1: 1 um, v2: 2 um)
    def ea_design(L12, L34, vov_b, I_fixed=None):
        E = {}
        pL = P[f"p_L{L12*1e6:.2f}"]
        nL = P[f"n_L{L34*1e6:.2f}"]
        # step 4: A_ea = gm1/(gds2+gds4) = (2/VOV1)/(lam_p + lam_n)
        vov1 = 0.10
        lam_sum = pL["lam"] + nL["lam"]
        A_ea = (2 / vov1) / lam_sum
        # buffer gain (bulk tied to source):  A_b = gm_b/(gm_b + gds_b + gds_bs)
        I_B = 30e-6
        gm_b = 2 * I_B / vov_b
        gds_b = p05["lam"] * I_B
        gds_bs = p1["lam"] * I_B
        A_b = gm_b / (gm_b + gds_b + gds_bs)
        G = beta * A_ea * A_b
        UGF = G * gm_p_max / (2 * math.pi * s["CL"])
        E.update(L12=L12, L34=L34, vov_b=vov_b, vsg_b=p05["VTH"] + vov_b, vov1=vov1, lam_sum=lam_sum, A_ea=A_ea, A_b=A_b,
                 G=G, UGF_max=UGF, gm_b=gm_b, I_B=I_B)
        # step 5: non-dominant poles
        p_b = gm_b / (2 * math.pi * Cg)
        LB = 0.5e-6
        WB = 2 * I_B / (p05["KP"] * vov_b ** 2) * LB
        vov34 = 0.15

        def caps(I_D1):
            W12 = 2 * I_D1 / (pL["KP"] * vov1 ** 2) * L12
            W34 = 2 * I_D1 / (nL["KP"] * vov34 ** 2) * L34
            c_m2 = CGDO_P * W12 + CJ_P * W12 * 0.5e-6 + CJSW_P * (2 * W12 + 1e-6)
            c_m4 = CGDO_N * W34 + CJ_N * W34 * 0.5e-6 + CJSW_N * (2 * W34 + 1e-6)
            cgs_b = (2 / 3) * WB * LB * COX + CGDO_P * WB
            c_b_in = CGDO_P * WB + cgs_b * (1 - A_b)
            return W12, W34, c_m2 + c_m4 + c_b_in, dict(c_m2=c_m2, c_m4=c_m4, c_b_in=c_b_in)

        # With VOV1 fixed, W12 and W34 scale with I_D1, so C_ea (dominated by the
        # EA's own drain capacitance) scales with I_D1 too and
        #   p_ea = lam_sum*I_D1/(2 pi C_ea)  ~  lam_sum*KP*VOV1^2/(4 pi c'_d L)
        # does not depend on I_D1 (note Sec. 4.5).  I_D1 is therefore set by the
        # current budget: 20 uA per side.
        I_D1 = 20e-6 if I_fixed is None else I_fixed
        W12, W34, C_ea, cparts = caps(I_D1)
        Ro_ea = 1 / (lam_sum * I_D1)
        p_ea = 1 / (2 * math.pi * Ro_ea * C_ea)
        z_esr = 1 / (2 * math.pi * s["ESR"] * s["CL"])
        E.update(I_D1=I_D1, W12=W12, W34=W34, WB=WB, C_ea=C_ea, cparts=cparts,
                 Ro_ea=Ro_ea, p_b=p_b, p_ea=p_ea, z_esr=z_esr)

        # step 6: loop gain and phase margin at both load ends
        def loop(IL, gm_p, esr):
            # load = ideal current sink (as in the test bench): no RL term
            rds = 1 / (p18["lam"] * IL)
            Ro = 1 / (1 / rds + 1 / (R1 + R2))
            T0 = G * gm_p * Ro
            f = np.logspace(0, 9, 20001)
            w = 2 * np.pi * f
            Zout = 1 / (1 / Ro + 1 / (esr + 1 / (1j * w * s["CL"])))
            T = G * gm_p * Zout / ((1 + 1j * f / p_b) * (1 + 1j * f / p_ea))
            k = np.argmax(np.abs(T) < 1)
            pm = 180 + np.degrees(np.angle(T[k]))
            return dict(T0=T0, T0_dB=20 * math.log10(T0), Ro=Ro,
                        p_o=1 / (2 * math.pi * Ro * s["CL"]), UGF=float(f[k]), PM=float(pm))

        E["light"] = loop(s["IL_MIN"], gm_p_min, s["ESR"])
        E["heavy"] = loop(s["IL_MAX"], gm_p_max, s["ESR"])
        E["heavy_esr0"] = loop(s["IL_MAX"], gm_p_max, 1e-9)
        # step 7: regulation and PSRR predictions
        E["loadreg"] = dVSG / G
        E["linereg"] = 1 / G
        E["psrr_dc_dB"] = 20 * math.log10(G)
        E["ESR_bound"] = 1 / (G * gm_p_max)
        # step 8: quiescent current, slew estimate
        IREF = 5e-6
        I_T = 2 * I_D1
        E.update(IREF=IREF, I_T=I_T, Iq=IREF + I_T + I_B + I_div)
        E["t_slew"] = Cg * dVSG / I_B
        E["dV_release"] = s["IL_MAX"] * E["t_slew"] / (2 * s["CL"])
        Lm = 1e-6
        Wbias = 5e-6
        sizes = dict(
            IREF=IREF, VREF=s["VREF"],
            Wbias=Wbias, Lbias=Lm,
            W5=rd(Wbias * I_T / IREF), L5=Lm,
            WBS=rd(Wbias * I_B / IREF), LBS=Lm,
            W12=rd(math.ceil(W12 * 1e6) * 1e-6), L12=L12,
            W34=rd(math.ceil(W34 * 1e6) * 1e-6), L34=L34,
            WB=rd(math.ceil(WB * 1e6) * 1e-6), LB=LB,
            WPf=Wf, LP=LP, MP=MP,
            R1=R1, R2=R2, CL=s["CL"], ESR=s["ESR"],
        )
        return E, sizes

    # ---- EA output headroom window for the buffer VSG (Sec. 4.6)
    #   upper: VEA <= VREF + |VTH,p|  (M2 saturated), worst at VIN_MAX, IL_MIN
    #   lower: VEA >= VOV4            (M4 saturated), worst at VIN_MIN, IL_MAX
    #   VEA = VIN - VSG,p(IL) - VSG,b
    vth_p1 = P["p_L1.00"]["VTH"]
    vov4 = 0.15
    vsgb_lo = s["VIN_MAX"] - vsg_min_load - s["VREF"] - vth_p1
    vsgb_hi = s["VIN_MIN"] - vsg_do - vov4
    vsgb_mid = 0.5 * (vsgb_lo + vsgb_hi)
    vovb_mid = vsgb_mid - p05["VTH"]
    H.update(vsgb_lo=vsgb_lo, vsgb_hi=vsgb_hi, vsgb_mid=vsgb_mid, vovb_mid=vovb_mid)

    # design iterations (Sec. 5): v1 first pass, v2 longer EA devices,
    # v3 = final (short input pair, long mirror, buffer VSG from the window)
    v1, sizes_v1 = ea_design(1e-6, 1e-6, 0.15)
    v2, sizes_v2 = ea_design(2e-6, 2e-6, 0.15)
    v3, sizes_v3 = ea_design(1e-6, 3e-6, round(vovb_mid, 2))
    for name, sz in (("v1", sizes_v1), ("v2", sizes_v2), ("v3", sizes_v3)):
        (ROOT / "scripts" / f"sizes_{name}.json").write_text(json.dumps(sz, indent=2))
    (ROOT / "scripts" / "sizes.json").write_text(json.dumps(sizes_v3, indent=2))
    (ROOT / "scripts" / "hand.json").write_text(json.dumps(
        dict(spec=s, common=H, v1=v1, v2=v2, v3=v3), indent=2, default=float))
    for k, v in H.items():
        print(f"{k:14s} {v}")
    for name, E in (("v1", v1), ("v2", v2), ("v3", v3)):
        print(f"---- {name}")
        for k, v in E.items():
            print(f"  {k:14s} {v}")
    for name, sz in (("v1", sizes_v1), ("v2", sizes_v2), ("v3", sizes_v3)):
        print(f"sizes {name}:", json.dumps(sz))


if __name__ == "__main__":
    main()
