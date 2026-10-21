#!/usr/bin/env python3
"""BB386_PMSLICE_V1: longer time slices while the 386 is in protected mode.

The 1 ms slice timer ends every b86_jit_run. In protected mode the
interpreter only managed ~16-45 instructions per slice, and the work
blitzBUS does between slices took roughly 0.6 ms of every 1 ms, so most of
the time went to slice overhead rather than guest code. While CR0.PE=1
this patch keeps re-entering b86_jit_run for up to BB386_PM_SLICE_US
(default 8000 us) when the only reason it stopped was the slice tick.
Real mode is unchanged. Instruction accounting (C.icnt) accumulates across
the re-entries.

Usage: python .\\scripts\\bb386_pmslice_v1.py  (then rebuild). Safe to run twice.
Build with -DBB386_PM_SLICE_US=0 to disable.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "src", "bb_live.c")
MARK = "BB386_PMSLICE_V1"
OLD = "        rc=b86_jit_run(&C, bb_v10_budget);\n"
NEW = """        rc=b86_jit_run(&C, bb_v10_budget);
    /* BB386_PMSLICE_V1: protected mode keeps the CPU for several slice ticks. */
#ifndef BB386_PM_SLICE_US
#define BB386_PM_SLICE_US 8000u
#endif
    if (BB386_PM_SLICE_US && C.model >= B86_CPU_386) {
        while (rc == B86_EXIT && (C.msw & 1u) && C.irq == 1u &&
               bb_now_us() - v24_jit_t0 < (uint64_t)BB386_PM_SLICE_US) {
            C.irq = 0u;
            rc = b86_jit_run(&C, bb_v10_budget);
        }
    }
"""
def main():
    s = open(PATH, newline="").read()
    if MARK in s:
        print("already applied"); return 0
    crlf = "\r\n" in s
    if crlf: s = s.replace("\r\n", "\n")
    if s.count(OLD) != 1:
        print(f"ABORT: anchor found {s.count(OLD)} times; bb_live.c unchanged"); return 1
    s = s.replace(OLD, NEW, 1)
    bak = PATH + ".pre_pmslice_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(open(PATH, newline="").read())
    if crlf: s = s.replace("\n", "\r\n")
    open(PATH, "w", newline="").write(s)
    print("BB386_PMSLICE_V1 applied to", PATH); return 0
if __name__ == "__main__":
    sys.exit(main())
