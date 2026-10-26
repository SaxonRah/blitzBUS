#!/usr/bin/env python3
"""BB386_PJ_HOT_V1: SRAM tier for the hottest native protected-mode blocks (blitz86 r72).

The XIP-cache model of the Descent demo put ~92% of cache misses on PJ code
fetched from PSRAM. r72 can re-translate the hottest blocks into an SRAM
buffer (their PSRAM copies jump there). This script:
  * adds  BB_PJ_HOT_KB=<n>  to the build when $env:BB_PJ_HOT_KB is set
  * allocates that SRAM buffer in bb_live.c and attaches it after PJ
  * prints [bb386-hot] promotions/resets/refused/used/trampolines with the
    [bb386-churn] line (if bb386_pj_churn_v1.py is applied)
Give the SRAM back elsewhere, e.g. the real-mode JIT cache:
    $env:BB_CODE_KB = '128'; $env:BB_PJ_HOT_KB = '96'
Without BB_PJ_HOT_KB nothing changes. Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
INST = os.path.join(ROOT, "scripts", "install_live.py")
A_ATTACH = '''            printf("[bb386-pj] attach FAILED: state needs %u B\\n", (unsigned)b86_pj_state_bytes());
        fflush(stdout);
'''
ADD_ATTACH = '''#if defined(BB_PJ_HOT_KB) && BB_PJ_HOT_KB > 0   /* BB386_PJ_HOT_V1 */
        {
            extern int b86_pj_attach_hot(B86Cpu *c, void *buf, size_t bytes);
            static uint8_t bb_pj_hot[BB_PJ_HOT_KB * 1024u] __attribute__((aligned(64)));   /* SRAM */
            const int ok = b86_pj_attach_hot(&C, bb_pj_hot, sizeof bb_pj_hot);
            printf("[bb386-pj] SRAM hot tier: %u KiB at %p %s\\n", (unsigned)BB_PJ_HOT_KB, (void *)bb_pj_hot, ok ? "on" : "FAILED");
            fflush(stdout);
        }
#endif
'''
A_CHURN = '''        sp_t = now; sp_i = ic; sp_blocks = pj[0];
'''
ADD_CHURN = '''#if defined(BB_PJ_HOT_KB) && BB_PJ_HOT_KB > 0   /* BB386_PJ_HOT_V1 */
        { extern void b86_pj_hot_stats(const B86Cpu *c, unsigned long out[6]); unsigned long hs[6];
          b86_pj_hot_stats(&C, hs);
          printf("[bb386-hot] promotions=%lu resets=%lu refused=%lu used=%lu/%lu trampolines=%lu\\n", hs[0], hs[1], hs[2], hs[3], hs[4], hs[5]); }
#endif
'''
I_OLD = '{(\" BB_PJ_CODE_KB=\"+os.environ[\"BB_PJ_CODE_KB\"]) if os.environ.get(\"BB_PJ_CODE_KB\") else \"\"}'
I_NEW = I_OLD + '{(\" BB_PJ_HOT_KB=\"+os.environ[\"BB_PJ_HOT_KB\"]) if os.environ.get(\"BB_PJ_HOT_KB\") else \"\"}'
def edit(path, fn):
    t = open(path, newline="").read()
    crlf = "\r\n" in t
    u = t.replace("\r\n", "\n") if crlf else t
    r = fn(u)
    if r is None: return False
    bak = path + ".pre_pj_hot_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(path, "w", newline="").write(r.replace("\n", "\r\n") if crlf else r)
    return True
def live(u):
    if "BB386_PJ_HOT_V1" in u: print("bb_live.c: already applied"); return None
    if u.count(A_ATTACH) != 1: raise SystemExit("ABORT: PJ attach block not found (apply bb386_pj_v1.py first)")
    u = u.replace(A_ATTACH, A_ATTACH + ADD_ATTACH, 1)
    if u.count(A_CHURN) == 1: u = u.replace(A_CHURN, A_CHURN + ADD_CHURN, 1)
    else: print("note: [bb386-churn] block not found; hot stats line not added")
    return u
def inst(u):
    if "BB_PJ_HOT_KB" in u: print("install_live.py: already applied"); return None
    if u.count(I_OLD) != 1: raise SystemExit("ABORT: BB_PJ_CODE_KB option not found in install_live.py")
    return u.replace(I_OLD, I_NEW, 1)
if __name__ == "__main__":
    if edit(LIVE, live): print("BB386_PJ_HOT_V1 applied to", LIVE)
    if edit(INST, inst): print("BB386_PJ_HOT_V1 applied to", INST)
