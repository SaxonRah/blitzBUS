#!/usr/bin/env python3
"""BB386_PGSTAT_V1: paging/PIC statistics in the [bb386-pm] progress lines.

Needs blitz86 r65 (paging) and the earlier BB386_PM_STATE_V1 /
BB386_QUIET_V1 patches. Adds one line to every [bb386-pm] register dump:
    [bb386-pm]   pg=1 cr3=.. cr2=.. pf=.. tsw=.. walks=.. flush=.. icount=.. pic irr/isr/imr=..
and prints that dump every 4096 protected-mode slices (not only at powers
of two), so a slow phase shows its rate.

Usage: python .\\scripts\\bb386_pgstat_v1.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_PGSTAT_V1"
EDITS = [
("register dump",
"""    printf("[bb386-pm]   code@%08lX:", (unsigned long)lin);""",
"""    {   /* BB386_PGSTAT_V1 */
        extern unsigned long b86_pg_stat_faults, b86_pg_stat_tswitch, b86_pg_stat_walks, b86_pg_stat_flush;
        printf("[bb386-pm]   pg=%u cr3=%08lX cr2=%08lX pf=%lu tsw=%lu walks=%lu flush=%lu icount=%llu pic irr=%02X isr=%02X imr=%02X tr=%04X\\n",
               (unsigned)C.pg, (unsigned long)C.cr3, (unsigned long)C.cr2,
               b86_pg_stat_faults, b86_pg_stat_tswitch, b86_pg_stat_walks, b86_pg_stat_flush,
               (unsigned long long)C.icount, (unsigned)bb_irq36.irr, (unsigned)bb_irq36.isr,
               (unsigned)bb_irq36.imr, (unsigned)C.tr_sel);
    }
    printf("[bb386-pm]   code@%08lX:", (unsigned long)lin);"""),
("progress cadence",
"""        if ((bb386_pm_slices & (bb386_pm_slices - 1u)) == 0u && bb386_pm_slices >= 2u) {""",
"""        if (((bb386_pm_slices & (bb386_pm_slices - 1u)) == 0u && bb386_pm_slices >= 2u) ||
            (bb386_pm_slices & 4095u) == 0u) {   /* BB386_PGSTAT_V1 */"""),
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
    for name, old, new in EDITS: s = s.replace(old, new, 1)
    bak = PATH + ".pre_pgstat_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB386_PGSTAT_V1 applied to", PATH); return 0
if __name__ == "__main__":
    sys.exit(main())
