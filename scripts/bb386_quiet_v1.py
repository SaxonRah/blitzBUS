#!/usr/bin/env python3
"""BB386_QUIET_V1: stop the per-mode-switch log flood in src/bb_live.c.

DOS/4GW switches real <-> protected mode hundreds of times while it loads a
program (every DOS call from protected mode is a round trip). Each switch
printed ~40 lines: [bb386-pm] ENTER/LEAVE with full registers, the V13
"follow 6 dispatches after PM exit" dumps and the V15 callback snapshots.
That flood is what scrolled past so fast, and it slows the guest down a lot.

After this patch:
  * ENTER/LEAVE are printed for switches 1, 2, 4, 8, 16, ... (numbered);
  * V13 follow-ups and V15 snapshots are off unless built with
    -DBB386_TRACE_PM_EXIT=1 (they were for the 1231:6570 BIOS-vector bug);
  * failures still dump: [bb386-pm] STOP, and V13 on HALT/UNSUPPORTED/SHUTDOWN.

Usage: python .\\scripts\\bb386_quiet_v1.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_QUIET_V1"

EDITS = [
("ENTER/LEAVE logging",
"""    if (pm && !bb386_pm_was) {
        printf("[bb386-pm] ENTER protected mode (rc=%s retired=%lu)\\n", bb386_rc_name(rc), (unsigned long)C.icnt);
        bb386_pm_regs("enter");
    } else if (!pm && bb386_pm_was) {
        printf("[bb386-pm] LEAVE protected mode -> real mode %04X:%04X after %lu PM slices\\n",
               (unsigned)C.seg[B86_CS], (unsigned)(C.ip & 0xFFFFu), bb386_pm_slices);
        fflush(stdout);
    }""",
"""    static unsigned long bb386_pm_entries;   /* BB386_QUIET_V1: log switches 1,2,4,8,... */
    const int bb386_loud = bb386_pm_entries < 2u || !(bb386_pm_entries & (bb386_pm_entries - 1u));
    if (pm && !bb386_pm_was) {
        ++bb386_pm_entries;
        if (bb386_pm_entries <= 2u || !(bb386_pm_entries & (bb386_pm_entries - 1u))) {
            printf("[bb386-pm] ENTER protected mode #%lu (rc=%s retired=%lu)\\n",
                   bb386_pm_entries, bb386_rc_name(rc), (unsigned long)C.icnt);
            bb386_pm_regs("enter");
        }
    } else if (!pm && bb386_pm_was && bb386_loud) {
        printf("[bb386-pm] LEAVE protected mode #%lu -> real mode %04X:%04X after %lu PM slices\\n",
               bb386_pm_entries, (unsigned)C.seg[B86_CS], (unsigned)(C.ip & 0xFFFFu), bb386_pm_slices);
        fflush(stdout);
    }"""),
("V15 snapshot gate",
"""static unsigned bb386_v15_remaining;""",
"""#ifndef BB386_TRACE_PM_EXIT
#define BB386_TRACE_PM_EXIT 0   /* BB386_QUIET_V1: 1 = V13/V15 per-PM-exit traces */
#endif
static unsigned bb386_v15_remaining;"""),
("V15 PM-exit trigger",
"""    if (was_pm && !now_pm) {
        bb386_v15_remaining=8u;
        return 1;
    }""",
"""    if (was_pm && !now_pm) {
        bb386_v15_remaining=BB386_TRACE_PM_EXIT ? 8u : 0u;   /* BB386_QUIET_V1 */
        return BB386_TRACE_PM_EXIT != 0;
    }"""),
("V13 follow-up",
"""        if (bb386_v13_pre_pm && !(C.msw & 1u)) bb386_v13_follow = 6u;""",
"""        if (bb386_v13_pre_pm && !(C.msw & 1u)) bb386_v13_follow = BB386_TRACE_PM_EXIT ? 6u : 0u;   /* BB386_QUIET_V1 */"""),
]

def main():
    s = open(PATH, newline="").read()
    if MARK in s:
        print("already applied"); return 0
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    for name, old, new in EDITS:
        if s.count(old) != 1:
            print(f"ABORT: anchor '{name}' found {s.count(old)} times; bb_live.c unchanged"); return 1
    for name, old, new in EDITS:
        s = s.replace(old, new, 1)
    bak = PATH + ".pre_quiet_v1"
    if not os.path.exists(bak):
        open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB386_QUIET_V1 applied to", PATH)
    return 0

if __name__ == "__main__":
    sys.exit(main())
