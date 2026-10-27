#!/usr/bin/env python3
"""BB386_PJ_V1B: place the PJ code buffer after the guest RAM in PSRAM.

The PSRAM sections are laid out by name. "bb_pj_code" sorted before
"md_guest", whose buffer is 2 MiB-aligned in the paged build, so the
512 KiB buffer pushed the guest to the next 2 MiB boundary and PSRAM
overflowed by ~1 MiB. Renaming it "zzz_bb_pj_code" puts it at the end,
after "zz_md_disk", like the existing disk buffer.

Usage: python .\\scripts\\bb386_pj_v1b.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIVE = os.path.join(ROOT, "src", "bb_live.c")
PJ = os.path.join(ROOT, "scripts", "bb386_pj_v1.py")
OLD, NEW = '__uninitialized_psram("bb_pj_code")', '__uninitialized_psram("zzz_bb_pj_code")'
def fix(path):
    s = open(path, newline="").read()
    if NEW in s: print(path + ": already applied"); return 0
    if OLD not in s: print(path + ": PJ PSRAM buffer not found (apply bb386_pj_v1.py first)"); return 1
    open(path, "w", newline="").write(s.replace(OLD, NEW))
    print("BB386_PJ_V1B applied to", path); return 0
def main():
    rc = fix(LIVE)
    if os.path.exists(PJ): fix(PJ)          # keep the installer in step for later re-runs
    return rc
if __name__ == "__main__":
    sys.exit(main())
