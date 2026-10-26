#!/usr/bin/env python3
"""BB386_PJ_PCS_V2: function-level profile + switches (blitz86 r73).

Run after bb386_pj_pcs_v1.py. Adds to each [bb386-churn] dump:
  [bb386-pcs-top] PC:count ...   the 24 most-sampled C-code PCs (8-byte
                                  buckets, SRAM and flash) since the last dump
  [bb386-rmjit] flushes=.. pm-return-flushes=.. pm-return-kept=..
                                  real-mode code-cache flushes; r73 keeps the
                                  cache when DOS/4GW returns to real mode
Turn the PC lists into function names with:
  python scripts\\bb386_pcs_symbols.py logs\\bb-live-....-console.txt

Sample-driven SRAM promotion (r72f) is OFF unless $env:BB_PCS_PROMOTE='1'
when this script runs (re-run the script to change it).
"""
import os, re, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
A_START = "        bb_pcs_start();   /* BB386_PJ_PCS_V1 */\n"
A_CHURN = "        sp_t = now; sp_i = ic; sp_blocks = pj[0];\n"
ADD_CHURN = r'''        { /* BB386_PJ_PCS_V2 */
          extern unsigned b86_pj_pc_top(unsigned n, uint32_t *pc, uint32_t *cnt);
          extern void b86_jit_flush_causes(const struct B86Jit *j, unsigned long out[3]);
          uint32_t tp[24], tc[24]; unsigned tn = b86_pj_pc_top(24u, tp, tc), k;
          unsigned long fc[3];
          if (tn) {
            printf("[bb386-pcs-top]");
            for (k = 0; k < tn; ++k) printf(" %08lX:%lu", (unsigned long)tp[k], (unsigned long)tc[k]);
            printf("\n");
          }
          b86_jit_flush_causes(C.jit, fc);
          printf("[bb386-rmjit] flushes=%lu pm-return-flushes=%lu pm-return-kept=%lu\n", fc[0], fc[1], fc[2]);
        }
'''
PROMO_RE = re.compile(r"        b86_pj_pc_promote\([01]\);   /\* BB386_PJ_PCS_V2 promote \*/\n")

def main():
    on = 1 if os.environ.get("BB_PCS_PROMOTE", "0").strip() == "1" else 0
    promo = "        b86_pj_pc_promote(%d);   /* BB386_PJ_PCS_V2 promote */\n" % on
    t = open(LIVE, newline="").read()
    crlf = "\r\n" in t
    u = t.replace("\r\n", "\n") if crlf else t
    if "BB386_PJ_PCS_V1" not in u: raise SystemExit("ABORT: run bb386_pj_pcs_v1.py first")
    changed = False
    if PROMO_RE.search(u):
        u2 = PROMO_RE.sub(lambda m: promo, u, count=1)
        changed = u2 != u; u = u2
    else:
        if u.count(A_START) != 1: raise SystemExit("ABORT: bb_pcs_start() call not found")
        u = u.replace(A_START, A_START + "        { extern void b86_pj_pc_promote(int on);\n" + promo + "        }\n", 1)
        changed = True
    if "BB386_PJ_PCS_V2 */\n          extern unsigned b86_pj_pc_top" not in u:
        if u.count(A_CHURN) != 1: raise SystemExit("ABORT: [bb386-churn] block not found")
        u = u.replace(A_CHURN, A_CHURN + ADD_CHURN, 1)
        changed = True
    if not changed:
        print("bb_live.c: already applied (sample promotion %s)" % ("ON" if on else "OFF")); return 0
    bak = LIVE + ".pre_pj_pcs_v2"
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(LIVE, "w", newline="").write(u.replace("\n", "\r\n") if crlf else u)
    print("BB386_PJ_PCS_V2 applied to %s (sample promotion %s)" % (LIVE, "ON" if on else "OFF"))
    return 0

if __name__ == "__main__":
    sys.exit(main())
