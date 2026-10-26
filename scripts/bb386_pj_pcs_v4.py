#!/usr/bin/env python3
"""BB386_PJ_PCS_V4: sample the caller too (blitz86 r73c).

The sampler interrupt also reads the interrupted LR, so time in leaf
functions (64-bit divides, memchr, busy_wait_us, ...) can be charged to the
code that calls them. Each [bb386-churn] dump then prints
  [bb386-pcs-callers] LR:count ...
and bb386_pcs_symbols.py lists both tables.
Run after bb386_pj_pcs_v1/v2.py. Sampling itself is still switched with
bb386_pj_pcs_v3.py ($env:BB_PCS='1'). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
EDITS = [
    ('extern void b86_pj_pc_sample(uint32_t pc);\n',
     'extern void b86_pj_pc_sample(uint32_t pc);\nextern void b86_pj_pc_sample_lr(uint32_t pc, uint32_t lr);   /* BB386_PJ_PCS_V4 */\n'),
    ('bb_pcs_c(uint32_t pc)\n', 'bb_pcs_c(uint32_t pc, uint32_t lr)\n'),
    ('    b86_pj_pc_sample(pc);\n}', '    b86_pj_pc_sample_lr(pc, lr);\n}'),
    ('        "ldr r0, [r0, #24]\\n"\n', '        "ldr r1, [r0, #20]\\n"\n        "ldr r0, [r0, #24]\\n"\n'),
]
A_TOP = '''          if (tn) {
            printf("[bb386-pcs-top]");'''
ADD_TOP = '''          { /* BB386_PJ_PCS_V4 */
            extern unsigned b86_pj_pc_top_lr(unsigned n, uint32_t *pc, uint32_t *cnt);
            uint32_t lp[24], lc[24]; unsigned ln = b86_pj_pc_top_lr(24u, lp, lc), q;
            if (ln) {
              printf("[bb386-pcs-callers]");
              for (q = 0; q < ln; ++q) printf(" %08lX:%lu", (unsigned long)lp[q], (unsigned long)lc[q]);
              printf("\\n");
            }
          }
'''

def main():
    t = open(LIVE, newline="").read()
    crlf = "\r\n" in t
    u = t.replace("\r\n", "\n") if crlf else t
    if "BB386_PJ_PCS_V4" in u:
        print("bb_live.c: BB386_PJ_PCS_V4 already applied"); return 0
    if "BB386_PJ_PCS_V2" not in u: raise SystemExit("ABORT: run bb386_pj_pcs_v1.py and v2.py first")
    for old, new in EDITS:
        if u.count(old) != 1: raise SystemExit("ABORT: anchor not found once: %r" % old[:50])
        u = u.replace(old, new, 1)
    if u.count(A_TOP) != 1: raise SystemExit("ABORT: [bb386-pcs-top] print not found")
    u = u.replace(A_TOP, ADD_TOP + A_TOP, 1)
    bak = LIVE + ".pre_pj_pcs_v4"
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(LIVE, "w", newline="").write(u.replace("\n", "\r\n") if crlf else u)
    print("BB386_PJ_PCS_V4 applied to " + LIVE)
    return 0

if __name__ == "__main__":
    sys.exit(main())
