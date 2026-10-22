#!/usr/bin/env python3
"""BB386_PMRAM_V1: run blitz86's protected-mode hot path from SRAM.

On the Pico every protected-mode instruction ran through ~15 flash cache
misses (the 16 KiB XIP cache also fronts PSRAM guest memory, so code and
data evict each other). blitz86 r69 marks the hot path (PM40, fetch window,
page walk, PM dispatch, 386 run loop) B86_PM_HOT; with B86_PM_RAM=1 it goes
to .time_critical (SRAM). It needs about 18 KiB, so lower the real-mode JIT
code cache:   $env:BB_CODE_KB = '200'
Set $env:BB_PM_RAM = '0' to build without it.

Usage: python .\\scripts\\bb386_pmram_v1.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(ROOT, "scripts", "install_live.py")
OLD = "B86_RAM_FUNCS=1 B86_TV_SRAM="
NEW = "B86_RAM_FUNCS=1 B86_PM_RAM={os.environ.get(\"BB_PM_RAM\",\"1\")} B86_TV_SRAM="
def main():
    s = open(PATH, newline="").read()
    if "B86_PM_RAM=" in s:
        print("already applied"); return 0
    if s.count(OLD) != 1:
        print("ABORT: could not find '%s' in install_live.py; add B86_PM_RAM=1 to the "
              "blitzbus_pico_b86_dos compile definitions by hand" % OLD); return 1
    bak = PATH + ".pre_pmram_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(s)
    open(PATH, "w", newline="").write(s.replace(OLD, NEW, 1))
    print("BB386_PMRAM_V1 applied to", PATH)
    print("Now rebuild with a smaller real-mode code cache, e.g.  $env:BB_CODE_KB = '200'")
    return 0
if __name__ == "__main__":
    sys.exit(main())
