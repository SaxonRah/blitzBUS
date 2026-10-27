#!/usr/bin/env python3
"""BB386_PJ_V1: enable blitz86's native protected-mode translator (PJ).

Needs blitz86 r70 and BB386_PMRAM_V1. PJ compiles straight-line runs of
flat 32-bit protected-mode code (Descent's game code under DOS/4GW) to
Thumb-2 in an SRAM buffer, so those instructions no longer go through the
interpreter. Anything it does not handle still runs on PM40/the stages.

This script
  1. adds B86_PJ / B86_PJ_HASH / B86_PJ_CPS / BB_PJ_CODE_KB to the compile
     definitions in scripts/install_live.py ($env:BB_PJ='0' disables it;
     $env:BB_PJ_CODE_KB sets the code buffer, default 64), and
  2. attaches the translator in src/bb_live.c right after the real-mode JIT
     is created, and adds a "[bb386-pj]" statistics line to the
     [bb386-pm] dumps.
The translated code goes to a 512 KiB buffer in PSRAM by default (it runs
through the XIP cache; $env:BB_PJ_PSRAM='0' puts a 64 KiB buffer in SRAM
instead, $env:BB_PJ_CODE_KB sets the size). The 8 KiB of lookup state is in
SRAM, so with PMRAM's 18 KiB already taken use e.g.
    $env:BB_CODE_KB = '192'      ('120' with BB_PJ_PSRAM=0)

Usage: python .\\scripts\\bb386_pj_v1.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
INST = os.path.join(ROOT, "scripts", "install_live.py")
ATTACH = r'''
#if defined(B86_PJ) && B86_PJ   /* BB386_PJ_V1: native protected-mode translator */
    {
#ifndef BB_PJ_PSRAM
#define BB_PJ_PSRAM 1                       /* code buffer in PSRAM (runs through the XIP cache) */
#endif
#if BB_PJ_PSRAM && defined(__uninitialized_psram)
#ifndef BB_PJ_CODE_KB
#define BB_PJ_CODE_KB 512
#endif
        static uint8_t __uninitialized_psram("zzz_bb_pj_code") __attribute__((aligned(64))) bb_pj_code[BB_PJ_CODE_KB * 1024u];
        const char *bb_pj_where = "PSRAM";
#else
#ifndef BB_PJ_CODE_KB
#define BB_PJ_CODE_KB 64
#endif
        static uint8_t bb_pj_code[BB_PJ_CODE_KB * 1024u] __attribute__((aligned(64)));
        const char *bb_pj_where = "SRAM";
#endif
        static uint64_t bb_pj_state[8192u / 8u];       /* SRAM: hash tables are probed on every block */
        if (b86_pj_attach(&C, bb_pj_state, sizeof bb_pj_state, bb_pj_code, sizeof bb_pj_code))
            printf("[bb386-pj] native PM translator: %u KiB code in %s at %p, state %u B\n",
                   (unsigned)BB_PJ_CODE_KB, bb_pj_where, (void *)bb_pj_code, (unsigned)b86_pj_state_bytes());
        else
            printf("[bb386-pj] attach FAILED: state needs %u B\n", (unsigned)b86_pj_state_bytes());
        fflush(stdout);
    }
#endif
'''
STATS = r'''#if defined(B86_PJ) && B86_PJ   /* BB386_PJ_V1 */
    { unsigned long pj[8], so[256]; int k, q, best;
      b86_pj_stats(&C, pj); b86_pj_stop_ops(&C, so);
      printf("[bb386-pj]   blocks=%lu flush(smc,full)=%lu,%lu runs=%lu native=%lu (%.1f/run) mem-exits=%lu declined=%lu code=%lu/%lu stops:",
             pj[0], pj[1] / 1000000ul, pj[1] % 1000000ul, pj[2], pj[3], pj[2] ? (double)pj[3] / (double)pj[2] : 0.0, pj[4], pj[5], pj[6], pj[7]);
      for (k = 0; k < 8; ++k) { best = 0; for (q = 1; q < 256; ++q) if (so[q] > so[best]) best = q; if (!so[best]) break; printf(" %02X:%lu", best, so[best]); so[best] = 0; }
      printf("\n"); }
#endif
'''
def main():
    s = open(LIVE, newline="").read()
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    changed = False
    if "BB386_PJ_V1" not in s:
        a = "    J = b86_jit_create_ex(&C, bb_code, BB_CODE_BYTES, bb_hot, sizeof bb_hot);\n"
        b = '    printf("[bb386-pm]   code@%08lX:", (unsigned long)lin);\n'
        if s.count(a) != 1 or s.count(b) != 1:
            print("ABORT: bb_live.c anchors not found (JIT create %d, PM dump %d)" % (s.count(a), s.count(b))); return 1
        s = s.replace(a, a + ATTACH, 1).replace(b, STATS + b, 1)
        bak = LIVE + ".pre_pj_v1"
        if not os.path.exists(bak): open(bak, "w", newline="").write(open(LIVE, newline="").read())
        out = s.replace("\n", "\r\n") if crlf else s
        open(LIVE, "w", newline="").write(out)
        print("BB386_PJ_V1 applied to", LIVE); changed = True
    else:
        print("bb_live.c: already applied")
    t = open(INST, newline="").read()
    if "B86_PJ=" not in t:
        old = "B86_RAM_FUNCS=1 B86_PM_RAM="
        if t.count(old) != 1:
            print("ABORT: apply scripts\\bb386_pmram_v1.py first (install_live.py anchor missing)"); return 1
        new = ("B86_RAM_FUNCS=1 B86_PJ={os.environ.get(\"BB_PJ\",\"1\")} B86_PJ_HASH=512u B86_PJ_CPS=256u "
               "BB_PJ_PSRAM={os.environ.get(\"BB_PJ_PSRAM\",\"1\")}"
               "{(\" BB_PJ_CODE_KB=\"+os.environ[\"BB_PJ_CODE_KB\"]) if os.environ.get(\"BB_PJ_CODE_KB\") else \"\"} B86_PM_RAM=")
        bak = INST + ".pre_pj_v1"
        if not os.path.exists(bak): open(bak, "w", newline="").write(t)
        open(INST, "w", newline="").write(t.replace(old, new, 1))
        print("BB386_PJ_V1 applied to", INST); changed = True
    else:
        print("install_live.py: already applied")
    if changed:
        print("Rebuild with room for the PJ state, e.g.  $env:BB_CODE_KB = '192'")
    return 0
if __name__ == "__main__":
    sys.exit(main())
