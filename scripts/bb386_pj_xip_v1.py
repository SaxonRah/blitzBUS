#!/usr/bin/env python3
"""BB386_PJ_XIP_V1: where do the XIP cache misses come from? (blitz86 r72e)

r72d filled the SRAM tier but demo speed and misses per instruction did not
move, so the misses may not be PJ code. This script gives blitz86 the XIP
cache counters (xip_ctrl_hw->ctr_acc / ctr_hit) and the 1 MHz timer. blitz86
charges every native protected-mode run, and every gap between runs, to:
    sram   runs that start in the SRAM hot tier
    psram  runs that start in PSRAM code (may continue into SRAM via a jump)
    gaps   everything between runs: dispatcher, interpreter, real mode,
           DOS/BIOS, and any core-1 traffic during that time
and prints with each [bb386-churn] dump (deltas since the previous dump):
  [bb386-xip] sram runs=.. insns=.. mips=.. miss/insn=.. time=..% |
              psram ... | gaps miss=.. time=..% | dropped=..
Core 1 (LCD) shares the cache, so its misses land in whatever core 0 was
doing at the time. 'dropped' counts samples skipped because the counters were
cleared or saturated meanwhile. Read-only; costs a few register reads per run.
Needs bb386_pj_churn_v1.py applied first. Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
A_ATTACH = '''            printf("[bb386-pj] attach FAILED: state needs %u B\\n", (unsigned)b86_pj_state_bytes());
        fflush(stdout);
'''
ADD_ATTACH = '''        {   /* BB386_PJ_XIP_V1 */
            extern void b86_pj_set_xip_counters(B86Cpu *c, const volatile uint32_t *acc, const volatile uint32_t *hit, const volatile uint32_t *us);
#if defined(timer0_hw)
            b86_pj_set_xip_counters(&C, &xip_ctrl_hw->ctr_acc, &xip_ctrl_hw->ctr_hit, &timer0_hw->timerawl);
#else
            b86_pj_set_xip_counters(&C, &xip_ctrl_hw->ctr_acc, &xip_ctrl_hw->ctr_hit, &timer_hw->timerawl);
#endif
            printf("[bb386-pj] XIP miss split on\\n");
        }
'''
A_CHURN = '''        sp_t = now; sp_i = ic; sp_blocks = pj[0];
'''
ADD_CHURN = '''        { /* BB386_PJ_XIP_V1 */
          extern void b86_pj_xip_split(const B86Cpu *c, unsigned long out[12]);
          static unsigned long xp[12]; static uint64_t xt;
          unsigned long xs[12], d[12]; unsigned k;
          const uint64_t xn = time_us_64(); const double wall = xt ? (double)(xn - xt) : 0.0;
          b86_pj_xip_split(&C, xs);
          for (k = 0; k < 12u; ++k) { d[k] = xs[k] - xp[k]; xp[k] = xs[k]; }
          xt = xn;
          if (wall > 0.0)
            printf("[bb386-xip] sram runs=%lu insns=%lu mips=%.2f miss/insn=%.3f time=%.1f%% | psram runs=%lu insns=%lu mips=%.2f miss/insn=%.3f time=%.1f%% | gaps n=%lu miss=%lu miss/us=%.2f time=%.1f%% | dropped=%lu\\n",
                   d[0], d[1], d[3] ? (double)d[1] / (double)d[3] : 0.0, d[1] ? (double)d[2] / (double)d[1] : 0.0, 100.0 * (double)d[3] / wall,
                   d[4], d[5], d[7] ? (double)d[5] / (double)d[7] : 0.0, d[5] ? (double)d[6] / (double)d[5] : 0.0, 100.0 * (double)d[7] / wall,
                   d[8], d[9], d[10] ? (double)d[9] / (double)d[10] : 0.0, 100.0 * (double)d[10] / wall, d[11]);
        }
'''
INCLUDES = '#include "hardware/structs/xip_ctrl.h"   /* BB386_PJ_XIP_V1 */\n#include "hardware/structs/timer.h"\n'

def live(u):
    if "BB386_PJ_XIP_V1" in u:
        print("bb_live.c: already applied"); return None
    if u.count(A_ATTACH) != 1: raise SystemExit("ABORT: PJ attach block not found (apply bb386_pj_v1.py first)")
    if u.count(A_CHURN) != 1: raise SystemExit("ABORT: [bb386-churn] block not found (apply bb386_pj_churn_v1.py first)")
    u = u.replace(A_ATTACH, A_ATTACH + ADD_ATTACH, 1)
    u = u.replace(A_CHURN, A_CHURN + ADD_CHURN, 1)
    i = u.find("#include")
    if i < 0: raise SystemExit("ABORT: no #include line in bb_live.c")
    return u[:i] + INCLUDES + u[i:]

def main():
    t = open(LIVE, newline="").read()
    crlf = "\r\n" in t
    u = t.replace("\r\n", "\n") if crlf else t
    r = live(u)
    if r is None: return 0
    bak = LIVE + ".pre_pj_xip_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(LIVE, "w", newline="").write(r.replace("\n", "\r\n") if crlf else r)
    print("BB386_PJ_XIP_V1 applied to", LIVE)
    return 0

if __name__ == "__main__":
    sys.exit(main())
