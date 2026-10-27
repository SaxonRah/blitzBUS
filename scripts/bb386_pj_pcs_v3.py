#!/usr/bin/env python3
"""BB386_PJ_PCS_V3: turn the 20 kHz core-0 PC sampler on or off (blitz86 r73b).

  $env:BB_PCS = '0'   (default) sampler not started: no timer interrupt,
                      no [bb386-pcs] / [bb386-pcs-top] lines
  $env:BB_PCS = '1'   sampler started as in bb386_pj_pcs_v1.py

Re-run the script after changing the variable. Everything else from v1/v2
([bb386-rmjit], [bb386-xip]) stays.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
ON = "        bb_pcs_start();   /* BB386_PJ_PCS_V1 */\n"
OFF = "        /* bb_pcs_start(); BB386_PJ_PCS_V1 sampler off (BB386_PJ_PCS_V3) */\n"

def main():
    want_on = os.environ.get("BB_PCS", "0").strip() == "1"
    t = open(LIVE, newline="").read()
    crlf = "\r\n" in t
    u = t.replace("\r\n", "\n") if crlf else t
    if ON not in u and OFF not in u: raise SystemExit("ABORT: run bb386_pj_pcs_v1.py first")
    new = u.replace(OFF, ON) if want_on else u.replace(ON, OFF)
    if new == u:
        print("bb_live.c: sampler already %s" % ("ON" if want_on else "OFF")); return 0
    bak = LIVE + ".pre_pj_pcs_v3"
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(LIVE, "w", newline="").write(new.replace("\n", "\r\n") if crlf else new)
    print("BB386_PJ_PCS_V3: sampler %s in %s" % ("ON" if want_on else "OFF", LIVE))
    return 0

if __name__ == "__main__":
    sys.exit(main())
