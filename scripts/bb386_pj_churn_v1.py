#!/usr/bin/env python3
"""BB386_PJ_CHURN_V1: speed / translation-churn statistics for blitz86 r71.

Adds two lines next to every [bb386-pj] dump in src/bb_live.c:
  [bb386-speed] pm-mips=<protected-mode guest MIPS since the previous dump>
                pm-insns=<delta> wall-ms=<delta>
  [bb386-churn] flushes total/smc/full/pm16ctx/codepage, smc-stores,
                blocks-killed, refinds, new-blocks since the previous dump
Read-only: no effect on emulation. Needs blitz86 r71 (b86_pj_flush_causes).
Usage: python .\\scripts\\bb386_pj_churn_v1.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
ANCHOR = "      b86_pj_stats(&C, pj); b86_pj_stop_ops(&C, so);\n"
ADD = r'''      { /* BB386_PJ_CHURN_V1 */
        extern void b86_pj_flush_causes(const B86Cpu *c, unsigned long out[10]);
        static uint64_t sp_t, sp_i; static unsigned long sp_blocks;
        unsigned long fc[10];
        const uint64_t now = time_us_64(), ic = (uint64_t)C.icount;
        const double dt_ms = sp_t ? (double)(now - sp_t) / 1000.0 : 0.0;
        b86_pj_stats(&C, pj); b86_pj_flush_causes(&C, fc);
        printf("[bb386-speed] pm-mips=%.2f pm-insns=%llu wall-ms=%.0f\n",
               dt_ms > 0.0 ? (double)(ic - sp_i) / (dt_ms * 1000.0) : 0.0,
               (unsigned long long)(ic - sp_i), dt_ms);
        printf("[bb386-churn] flushes=%lu smc=%lu full=%lu pm16ctx=%lu codepage=%lu smc-stores=%lu killed=%lu refinds=%lu evictions=%lu unlinks=%lu new-blocks=%lu\n",
               fc[0], fc[1], fc[2], fc[3], fc[4], fc[5], fc[6], fc[7], fc[8], fc[9], pj[0] - sp_blocks);
        sp_t = now; sp_i = ic; sp_blocks = pj[0];
      }
'''
def main():
    s = open(LIVE, newline="").read()
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    if "BB386_PJ_CHURN_V1" in s:
        print("bb_live.c: already applied"); return 0
    if s.count(ANCHOR) != 1:
        print("ABORT: [bb386-pj] stats block not found (apply bb386_pj_v1.py first)"); return 1
    s = s.replace(ANCHOR, ANCHOR + ADD, 1)
    bak = LIVE + ".pre_pj_churn_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(open(LIVE, newline="").read())
    open(LIVE, "w", newline="").write(s.replace("\n", "\r\n") if crlf else s)
    print("BB386_PJ_CHURN_V1 applied to", LIVE)
    return 0
if __name__ == "__main__":
    sys.exit(main())
