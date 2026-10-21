#!/usr/bin/env python3
"""BB386_PGSTAT_V2: add wall time and PM dispatch-memo counters to the
[bb386-pm] statistics line (on top of BB386_PGSTAT_V1). Needs blitz86 r66.

    [bb386-pm]   pg=.. ... tr=.. t=12345ms memo=hits/misses/fallbacks

Usage: python .\\scripts\\bb386_pgstat_v2.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_PGSTAT_V2"
OLD1 = '''        extern unsigned long b86_pg_stat_faults, b86_pg_stat_tswitch, b86_pg_stat_walks, b86_pg_stat_flush;
        printf("[bb386-pm]   pg=%u cr3=%08lX cr2=%08lX pf=%lu tsw=%lu walks=%lu flush=%lu icount=%llu pic irr=%02X isr=%02X imr=%02X tr=%04X\\n",'''
NEW1 = '''        extern unsigned long b86_pg_stat_faults, b86_pg_stat_tswitch, b86_pg_stat_walks, b86_pg_stat_flush;
        extern unsigned long b86_pm_memo_hits, b86_pm_memo_misses, b86_pm_memo_fallbacks;   /* BB386_PGSTAT_V2 */
        printf("[bb386-pm]   pg=%u cr3=%08lX cr2=%08lX pf=%lu tsw=%lu walks=%lu flush=%lu icount=%llu pic irr=%02X isr=%02X imr=%02X tr=%04X t=%lums memo=%lu/%lu/%lu\\n",'''
OLD2 = '''               (unsigned)bb_irq36.imr, (unsigned)C.tr_sel);'''
NEW2 = '''               (unsigned)bb_irq36.imr, (unsigned)C.tr_sel,
               (unsigned long)(time_us_64() / 1000u),
               b86_pm_memo_hits, b86_pm_memo_misses, b86_pm_memo_fallbacks);'''
def main():
    s = open(PATH, newline="").read()
    if MARK in s:
        print("already applied"); return 0
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    for name, old in (("format", OLD1), ("arguments", OLD2)):
        if s.count(old) != 1:
            print(f"ABORT: anchor '{name}' found {s.count(old)} times (apply bb386_pgstat_v1.py first); bb_live.c unchanged")
            return 1
    s = s.replace(OLD1, NEW1, 1).replace(OLD2, NEW2, 1)
    bak = PATH + ".pre_pgstat_v2"
    if not os.path.exists(bak): open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB386_PGSTAT_V2 applied to", PATH); return 0
if __name__ == "__main__":
    sys.exit(main())
