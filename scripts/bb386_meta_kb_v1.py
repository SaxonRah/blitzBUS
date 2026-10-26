#!/usr/bin/env python3
"""BB386_META_KB_V1: make the real-mode JIT metadata arena size configurable.

bb_meta (PSRAM) is 896 KiB but Descent runs show used=637488 bytes, constant
for the whole session (fixed tables allocated at start; failures=0). The
free ~273 KiB can go to PJ's code buffer, whose size decides how often hot
protected-mode code is evicted:

    $env:BB_META_KB    = '656'     # 671,744 bytes, ~34 KiB above observed use
    $env:BB_PJ_CODE_KB = '1008'    # was 768; total PSRAM use is unchanged

Without BB_META_KB set nothing changes. Watch [bb-meta-usage] failures=0.
Usage: python .\\scripts\\bb386_meta_kb_v1.py   (then rebuild). Safe to run twice.
"""
import os, sys
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INST = os.path.join(ROOT, "scripts", "install_live.py")
OLD = '{(\" BB_PJ_CODE_KB=\"+os.environ[\"BB_PJ_CODE_KB\"]) if os.environ.get(\"BB_PJ_CODE_KB\") else \"\"}'
NEW = OLD + '{(\" BB_META_BYTES=\"+str(int(os.environ[\"BB_META_KB\"])*1024)+\"u\") if os.environ.get(\"BB_META_KB\") else \"\"}'
def main():
    t = open(INST, newline="").read()
    if "BB_META_KB" in t:
        print("install_live.py: already applied"); return 0
    if t.count(OLD) != 1:
        print("ABORT: BB_PJ_CODE_KB option not found in install_live.py (apply bb386_pj_v1.py first)"); return 1
    bak = INST + ".pre_meta_kb_v1"
    if not os.path.exists(bak): open(bak, "w", newline="").write(t)
    open(INST, "w", newline="").write(t.replace(OLD, NEW, 1))
    print("BB386_META_KB_V1 applied to", INST)
    return 0
if __name__ == "__main__":
    sys.exit(main())
