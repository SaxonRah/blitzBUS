#!/usr/bin/env python3
"""BB386_PJ_PCS_V1: PC sampling on core 0 (blitz86 r72f).

r72e showed that during the Descent demo ~40% of protected-mode instructions
run in PSRAM code at ~1.05 XIP misses per instruction, in long chained runs
(~256 instructions per run). Those loops are entered from C once and then
chain inside PSRAM, so dispatch counting never promotes them to SRAM.

This script adds a 20 kHz timer interrupt on core 0 that reads the
interrupted PC and hands it to b86_pj_pc_sample(). blitz86 maps samples in
PSRAM code to their block and moves blocks that are hot by time (not by
entry count) into the SRAM tier. Each [bb386-churn] dump also prints where
core 0 spent its time, as a share of samples since the previous dump:
  [bb386-pcs] psram=..% shared=..% sram-tier=..% sram-other=..% flash=..%
              other=..% samples=.. promoted=..
(sram-other = C hot path in SRAM, real-mode JIT cache; flash = C code run
from flash XIP.) Uses one free hardware alarm; set $env:BB_PCS_US to change
the period (default 50 us). Needs bb386_pj_churn_v1.py first. Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
INST = os.path.join(ROOT, "scripts", "install_live.py")
A_ATTACH = '''            printf("[bb386-pj] attach FAILED: state needs %u B\\n", (unsigned)b86_pj_state_bytes());
        fflush(stdout);
'''
TOP = r'''/* BB386_PJ_PCS_V1: core-0 PC sampler for blitz86 (hot-loop promotion + time profile) */
#include "hardware/timer.h"
#include "hardware/irq.h"
#include "hardware/structs/timer.h"
#ifndef BB_PCS_US
#define BB_PCS_US 50u
#endif
extern void b86_pj_pc_sample(uint32_t pc);
static int bb_pcs_alarm = -1;
void __attribute__((used, noinline, section(".time_critical.bb_pcs_c"))) bb_pcs_c(uint32_t pc)
{
    timer0_hw->intr = 1u << bb_pcs_alarm;
    timer0_hw->alarm[bb_pcs_alarm] = timer0_hw->timerawl + BB_PCS_US;
    b86_pj_pc_sample(pc);
}
/* Exception entry stacked r0-r3, r12, lr, pc, xpsr: the interrupted PC is at
 * [sp, #24] of whichever stack was active. Tail-call the C part with it. */
void __attribute__((naked, section(".time_critical.bb_pcs_isr"))) bb_pcs_isr(void)
{
    __asm volatile(
        "tst lr, #4      \n"
        "ite eq          \n"
        "mrseq r0, msp   \n"
        "mrsne r0, psp   \n"
        "ldr r0, [r0, #24]\n"
        "b bb_pcs_c      \n");
}
static void bb_pcs_start(void)
{
    bb_pcs_alarm = hardware_alarm_claim_unused(false);
    if (bb_pcs_alarm < 0) { printf("[bb386-pcs] no free hardware alarm: sampling off\n"); return; }
    irq_set_exclusive_handler(TIMER0_IRQ_0 + bb_pcs_alarm, bb_pcs_isr);
    hw_set_bits(&timer0_hw->inte, 1u << bb_pcs_alarm);
    irq_set_enabled(TIMER0_IRQ_0 + bb_pcs_alarm, true);
    timer0_hw->alarm[bb_pcs_alarm] = timer0_hw->timerawl + 1000u;
    printf("[bb386-pcs] PC sampling every %u us on alarm %d\n", (unsigned)BB_PCS_US, bb_pcs_alarm);
}
'''
ADD_ATTACH = '''        bb_pcs_start();   /* BB386_PJ_PCS_V1 */
'''
A_CHURN = '''        sp_t = now; sp_i = ic; sp_blocks = pj[0];
'''
ADD_CHURN = '''        { /* BB386_PJ_PCS_V1 */
          extern void b86_pj_pc_stats(unsigned long out[8]);
          static unsigned long pp[8]; unsigned long ps[8], d[8], tot = 0; unsigned k;
          b86_pj_pc_stats(ps);
          for (k = 0; k < 8u; ++k) { d[k] = ps[k] - pp[k]; pp[k] = ps[k]; }
          for (k = 0; k < 7u; ++k) tot += d[k];
          if (tot)
            printf("[bb386-pcs] psram=%.1f%% shared=%.1f%% sram-tier=%.1f%% sram-other=%.1f%% flash=%.1f%% other=%.1f%% samples=%lu promoted=%lu\\n",
                   100.0 * d[0] / tot, 100.0 * d[1] / tot, 100.0 * d[2] / tot, 100.0 * d[3] / tot, 100.0 * d[4] / tot,
                   100.0 * (d[5] + d[6]) / tot, tot, d[7]);
        }
'''
I_OLD = '{(\\" BB_PJ_CODE_KB=\\"+os.environ[\\"BB_PJ_CODE_KB\\"]) if os.environ.get(\\"BB_PJ_CODE_KB\\") else \\"\\"}'
I_NEW = I_OLD + '{(\\" BB_PCS_US=\\"+os.environ[\\"BB_PCS_US\\"]+\\"u\\") if os.environ.get(\\"BB_PCS_US\\") else \\"\\"}'

def edit(path, fn, tag):
    t = open(path, newline="").read()
    crlf = "\r\n" in t
    u = t.replace("\r\n", "\n") if crlf else t
    r = fn(u)
    if r is None: return False
    bak = path + ".pre_" + tag
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(path, "w", newline="").write(r.replace("\n", "\r\n") if crlf else r)
    return True

def live(u):
    if "BB386_PJ_PCS_V1" in u:
        print("bb_live.c: already applied"); return None
    if u.count(A_ATTACH) != 1: raise SystemExit("ABORT: PJ attach block not found (apply bb386_pj_v1.py first)")
    if u.count(A_CHURN) != 1: raise SystemExit("ABORT: [bb386-churn] block not found (apply bb386_pj_churn_v1.py first)")
    u = u.replace(A_ATTACH, A_ATTACH + ADD_ATTACH, 1)
    u = u.replace(A_CHURN, A_CHURN + ADD_CHURN, 1)
    # helper code goes before the first function definition that uses C: put it after the last #include
    brace = u.find("{")
    last = u.rfind("\n#include", 0, brace if brace > 0 else len(u))
    if last < 0: raise SystemExit("ABORT: no #include line in bb_live.c")
    eol = u.find("\n", last + 1)
    return u[:eol + 1] + TOP + u[eol + 1:]

def inst(u):
    if "BB_PCS_US" in u:
        print("install_live.py: already applied"); return None
    if u.count(I_OLD) != 1:
        print("note: BB_PJ_CODE_KB option not found in install_live.py; BB_PCS_US stays at 50"); return None
    return u.replace(I_OLD, I_NEW, 1)

if __name__ == "__main__":
    if edit(LIVE, live, "pj_pcs_v1"): print("BB386_PJ_PCS_V1 applied to", LIVE)
    if os.path.exists(INST) and edit(INST, inst, "pj_pcs_v1"): print("BB386_PJ_PCS_V1 applied to", INST)
